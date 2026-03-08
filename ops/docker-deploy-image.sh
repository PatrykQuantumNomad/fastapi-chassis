#!/usr/bin/env bash
set -euo pipefail

# Pull a published image and replace a single named container on the target
# host. This path is useful for simple VM deployments that do not need Compose.
IMAGE_NAME="${IMAGE_NAME:?Set IMAGE_NAME to the registry/repository name}"
IMAGE_NAME="${IMAGE_NAME,,}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_NAME="${CONTAINER_NAME:-fastapi-template}"
HOST_PORT="${HOST_PORT:-8000}"
CONTAINER_PORT="${CONTAINER_PORT:-8000}"
ENV_FILE="${ENV_FILE:-.env}"
DATA_DIR="${DATA_DIR:-./data}"
REGISTRY_HOST="${REGISTRY_HOST:-ghcr.io}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-90}"
VERIFY_HOST="${VERIFY_HOST:-127.0.0.1}"
VERIFY_HOST_HEADER="${VERIFY_HOST_HEADER:-}"
VERIFY_SCHEME="${VERIFY_SCHEME:-http}"
VERIFY_TIMEOUT_SECONDS="${VERIFY_TIMEOUT_SECONDS:-5}"
ROLLBACK_CONTAINER_NAME="${CONTAINER_NAME}-rollback"

current_container_status() {
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1"
}

resolve_readiness_path() {
  docker exec "$1" python -c 'import os; print(os.environ.get("APP_READINESS_CHECK_PATH", "/ready"))'
}

wait_for_container_ready() {
  local container_name="$1"
  local deadline="$2"

  while true; do
    status="$(current_container_status "${container_name}")"

    if [[ "${status}" == "healthy" ]]; then
      if docker exec "${container_name}" python /app/ops/http_probe.py \
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

rollback_previous_container() {
  if docker container inspect "${ROLLBACK_CONTAINER_NAME}" >/dev/null 2>&1; then
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker rename "${ROLLBACK_CONTAINER_NAME}" "${CONTAINER_NAME}"
    docker start "${CONTAINER_NAME}" >/dev/null
  fi
}

# Fail fast when deployment inputs are missing instead of falling back to
# incomplete defaults that may start a broken container.
if [[ ! -s "${ENV_FILE}" ]]; then
  echo "Missing or empty env file: ${ENV_FILE}" >&2
  exit 1
fi

mkdir -p "${DATA_DIR}"

if [[ -n "${REGISTRY_USERNAME:-}" && -n "${REGISTRY_PASSWORD:-}" ]]; then
  echo "${REGISTRY_PASSWORD}" | docker login "${REGISTRY_HOST}" --username "${REGISTRY_USERNAME}" --password-stdin
fi

docker pull "${IMAGE_REF}"

# Preserve the previous container under a rollback name instead of deleting it
# before the replacement proves it is healthy.
docker rm -f "${ROLLBACK_CONTAINER_NAME}" >/dev/null 2>&1 || true
if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  docker stop "${CONTAINER_NAME}" >/dev/null
  docker rename "${CONTAINER_NAME}" "${ROLLBACK_CONTAINER_NAME}"
fi

# The container image owns the application startup path; this script only injects
# runtime configuration, networking, and persistent storage.
if ! docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /var/tmp \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --env-file "${ENV_FILE}" \
  -e APP_HOST=0.0.0.0 \
  -e APP_PORT="${CONTAINER_PORT}" \
  -p "${HOST_PORT}:${CONTAINER_PORT}" \
  -v "${DATA_DIR}:/app/data" \
  "${IMAGE_REF}"; then
  echo "Failed to start replacement container." >&2
  rollback_previous_container
  exit 1
fi

deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
if ! wait_for_container_ready "${CONTAINER_NAME}" "${deadline}"; then
  status="$(current_container_status "${CONTAINER_NAME}")"
  echo "Deployment failed with status: ${status}" >&2
  docker logs "${CONTAINER_NAME}" || true
  rollback_previous_container
  exit 1
fi

readiness_path="$(resolve_readiness_path "${CONTAINER_NAME}")"
if ! verify_host_readiness "${IMAGE_REF}" "${HOST_PORT}" "${readiness_path}"; then
  echo "Deployment failed host-level verification on ${VERIFY_SCHEME}://${VERIFY_HOST}:${HOST_PORT}${readiness_path}" >&2
  docker logs "${CONTAINER_NAME}" || true
  rollback_previous_container
  exit 1
fi

docker rm -f "${ROLLBACK_CONTAINER_NAME}" >/dev/null 2>&1 || true
echo "Deployment is healthy, ready, and externally reachable."
