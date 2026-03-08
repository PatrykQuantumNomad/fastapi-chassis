#!/usr/bin/env bash
set -euo pipefail

# Build the application image locally and optionally push the tagged result.
# The defaults keep local usage simple while still stamping OCI metadata when
# the build runs in CI or from a checked-out git repository.
DEFAULT_IMAGE_NAME="${GITHUB_REPOSITORY:-fastapi-template}"
IMAGE_NAME="${IMAGE_NAME:-$DEFAULT_IMAGE_NAME}"
IMAGE_NAME="${IMAGE_NAME,,}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo local)}"
PUSH_IMAGE="${PUSH_IMAGE:-false}"
BUILD_DATE="${BUILD_DATE:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
VCS_REF="${VCS_REF:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
REPOSITORY_URL="${REPOSITORY_URL:-$(git config --get remote.origin.url 2>/dev/null || true)}"
VERSION="${VERSION:-${IMAGE_TAG}}"

# Normalize common GitHub remote formats so OCI labels get a browsable URL.
if [[ "${REPOSITORY_URL}" =~ ^git@github\.com:(.+)\.git$ ]]; then
  REPOSITORY_URL="https://github.com/${BASH_REMATCH[1]}"
elif [[ "${REPOSITORY_URL}" =~ ^https://github\.com/.+\.git$ ]]; then
  REPOSITORY_URL="${REPOSITORY_URL%.git}"
fi

# Keep metadata wiring in one place so local builds and CI builds stamp the
# same Dockerfile args consistently.
build_args=(
  --build-arg "BUILD_DATE=${BUILD_DATE}"
  --build-arg "VCS_REF=${VCS_REF}"
  --build-arg "VERSION=${VERSION}"
)

if [[ -n "${REPOSITORY_URL}" ]]; then
  build_args+=(--build-arg "REPOSITORY_URL=${REPOSITORY_URL}")
fi

# Always tag the content-addressed build and a moving latest tag for convenience.
docker build \
  --file Dockerfile \
  "${build_args[@]}" \
  --tag "${IMAGE_NAME}:${IMAGE_TAG}" \
  --tag "${IMAGE_NAME}:latest" \
  .

# Push is opt-in so local iteration does not require registry credentials.
if [[ "${PUSH_IMAGE}" == "true" ]]; then
  docker push "${IMAGE_NAME}:${IMAGE_TAG}"
  docker push "${IMAGE_NAME}:latest"
fi
