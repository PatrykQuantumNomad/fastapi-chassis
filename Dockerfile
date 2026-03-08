# syntax=docker/dockerfile:1.7

# Keep base images pinned by digest so rebuilds stay reproducible.
# Use ARG-based references so ops/refresh-docker-base-digests.sh can update
# digests automatically.
ARG UV_BASE_IMAGE=ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca
ARG PYTHON_RUNTIME_IMAGE=python:3.13-slim-bookworm@sha256:1245b6c39d0b8e49e911c7d07b60cd9ed26016b0e439b6903d5e08730e417553

FROM ${UV_BASE_IMAGE} AS builder

ENV UV_LINK_MODE=copy

WORKDIR /app

# Install tini once in the builder, pinned to the current Debian package version,
# then copy the binary into the final image without carrying apt tooling forward.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    apt-get install --yes --no-install-recommends tini=0.19.0-1+b3 && \
    rm -rf /var/lib/apt/lists/*

ARG UV_EXTRAS="--extra postgres --extra redis"

COPY pyproject.toml uv.lock README.md ./
# Resolve third-party dependencies first so source-only changes reuse this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project ${UV_EXTRAS}

COPY src /app/src
COPY alembic /app/alembic
COPY main.py alembic.ini /app/
COPY ops/docker-entrypoint.sh ops/http_probe.py /app/ops/

# Install the local project into the virtualenv after the application files exist.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable ${UV_EXTRAS}

# The runtime stage stays slim: only Python, the app virtualenv, runtime files,
# and the init binary required for signal forwarding/reaping are copied across.
FROM ${PYTHON_RUNTIME_IMAGE} AS runtime

ARG BUILD_DATE=unknown
ARG REPOSITORY_URL=
ARG VCS_REF=unknown
ARG VERSION=dev

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/src"

LABEL org.opencontainers.image.title="fastapi-template" \
      org.opencontainers.image.description="Production-ready FastAPI template with Builder pattern configuration" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="${REPOSITORY_URL}" \
      org.opencontainers.image.url="${REPOSITORY_URL}" \
      org.opencontainers.image.documentation="${REPOSITORY_URL}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}"

WORKDIR /app

# Use stable high IDs so mounted volumes keep predictable ownership across rebuilds
# and orchestrators can set matching runAsUser/runAsGroup values explicitly.
RUN groupadd --system --gid 10001 app && \
    useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/app app && \
    install -d -o app -g app /app/data

COPY --from=builder /usr/bin/tini /usr/bin/tini
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/alembic /app/alembic
COPY --from=builder --chown=app:app /app/src /app/src
COPY --from=builder --chown=app:app /app/main.py /app/alembic.ini /app/
COPY --from=builder --chown=app:app --chmod=755 /app/ops/docker-entrypoint.sh /app/ops/docker-entrypoint.sh
COPY --from=builder --chown=app:app /app/ops/http_probe.py /app/ops/http_probe.py

EXPOSE 8000

# Healthcheck stays separate from readiness so container platforms can detect
# dead processes quickly without needing external orchestration logic.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python /app/ops/http_probe.py --path-env APP_HEALTH_CHECK_PATH --default-path /healthcheck

USER app

# tini becomes PID 1 and forwards signals to the entrypoint/app correctly.
ENTRYPOINT ["/usr/bin/tini", "--", "/app/ops/docker-entrypoint.sh"]
