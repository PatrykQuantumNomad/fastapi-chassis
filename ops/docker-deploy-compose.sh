#!/usr/bin/env bash
set -euo pipefail

# Pull and restart the Compose-based deployment using a published image tag.
# This path fits remote hosts where Compose manages named volumes or multiple
# services, even if this template currently only defines the app service.
IMAGE_NAME="${IMAGE_NAME:?Set IMAGE_NAME to the registry/repository name}"
IMAGE_NAME="${IMAGE_NAME,,}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
REQUESTED_IMAGE_TAG="${IMAGE_TAG}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.deploy.yml}"
PROJECT_NAME="${PROJECT_NAME:-fastapi-template}"
ENV_FILE="${ENV_FILE:-.env}"
REGISTRY_HOST="${REGISTRY_HOST:-ghcr.io}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-90}"
VERIFY_HOST="${VERIFY_HOST:-127.0.0.1}"
VERIFY_HOST_HEADER="${VERIFY_HOST_HEADER:-}"
VERIFY_SCHEME="${VERIFY_SCHEME:-http}"
VERIFY_TIMEOUT_SECONDS="${VERIFY_TIMEOUT_SECONDS:-5}"
ROLLBACK_IMAGE_TAG="${ROLLBACK_IMAGE_TAG:-rollback-${PROJECT_NAME}}"
ROLLBACK_IMAGE_REF="${IMAGE_NAME}:${ROLLBACK_IMAGE_TAG}"
COMPOSE_ARGS=(
  --project-name "${PROJECT_NAME}"
  --file "${COMPOSE_FILE}"
  --env-file "${ENV_FILE}"
)

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "Missing compose file: ${COMPOSE_FILE}" >&2
  exit 1
fi

if [[ ! -s "${ENV_FILE}" ]]; then
  echo "Missing or empty env file: ${ENV_FILE}" >&2
  exit 1
fi

if [[ -n "${REGISTRY_USERNAME:-}" && -n "${REGISTRY_PASSWORD:-}" ]]; then
  echo "${REGISTRY_PASSWORD}" | docker login "${REGISTRY_HOST}" --username "${REGISTRY_USERNAME}" --password-stdin
fi

# Export image variables so Compose can substitute them inside the deployment
# file without hard-coding registry coordinates into version-controlled YAML.
export IMAGE_NAME IMAGE_TAG ENV_FILE

compose() {
  docker compose "${COMPOSE_ARGS[@]}" "$@"
}

current_container_id() {
  compose ps -q app
}

current_container_status() {
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1"
}

resolve_readiness_path() {
  docker exec "$1" python -c 'import os; print(os.environ.get("APP_READINESS_CHECK_PATH", "/ready"))'
}

resolve_host_port() {
  docker port "$1" 8000/tcp | awk -F: 'NR==1 {print $NF}'
}

wait_for_compose_ready() {
  local container_id="$1"
  local deadline="$2"

  while true; do
    local status
    status="$(current_container_status "${container_id}")"

    if [[ "${status}" == "healthy" ]]; then
      if docker exec "${container_id}" python /app/ops/http_probe.py \
        --path-env APP_READINESS_CHECK_PATH \
        --default-path /ready >/dev/null 2>&1; then
        return 0
      fi
    fi

    if [[ "${status}" == "unhealthy" || "${status}" == "exited" || "${status}" == "dead" ]]; then
      return 1
    fi

    if (( SECONDS >= deadline )); then
      return 1
    fi

    sleep 3
  done
}

verify_host_readiness() {
  local image_ref="$1"
  local host_port="$2"
  local readiness_path="$3"

  local probe_args=(
    --network host
    "${image_ref}"
    python /app/ops/http_probe.py
    --scheme "${VERIFY_SCHEME}"
    --host "${VERIFY_HOST}"
    --port "${host_port}"
    --path "${readiness_path}"
    --path-env APP_READINESS_CHECK_PATH
    --default-path /ready
    --timeout "${VERIFY_TIMEOUT_SECONDS}"
  )

  if [[ -n "${VERIFY_HOST_HEADER}" ]]; then
    probe_args+=(--host-header "${VERIFY_HOST_HEADER}")
  fi

  docker run --rm "${probe_args[@]}" >/dev/null 2>&1
}

rollback_compose_deployment() {
  if ! docker image inspect "${ROLLBACK_IMAGE_REF}" >/dev/null 2>&1; then
    echo "No rollback image is available for compose deployment." >&2
    return 1
  fi

  export IMAGE_TAG="${ROLLBACK_IMAGE_TAG}"
  compose up -d --remove-orphans

  local rollback_container_id
  rollback_container_id="$(current_container_id)"
  if [[ -z "${rollback_container_id}" ]]; then
    echo "Rollback did not recreate the compose app container." >&2
    return 1
  fi

  local deadline
  deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  if ! wait_for_compose_ready "${rollback_container_id}" "${deadline}"; then
    echo "Rollback container failed readiness checks." >&2
    compose logs --no-color
    return 1
  fi

  local readiness_path
  readiness_path="$(resolve_readiness_path "${rollback_container_id}")"
  local host_port
  host_port="$(resolve_host_port "${rollback_container_id}")"
  if [[ -z "${host_port}" ]]; then
    echo "Could not resolve the published host port during rollback verification." >&2
    compose logs --no-color
    return 1
  fi

  if ! verify_host_readiness "${ROLLBACK_IMAGE_REF}" "${host_port}" "${readiness_path}"; then
    echo "Rollback container failed host-level verification." >&2
    compose logs --no-color
    return 1
  fi

  echo "Rollback restored the previous compose deployment."
  return 0
}

previous_container_id="$(current_container_id || true)"
if [[ -n "${previous_container_id}" ]]; then
  previous_image_id="$(docker inspect --format '{{.Image}}' "${previous_container_id}")"
  docker tag "${previous_image_id}" "${ROLLBACK_IMAGE_REF}"
fi

compose pull
compose up -d --remove-orphans

# Resolve the concrete container ID after `up` because Compose may recreate the
# service container even when the logical service name stays the same.
container_id="$(current_container_id)"
if [[ -z "${container_id}" ]]; then
  echo "Compose deployment did not create the app container." >&2
  rollback_compose_deployment || true
  exit 1
fi

image_ref="$(docker inspect --format '{{.Config.Image}}' "${container_id}")"

# Like the single-container path, wait on the Docker health status so callers
# get a real success/failure signal instead of a fire-and-forget restart.
deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
if ! wait_for_compose_ready "${container_id}" "${deadline}"; then
  status="$(current_container_status "${container_id}")"
  echo "Compose deployment failed with status: ${status}" >&2
  compose logs --no-color
  rollback_compose_deployment || true
  exit 1
fi

readiness_path="$(resolve_readiness_path "${container_id}")"
host_port="$(resolve_host_port "${container_id}")"
if [[ -z "${host_port}" ]]; then
  echo "Could not resolve the published host port for the app container." >&2
  compose logs --no-color
  rollback_compose_deployment || true
  exit 1
fi

if ! verify_host_readiness "${image_ref}" "${host_port}" "${readiness_path}"; then
  echo "Compose deployment failed host-level verification on ${VERIFY_SCHEME}://${VERIFY_HOST}:${host_port}${readiness_path}" >&2
  compose logs --no-color
  rollback_compose_deployment || true
  exit 1
fi

if docker image inspect "${ROLLBACK_IMAGE_REF}" >/dev/null 2>&1; then
  docker image rm "${ROLLBACK_IMAGE_REF}" >/dev/null 2>&1 || true
fi

echo "Compose deployment for tag ${REQUESTED_IMAGE_TAG} is healthy, ready, and externally reachable."
