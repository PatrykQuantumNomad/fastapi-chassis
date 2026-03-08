#!/usr/bin/env bash
set -euo pipefail

# Refresh the pinned base-image digests in Dockerfile using the current
# manifest-list digests published by the upstream image repositories.
DOCKERFILE_PATH="${DOCKERFILE_PATH:-Dockerfile}"
UV_BASE_TAG="${UV_BASE_TAG:-ghcr.io/astral-sh/uv:python3.13-bookworm-slim}"
PYTHON_RUNTIME_TAG="${PYTHON_RUNTIME_TAG:-python:3.13-slim-bookworm}"
DRY_RUN="${DRY_RUN:-false}"

if [[ ! -f "${DOCKERFILE_PATH}" ]]; then
  echo "Dockerfile not found: ${DOCKERFILE_PATH}" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to refresh base image digests." >&2
  exit 1
fi

if ! docker buildx version >/dev/null 2>&1; then
  echo "docker buildx is required to refresh base image digests." >&2
  exit 1
fi

# Resolve the top-level digest so the Dockerfile keeps multi-architecture
# support instead of pinning a single platform-specific child manifest.
resolve_digest() {
  local image_ref="$1"
  local digest

  digest="$(
    docker buildx imagetools inspect "${image_ref}" \
      | awk '/^Digest:/ {print $2; exit}'
  )"

  if [[ -z "${digest}" ]]; then
    echo "Failed to resolve digest for ${image_ref}" >&2
    exit 1
  fi

  printf '%s' "${digest}"
}

uv_digest="$(resolve_digest "${UV_BASE_TAG}")"
python_digest="$(resolve_digest "${PYTHON_RUNTIME_TAG}")"

new_uv_arg="ARG UV_BASE_IMAGE=${UV_BASE_TAG}@${uv_digest}"
new_python_arg="ARG PYTHON_RUNTIME_IMAGE=${PYTHON_RUNTIME_TAG}@${python_digest}"

# Dry-run mode is useful in CI checks or review workflows where you want to
# show the proposed replacements without mutating the working tree.
if [[ "${DRY_RUN}" == "true" ]]; then
  echo "${new_uv_arg}"
  echo "${new_python_arg}"
  exit 0
fi

# Use a tiny Python rewrite step so only the two ARG lines are replaced and the
# rest of the Dockerfile formatting stays untouched.
DOCKERFILE_PATH="${DOCKERFILE_PATH}" \
NEW_UV_ARG="${new_uv_arg}" \
NEW_PYTHON_ARG="${new_python_arg}" \
python <<'PY'
from pathlib import Path
import os
import re

dockerfile_path = Path(os.environ["DOCKERFILE_PATH"])
content = dockerfile_path.read_text()

content, uv_count = re.subn(
    r"^ARG UV_BASE_IMAGE=.*$",
    os.environ["NEW_UV_ARG"],
    content,
    count=1,
    flags=re.MULTILINE,
)
content, python_count = re.subn(
    r"^ARG PYTHON_RUNTIME_IMAGE=.*$",
    os.environ["NEW_PYTHON_ARG"],
    content,
    count=1,
    flags=re.MULTILINE,
)

if uv_count != 1 or python_count != 1:
    raise SystemExit("Failed to update pinned image args in Dockerfile")

dockerfile_path.write_text(content)
PY

echo "Updated ${DOCKERFILE_PATH}"
echo "  ${new_uv_arg}"
echo "  ${new_python_arg}"
