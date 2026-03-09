# VM Deployment

This document covers deploying FastAPI Chassis to virtual machines or bare-metal
servers using Docker. For Kubernetes deployments, see
[`docs/helm-chart.md`](helm-chart.md).

## Prerequisites

The target host needs:

- Docker Engine (20.10+)
- Docker Compose v2 plugin (only for the Compose deployment path)
- SSH access from the deployment source (your machine or GitHub Actions runner)
- Outbound network access to pull images from the container registry
- A writable directory for deployment assets and persistent data

## Deployment Paths

Two deployment paths are available. Both include health verification, readiness
probing, and automatic rollback on failure.

| Path | Script | Workflow | Make Target | Best For |
| --- | --- | --- | --- | --- |
| Single container | `ops/docker-deploy-image.sh` | `deploy-image.yml` | `make docker-deploy-image` | Simple single-service deployments |
| Docker Compose | `ops/docker-deploy-compose.sh` | `deploy-compose.yml` | `make docker-deploy-compose` | Multi-service stacks (app + Postgres + Redis) |

## Single Container Deployment

Pulls a published image and runs it with `docker run`. Suitable for SQLite
backends or when external databases are managed separately.

### How It Works

1. Authenticates with the container registry (if credentials are set).
2. Pulls the target image tag.
3. Stops the current container and renames it as a rollback candidate.
4. Starts the new container with security hardening:
   - read-only root filesystem
   - `cap-drop ALL`
   - `no-new-privileges`
   - `unless-stopped` restart policy
5. Waits for Docker HEALTHCHECK to report healthy.
6. Verifies the `/ready` endpoint inside the container.
7. Verifies readiness from the host network (catches port binding and proxy
   issues).
8. Rolls back to the previous container if any check fails.
9. Removes the rollback container on success.

### Script Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `IMAGE_NAME` | Yes | — | Registry/repository (e.g. `ghcr.io/org/fastapi-chassis`) |
| `IMAGE_TAG` | No | `latest` | Image tag to deploy |
| `ENV_FILE` | No | `.env` | Path to the env file with app configuration |
| `HOST_PORT` | No | `8000` | Port published on the host |
| `CONTAINER_PORT` | No | `8000` | Port inside the container |
| `CONTAINER_NAME` | No | `fastapi-chassis` | Docker container name |
| `DATA_DIR` | No | `./data` | Host directory mounted to `/app/data` |
| `REGISTRY_HOST` | No | `ghcr.io` | Container registry hostname |
| `REGISTRY_USERNAME` | No | — | Registry auth username |
| `REGISTRY_PASSWORD` | No | — | Registry auth password or token |
| `HEALTH_TIMEOUT_SECONDS` | No | `90` | Max seconds to wait for healthy status |
| `VERIFY_HOST` | No | `127.0.0.1` | Host address for post-deploy verification |
| `VERIFY_SCHEME` | No | `http` | Scheme for verification (`http` or `https`) |
| `VERIFY_HOST_HEADER` | No | — | Optional Host header override for proxy setups |
| `VERIFY_TIMEOUT_SECONDS` | No | `5` | Timeout for the verification probe |

### Manual Usage

```bash
IMAGE_NAME=ghcr.io/your-org/fastapi-chassis \
IMAGE_TAG=1.2.3 \
ENV_FILE=/opt/app/.env \
DATA_DIR=/opt/app/data \
  ./ops/docker-deploy-image.sh
```

Or via Make:

```bash
IMAGE_NAME=ghcr.io/your-org/fastapi-chassis \
IMAGE_TAG=1.2.3 \
ENV_FILE=/opt/app/.env \
  make docker-deploy-image
```

## Docker Compose Deployment

Deploys using `docker compose up`. Use this when the host should manage the
app alongside dependent services, or when you want Compose to handle volumes
and networks.

### How It Works

Same verification and rollback logic as the single container path, driven by
`docker compose up -d` instead of `docker run`. The script tags the currently
running image as a local rollback candidate before pulling the replacement. If
the new deployment fails health, readiness, or host-level verification, the
helper automatically redeploys the rollback tag.

### Compose File

The production compose file is `docker-compose.deploy.yml`. It defines a
single hardened app service:

- Read-only root filesystem with tmpfs for `/tmp` and `/var/tmp`
- `cap_drop: ALL` and `no-new-privileges`
- Resource limits (1 CPU, 512M memory by default)
- JSON file log driver with rotation (10M max, 3 files)
- Named volume for `/app/data`
- Bridge network isolation

Extend it with additional services (Postgres, Redis) by layering compose files
or editing the deployment file on the target host.

### Script Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `IMAGE_NAME` | Yes | — | Registry/repository |
| `IMAGE_TAG` | No | `latest` | Image tag to deploy |
| `COMPOSE_FILE` | No | `docker-compose.deploy.yml` | Path to the compose file |
| `PROJECT_NAME` | No | `fastapi-chassis` | Compose project name |
| `ENV_FILE` | No | `.env` | Path to the env file |
| `REGISTRY_HOST` | No | `ghcr.io` | Container registry hostname |
| `REGISTRY_USERNAME` | No | — | Registry auth username |
| `REGISTRY_PASSWORD` | No | — | Registry auth password or token |
| `HEALTH_TIMEOUT_SECONDS` | No | `90` | Max seconds to wait for healthy status |
| `VERIFY_HOST` | No | `127.0.0.1` | Host address for post-deploy verification |
| `VERIFY_SCHEME` | No | `http` | Scheme for verification |
| `VERIFY_HOST_HEADER` | No | — | Optional Host header override |
| `VERIFY_TIMEOUT_SECONDS` | No | `5` | Timeout for the verification probe |

### Manual Usage

```bash
IMAGE_NAME=ghcr.io/your-org/fastapi-chassis \
IMAGE_TAG=1.2.3 \
ENV_FILE=/opt/app/.env \
COMPOSE_FILE=/opt/app/docker-compose.deploy.yml \
  ./ops/docker-deploy-compose.sh
```

## GitHub Actions Workflows

Both deployment paths have corresponding GitHub Actions workflows that SSH
into a remote VM and execute the deploy scripts.

### Required Repository Secrets

| Secret | Description |
| --- | --- |
| `DEPLOY_HOST` | VM IP address or hostname |
| `DEPLOY_USER` | SSH username on the target host |
| `DEPLOY_SSH_KEY` | SSH private key for authentication |
| `DEPLOY_PORT` | SSH port (defaults to 22) |
| `DEPLOY_PATH` | Remote directory for deployment files (e.g. `/opt/app`) |
| `DEPLOY_ENV_FILE` | Full contents of the `.env` file (all app configuration) |
| `GHCR_USERNAME` | Container registry username |
| `GHCR_TOKEN` | Container registry token or personal access token |

### Workflow Inputs

Both workflows accept these inputs when triggered manually:

| Input | Default | Description |
| --- | --- | --- |
| `image_tag` | `latest` | Image tag to deploy |
| `verify_host` | `127.0.0.1` | Host for post-deploy verification |
| `verify_scheme` | `http` | Scheme for verification |
| `verify_host_header` | — | Optional Host header override |

The image deploy workflow also accepts `host_port` (default `8000`).

### Triggering a Deployment

1. Go to the **Actions** tab in your GitHub repository.
2. Select **Deploy Docker Image** or **Deploy Docker Compose**.
3. Click **Run workflow** and fill in the image tag.
4. The workflow SSHs into the VM, writes the `.env` file from the secret,
   copies the deploy script, and executes it.

### What the Workflow Does

1. Checks out the repository.
2. Creates the remote deployment directory via SSH.
3. Copies the deploy script (and compose file for the compose path) via SCP.
4. Writes the `.env` file from the `DEPLOY_ENV_FILE` secret.
5. Runs the deploy script with all required environment variables exported.

## Application Configuration

Both paths inject an `.env` file into the container. Use one of the bundled
presets as a starting point:

| Preset | Backend | Rate Limit Storage |
| --- | --- | --- |
| `.env.sqlite.example` | SQLite | Memory |
| `.env.sqlite-redis.example` | SQLite | Redis |
| `.env.postgres-redis.example` | Postgres | Redis |

Copy the preset that matches your infrastructure and adjust for production:

```bash
cp .env.postgres-redis.example .env
# Edit .env with production values
```

### Minimum Production Settings

```env
# Database
APP_DATABASE_BACKEND=postgres
APP_DATABASE_POSTGRES_HOST=db.internal
APP_DATABASE_POSTGRES_PORT=5432
APP_DATABASE_POSTGRES_NAME=myapp
APP_DATABASE_POSTGRES_USER=myapp
APP_DATABASE_POSTGRES_PASSWORD=strong-password-here

# Migrations (runs alembic upgrade head on container start)
RUN_DB_MIGRATIONS=true

# Server
APP_HOST=0.0.0.0
APP_PORT=8000
UVICORN_WORKERS=4

# Logging
APP_LOG_LEVEL=INFO
APP_LOG_FORMAT=json

# Security
APP_TRUSTED_HOSTS=["api.example.com"]
APP_CORS_ALLOWED_ORIGINS=["https://app.example.com"]
APP_SECURITY_HSTS_ENABLED=true

# Disable documentation endpoints
APP_DOCS_ENABLED=false
APP_REDOC_ENABLED=false
APP_OPENAPI_ENABLED=false
```

For the full variable reference, see [`docs/configuration.md`](configuration.md).

### Worker Count

The container defaults to `UVICORN_WORKERS=1`, which is correct for
orchestrated environments. For VM deployments, increase the worker count to
match the available CPU cores:

```env
UVICORN_WORKERS=4
```

Keep in mind:

- Each worker is an independent OS process; total RAM scales linearly.
- In-memory rate limiting and caching are per-process. Use Redis when running
  more than one worker.
- SQLite does not support concurrent writes from multiple processes. Use
  Postgres with multiple workers.

### Proxy Headers

When the app sits behind a reverse proxy (Nginx, Caddy, Traefik, ALB),
configure both layers:

```env
# Uvicorn layer: populate request.client from proxy headers
UVICORN_FORWARDED_ALLOW_IPS=10.0.0.0/8

# Application layer: honor X-Forwarded-Proto for HSTS decisions
APP_SECURITY_TRUST_PROXY_PROTO_HEADER=true
APP_SECURITY_TRUSTED_PROXIES=["10.0.0.1/32"]

# Application layer: extract real client IP for rate limiting
APP_RATE_LIMIT_TRUST_PROXY_HEADERS=true
APP_RATE_LIMIT_TRUSTED_PROXIES=["10.0.0.1/32"]
```

## Rollback Behavior

### Single Container

The deploy script preserves the previous container under a rollback name
before starting the replacement. If the new container fails health checks,
readiness, or host-level verification, the script automatically:

1. Removes the failed container.
2. Renames the preserved container back to the original name.
3. Restarts it.

### Docker Compose

The compose deploy script tags the currently running app image as a local
rollback candidate. On failure, it redeploys the compose stack using that
rollback tag. The same three-stage verification (Docker health, container
readiness, host-level readiness) gates the rollback as well.

After automatic rollback, operators should:

1. Review deploy logs to confirm rollback ran.
2. Verify the restored revision is healthy.
3. Retag or redeploy the last known-good release explicitly.
4. Evaluate whether database schema rollback is needed before downgrading code.

## Verification

The deploy scripts verify three layers before reporting success:

1. **Docker HEALTHCHECK**: the built-in container health check
   (`/healthcheck` via `ops/http_probe.py`) transitions to healthy.
2. **Container readiness**: the `/ready` endpoint returns 200 from inside the
   container (checks DB, cache, auth dependencies).
3. **Host-level readiness**: the `/ready` endpoint is reachable from the host
   network through the published port.

Use the `VERIFY_HOST`, `VERIFY_SCHEME`, and `VERIFY_HOST_HEADER` variables to
match the verification probe to the same path that real traffic follows.

## Host Setup Example

A minimal setup for a fresh Ubuntu VM:

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Create deployment directory
sudo mkdir -p /opt/app/data
sudo chown $USER:$USER /opt/app

# Write your .env file
cat <<'EOF' > /opt/app/.env
APP_DATABASE_BACKEND=sqlite
APP_DATABASE_SQLITE_PATH=/app/data/app.db
RUN_DB_MIGRATIONS=true
APP_HOST=0.0.0.0
APP_PORT=8000
APP_LOG_LEVEL=INFO
APP_LOG_FORMAT=json
APP_TRUSTED_HOSTS=["your-domain.com"]
EOF

# Deploy
IMAGE_NAME=ghcr.io/your-org/fastapi-chassis \
IMAGE_TAG=1.0.0 \
ENV_FILE=/opt/app/.env \
DATA_DIR=/opt/app/data \
  ./ops/docker-deploy-image.sh
```

## Reverse Proxy

The deploy scripts run the container directly on a host port. For TLS
termination, host-based routing, or internet exposure, place a reverse proxy
in front of the app.

### Nginx Example

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate     /etc/ssl/certs/api.example.com.pem;
    ssl_certificate_key /etc/ssl/private/api.example.com.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }
}
```

When using a reverse proxy, update the app configuration to match:

```env
APP_TRUSTED_HOSTS=["api.example.com"]
APP_SECURITY_TRUST_PROXY_PROTO_HEADER=true
APP_SECURITY_TRUSTED_PROXIES=["127.0.0.1/32"]
APP_SECURITY_HSTS_ENABLED=true
UVICORN_FORWARDED_ALLOW_IPS=127.0.0.1
```

And set the verification variables so the deploy script probes through the
proxy:

```bash
VERIFY_HOST=127.0.0.1
VERIFY_SCHEME=https
VERIFY_HOST_HEADER=api.example.com
```

## Production Checklist

Before deploying to production:

- [ ] Pin the image tag (never deploy `latest`)
- [ ] Set `UVICORN_WORKERS` to match VM CPU cores
- [ ] Configure `APP_TRUSTED_HOSTS` to your domain(s)
- [ ] Set `APP_CORS_ALLOWED_ORIGINS` to specific origins
- [ ] Use Redis-backed rate limiting for multi-worker deployments
- [ ] Configure proxy header trust only when behind a reverse proxy
- [ ] Set `APP_SECURITY_HSTS_ENABLED=true` when behind HTTPS
- [ ] Disable `APP_DOCS_ENABLED`, `APP_REDOC_ENABLED`, `APP_OPENAPI_ENABLED`
- [ ] Enable `APP_METRICS_ENABLED` only when `/metrics` is intentionally reachable
- [ ] Configure auth verification material if protected routes are enabled
- [ ] Set up log rotation on the host or use Docker's JSON file driver limits
- [ ] Document the backup and restore procedure for your database
- [ ] Test rollback by deploying a known-bad tag and verifying automatic recovery
