# Helm Chart

This document covers deploying FastAPI Chassis to Kubernetes using the included
Helm chart. For the auto-generated values reference, see
[`chart/README.md`](../chart/README.md).

## Prerequisites

- Kubernetes 1.19+
- Helm 3.x
- A container image published to a registry accessible from your cluster

## Quick Start

### Postgres Backend (Default)

```bash
helm install my-app ./chart \
  --set image.tag=1.0.0 \
  --set database.postgres.host=postgres.default \
  --set database.postgres.password=changeme
```

### SQLite Backend

```bash
helm install my-app ./chart \
  --set image.tag=1.0.0 \
  --set database.backend=sqlite \
  --set replicaCount=1
```

### Using a Values File

```bash
helm install my-app ./chart -f my-values.yaml
```

## Architecture Decisions

### Deployment vs StatefulSet

The chart automatically selects the workload kind based on `database.backend`:

- **Postgres or custom**: renders a stateless **Deployment** with a
  `RollingUpdate` strategy.
- **SQLite**: renders a **StatefulSet** with `volumeClaimTemplates` so each pod
  gets a stable PVC for its database file.

Both share the same pod template (defined in `_helpers.tpl` as
`fastapi-chassis.podSpec`), so probes, security context, and container
configuration are identical regardless of backend.

### Security Posture

Every pod runs with:

- `runAsNonRoot: true`, UID/GID `10001`
- `seccompProfile: RuntimeDefault`
- `readOnlyRootFilesystem: true`
- `capabilities: drop: ALL` (except `SYS_ADMIN` when LiteFS is enabled for
  FUSE)
- `automountServiceAccountToken: false`
- Writable directories limited to `/tmp`, `/var/tmp`, and `/app/data` (SQLite
  only), all backed by `emptyDir` volumes with size limits

### Config and Secret Separation

Non-sensitive values go into a **ConfigMap**, sensitive values into a
**Secret**. The pod mounts both via `envFrom`. A checksum annotation on the pod
template forces rolling restarts when either resource changes.

## Database Backends

### Postgres

The default. Set connection details via values:

```yaml
database:
  backend: postgres
  postgres:
    host: postgres.database
    port: 5432
    name: fastapi_chassis
    user: fastapi
    password: ""  # use existingSecret for production
    existingSecret: my-postgres-secret
    existingSecretPasswordKey: password
```

The chart stores the password in its own Secret unless `existingSecret` is set.
When `existingSecret` is provided, the chart injects it as an individual `env`
entry via `secretKeyRef`, and the chart's own Secret skips that key entirely.

### SQLite

Switches the workload to a StatefulSet:

```yaml
database:
  backend: sqlite
  sqlite:
    path: ./data/app.db
    journalMode: wal
    synchronous: normal
    busyTimeout: 5000
    cacheSize: -64000
    mmapSize: 0
    foreignKeys: true
```

Each pod gets its own PVC via the StatefulSet's `volumeClaimTemplates`.
Configure the volume through `persistence.*`:

```yaml
persistence:
  storageClass: gp3  # use high-performance block storage
  accessMode: ReadWriteOnce  # never use RWX with SQLite
  size: 10Gi
```

**Important**: without a replication layer (LiteFS or Litestream), each pod has
an isolated database. Use `replicaCount: 1` unless you have replication
configured.

### Custom URLs

For fully custom database wiring (e.g. managed RDS with IAM auth):

```yaml
database:
  backend: custom
  url: "postgresql+asyncpg://user:pass@rds.example.com:5432/app"
  alembicUrl: "postgresql+psycopg://user:pass@rds.example.com:5432/app"
  existingSecret: my-db-secret  # alternative to inline URLs
  existingSecretUrlKey: DATABASE_URL
  existingSecretAlembicUrlKey: ALEMBIC_DATABASE_URL
```

## Database Migrations

Two approaches are available:

### Helm Hook Job (Recommended)

Runs `alembic upgrade head` as a pre-install/pre-upgrade hook:

```yaml
migrations:
  enabled: true
  backoffLimit: 3
  activeDeadlineSeconds: 120
```

The Job uses the same image, ConfigMap, and Secret as the application pods. It
runs before the main workload starts and is cleaned up automatically on success.

### Container Startup

Runs migrations inside the application container on boot:

```yaml
database:
  runMigrations: true
```

Prefer the hook Job for production since it separates the migration step from
application startup and avoids migration races when multiple pods start
simultaneously.

## SQLite Replication

### Litestream (Disaster Recovery)

Litestream runs as a sidecar that continuously ships WAL changes to object
storage. On pod startup, an init container restores the database if it does not
exist locally.

```yaml
database:
  backend: sqlite

litestream:
  enabled: true
  replica:
    type: s3
    bucket: my-backups
    path: fastapi-chassis/db
    region: us-east-1
    url: s3://my-backups/fastapi-chassis/db  # used by restore init container
    syncInterval: "1s"
    retentionDuration: "720h"
  existingSecret: litestream-creds  # LITESTREAM_ACCESS_KEY_ID, LITESTREAM_SECRET_ACCESS_KEY
```

For IRSA-based access (no static credentials), annotate the ServiceAccount:

```yaml
serviceAccount:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789:role/litestream-role
```

### LiteFS (Horizontal Read Scaling)

LiteFS provides primary-replica replication across pods via a FUSE filesystem.
Its built-in HTTP proxy routes writes to the primary and serves reads locally.

```yaml
database:
  backend: sqlite

litefs:
  enabled: true
  proxy:
    port: 8080
    db: db
    passthrough:
      - "*.css"
      - "*.js"
  lease:
    type: static  # pod-0 is always primary
```

When LiteFS is enabled:

- The LiteFS proxy port (default `8080`) replaces the app port in the Service
- An init container copies the `litefs` binary into a shared volume
- The main container runs via `litefs mount` instead of the default entrypoint
- The pod requires `SYS_ADMIN` capability for FUSE
- A headless Service is created for StatefulSet pod DNS

For dynamic primary election, use Consul:

```yaml
litefs:
  lease:
    type: consul
    consul:
      hostname: "consul.consul:8500"
      key: "litefs/fastapi-chassis"
      ttl: "10s"
```

## Authentication

```yaml
auth:
  enabled: true
  jwtIssuer: https://auth.example.com/
  jwtAudience: fastapi-chassis
  jwtAlgorithms: '["RS256"]'
  jwksUrl: https://auth.example.com/.well-known/jwks.json
```

For shared-secret auth (development only):

```yaml
auth:
  enabled: true
  jwtAlgorithms: '["HS256"]'
  jwtSecret: my-secret-at-least-32-chars-long
```

Production deployments should use `existingSecret`:

```yaml
auth:
  enabled: true
  existingSecret: my-auth-secret
  existingSecretJwtSecretKey: jwt-secret
  existingSecretJwtPublicKeyKey: jwt-public-key
```

## Rate Limiting

```yaml
rateLimit:
  enabled: true
  requests: 100
  windowSeconds: 60
  keyStrategy: ip
  storageBackend: redis  # recommended; memory is per-pod only
  trustProxyHeaders: true

redis:
  host: redis.cache
  port: 6379
  db: 0
  existingSecret: redis-secret
  existingSecretPasswordKey: password
```

When `storageBackend: memory`, limits are per-pod and not shared across
replicas. Use `redis` for consistent enforcement across the deployment.

## Ingress

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "5m"
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: api.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: api-example-com-tls
      hosts:
        - api.example.com
```

When using Ingress, set `security.trustedHosts` to match:

```yaml
security:
  trustedHosts: '["api.example.com"]'
```

## Observability

### Prometheus Metrics

Metrics are enabled by default:

```yaml
metrics:
  enabled: true
  prefix: http
```

### ServiceMonitor

For Prometheus Operator autodiscovery:

```yaml
serviceMonitor:
  enabled: true
  interval: 30s
  scrapeTimeout: 10s
  labels:
    release: prometheus
```

### OpenTelemetry Tracing

```yaml
tracing:
  enabled: true
  serviceName: fastapi-chassis
  environment: production
  otlpEndpoint: http://otel-collector.observability:4318/v1/traces
```

## Autoscaling

```yaml
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 75
  targetMemoryUtilizationPercentage: 80
  scaleDownStabilization: 300
  scaleUpStabilization: 30
```

**Warning**: when `database.backend=sqlite`, scaling replicas creates isolated
databases per pod (split-brain). Only enable HPA for SQLite with a replication
layer like LiteFS, or when your workload is read-only per shard.

## Network Policy

```yaml
networkPolicy:
  enabled: true
  ingressFrom:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
  databaseCIDR: "10.0.1.0/24"
  redisCIDR: "10.0.2.0/24"
```

When enabled, the policy allows:

- Ingress on the app port from sources matching `ingressFrom`
- Egress to DNS (port 53)
- Egress to `databaseCIDR` and `redisCIDR` if set
- Any additional rules from `extraEgress`

## Pod Disruption Budget

Enabled by default when `replicaCount >= 2`:

```yaml
podDisruptionBudget:
  enabled: true
  minAvailable: 1
```

## Scheduling

### Pod Anti-Affinity

Shorthand for spreading pods across nodes:

```yaml
podAntiAffinityType: soft  # or "hard"
```

This generates `preferredDuringSchedulingIgnoredDuringExecution` (soft) or
`requiredDuringSchedulingIgnoredDuringExecution` (hard) anti-affinity based on
`kubernetes.io/hostname`. For custom rules, use the `affinity` field directly
(takes precedence).

### Topology Spread

```yaml
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule
```

## Secret Management

The chart supports three patterns for secrets:

### 1. Chart-Managed Secret (Default)

Set values directly and the chart creates a Secret:

```yaml
secret:
  create: true
database:
  postgres:
    password: my-password
```

### 2. Existing Secret per Component

Reference pre-created Secrets:

```yaml
database:
  postgres:
    existingSecret: my-db-secret
    existingSecretPasswordKey: password
redis:
  existingSecret: my-redis-secret
  existingSecretPasswordKey: password
auth:
  existingSecret: my-auth-secret
```

### 3. Global Existing Secret

Mount a single Secret containing all sensitive env vars:

```yaml
secret:
  create: false
existingSecret: my-app-secret
```

## Extra Configuration

### Additional Environment Variables

```yaml
# Non-sensitive (ConfigMap)
extraEnv:
  MY_CUSTOM_VAR: some-value

# Sensitive (Secret)
extraSecretEnv:
  MY_API_KEY: secret-value

# From external sources
extraEnvFrom:
  - configMapRef:
      name: external-config
  - secretRef:
      name: external-secret
```

### Extra Volumes

```yaml
extraVolumes:
  - name: my-config
    configMap:
      name: my-app-config

extraVolumeMounts:
  - name: my-config
    mountPath: /etc/my-app
    readOnly: true
```

## Resource Management

### Explicit Resources (Production)

```yaml
resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    memory: 1Gi
```

### Resource Presets (Dev/Test)

```yaml
resourcePreset: small  # nano, micro, small, medium, large, xlarge, 2xlarge
```

Explicit `resources` always take precedence over `resourcePreset`.

## Image Configuration

### Registry and Tag

```yaml
image:
  registry: ghcr.io
  repository: your-org/fastapi-chassis
  tag: "1.2.3"
  pullPolicy: IfNotPresent
```

### Digest Pinning

```yaml
image:
  registry: ghcr.io
  repository: your-org/fastapi-chassis
  digest: sha256:abcdef1234567890...
```

Digest takes precedence over tag when both are set.

### Private Registries

```yaml
imagePullSecrets:
  - name: my-registry-secret
```

### Global Registry Override

For air-gapped environments:

```yaml
global:
  imageRegistry: registry.internal.example.com
```

## Production Checklist

Before deploying to production:

- [ ] Pin image tag or digest (never use `latest`)
- [ ] Set explicit `resources` (do not rely on presets)
- [ ] Configure `security.trustedHosts` to your domain(s)
- [ ] Use `existingSecret` for all passwords and keys
- [ ] Enable `migrations.enabled` (hook Job) instead of `database.runMigrations`
- [ ] Set `replicaCount >= 2` or enable `autoscaling`
- [ ] Enable `podDisruptionBudget`
- [ ] Configure `podAntiAffinityType` or explicit `affinity`
- [ ] Set `cors.allowedOrigins` to specific origins
- [ ] Use Redis-backed rate limiting for multi-replica deployments
- [ ] Enable `serviceMonitor` if using Prometheus Operator
- [ ] Disable `app.debug`, `app.docsEnabled`, `app.redocEnabled`,
  `app.openapiEnabled`
- [ ] Enable `networkPolicy` and restrict ingress/egress

## Upgrade Notes

When upgrading the chart:

```bash
helm upgrade my-app ./chart -f my-values.yaml
```

The pod template includes checksum annotations for both the ConfigMap and
Secret. Any change to configuration values triggers a rolling restart
automatically.

For SQLite backends, the StatefulSet uses `RollingUpdate` strategy. Pods are
updated one at a time in reverse ordinal order (highest first), which keeps
pod-0 (the LiteFS primary) running until all replicas are updated.

## CI Testing

The chart ships with CI test values in `chart/ci/`:

- `test-values-postgres.yaml`: Postgres backend with in-cluster Postgres
- `test-values-sqlite.yaml`: SQLite backend with minimal configuration

These are used by the Helm testing infrastructure and can serve as reference
configurations.

Helm tests are included in `chart/templates/tests/`:

- `test-health.yaml`: verifies `/healthcheck` returns 200
- `test-readiness.yaml`: verifies `/ready` returns 200
- `test-api.yaml`: verifies the root endpoint returns 200

Run tests after install:

```bash
helm test my-app
```
