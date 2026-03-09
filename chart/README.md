# fastapi-chassis

![Version: 1.0.0](https://img.shields.io/badge/Version-1.0.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 1.0.0](https://img.shields.io/badge/AppVersion-1.0.0-informational?style=flat-square)

Production-ready Helm chart for deploying FastAPI Chassis applications

**Homepage:** <https://github.com/PatrykQuantumNomad/fastapi-chassis>

## Maintainers

| Name | Email | Url |
| ---- | ------ | --- |
| PatrykQuantumNomad |  |  |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| affinity | object | `{}` | Pod affinity/anti-affinity rules (explicit, takes precedence over podAntiAffinityType) |
| app.debug | bool | `false` | Enable debug mode (never enable in production) |
| app.docsEnabled | bool | `false` | Expose Swagger UI (disable in production) |
| app.forwardedAllowIps | string | `"*"` | Trusted proxy IPs for X-Forwarded-* headers. Use "*" when behind a k8s ingress controller. |
| app.healthCheckPath | string | `"/healthcheck"` | Liveness probe path |
| app.logFormat | string | `"json"` | Log format: json (recommended for production) or text |
| app.logLevel | string | `"INFO"` | Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| app.name | string | `"FastAPI Chassis"` | Application display name |
| app.openapiEnabled | bool | `false` | Expose OpenAPI schema (disable in production) |
| app.port | int | `8000` | Container port |
| app.readinessCheckPath | string | `"/ready"` | Readiness probe path |
| app.readinessIncludeDetails | bool | `false` | Include dependency details in readiness response |
| app.redocEnabled | bool | `false` | Expose ReDoc UI (disable in production) |
| app.requestTimeout | int | `30` | Request timeout in seconds |
| app.version | string | `""` | Application version (defaults to Chart.appVersion) |
| app.workers | int | `1` | Number of uvicorn workers per pod |
| auth.clockSkew | int | `30` | Clock skew tolerance (seconds) |
| auth.enabled | bool | `false` | Enable JWT authentication |
| auth.existingSecret | string | `""` | Use an existing Secret for JWT credentials (Bitnami pattern #2). When set, jwtSecret/jwtPublicKey fields above are ignored. |
| auth.existingSecretJwtPublicKeyKey | string | `""` | Key within the existing Secret containing the JWT public key PEM |
| auth.existingSecretJwtSecretKey | string | `""` | Key within the existing Secret containing the JWT shared secret |
| auth.httpTimeout | int | `5` | HTTP timeout for JWKS fetch (seconds) |
| auth.jwksCacheTtl | int | `300` | JWKS cache TTL (seconds) |
| auth.jwksUrl | string | `""` | JWKS URL for key rotation (must be https://) |
| auth.jwtAlgorithms | string | `"[\"RS256\"]"` | Allowed JWT algorithms (JSON array string) |
| auth.jwtAudience | string | `""` | Expected JWT audience |
| auth.jwtIssuer | string | `""` | Expected JWT issuer |
| auth.jwtPublicKey | string | `""` | JWT public key PEM for RS*/ES*/PS* algorithms (stored in Secret) |
| auth.jwtSecret | string | `""` | JWT shared secret for HS* algorithms (stored in Secret) |
| auth.requireAudience | bool | `true` | Require audience claim |
| auth.requireExp | bool | `true` | Require exp claim |
| auth.requireIssuer | bool | `true` | Require issuer claim |
| autoscaling.enabled | bool | `false` | Enable HorizontalPodAutoscaler |
| autoscaling.maxReplicas | int | `10` | Maximum replicas |
| autoscaling.minReplicas | int | `2` | Minimum replicas |
| autoscaling.scaleDownStabilization | int | `300` | Scale-down stabilization window (seconds) |
| autoscaling.scaleUpStabilization | int | `30` | Scale-up stabilization window (seconds) |
| autoscaling.targetCPUUtilizationPercentage | int | `75` | Target CPU utilization (%) |
| autoscaling.targetMemoryUtilizationPercentage | int | `80` | Target memory utilization (%) |
| cache.backend | string | `"redis"` | Cache backend: redis (recommended) or memory |
| cache.defaultTtl | int | `300` | Default TTL (seconds) |
| cache.enabled | bool | `false` | Enable caching layer |
| cache.keyPrefix | string | `"cache:"` | Redis key prefix |
| cache.maxEntries | int | `10000` | Max in-memory entries |
| cache.redisDb | int | `1` | Redis DB index for cache |
| commonLabels | object | `{}` | Labels applied to all resources |
| cors.allowCredentials | bool | `false` | Allow credentials |
| cors.allowedOrigins | string | `"[]"` | Allowed origins (JSON array string) |
| database.alembicUrl | string | `""` | Custom Alembic URL (only used when backend=custom; stored in Secret) |
| database.backend | string | `"postgres"` | Database backend: postgres, sqlite, or custom. SQLite deploys as a StatefulSet with persistent local storage. Postgres/custom deploy as a stateless Deployment. |
| database.connectTimeout | int | `5` | Connection timeout (seconds) |
| database.existingSecret | string | `""` | Use an existing Secret for custom DB URLs (only when backend=custom). When set, url/alembicUrl fields above are ignored. |
| database.existingSecretAlembicUrlKey | string | `""` | Key within the existing Secret containing the Alembic URL |
| database.existingSecretUrlKey | string | `""` | Key within the existing Secret containing the database URL |
| database.healthTimeout | int | `2` | Health check timeout (seconds) |
| database.maxOverflow | int | `10` | Max overflow connections |
| database.poolPrePing | bool | `true` | Ping connections before use |
| database.poolSize | int | `5` | Connection pool size |
| database.postgres.existingSecret | string | `""` | Use an existing Secret for the Postgres password (Bitnami pattern #2). When set, the password field above is ignored and the chart's Secret skips this key. |
| database.postgres.existingSecretPasswordKey | string | `""` | Key within the existing Secret containing the password |
| database.postgres.host | string | `"postgres"` | Postgres host |
| database.postgres.name | string | `"fastapi_chassis"` | Database name |
| database.postgres.password | string | `""` | Database password (stored in Secret). For production, use existingSecret instead. |
| database.postgres.port | int | `5432` | Postgres port |
| database.postgres.user | string | `"fastapi"` | Database user |
| database.runMigrations | bool | `false` | Run Alembic migrations on container startup (prefer migrations.enabled instead) |
| database.sqlite.busyTimeout | int | `5000` | Milliseconds to wait when the database is locked before SQLITE_BUSY. |
| database.sqlite.cacheSize | int | `-64000` | Page cache size. Negative = KiB (-64000 = 64 MB). |
| database.sqlite.foreignKeys | bool | `true` | Enforce foreign key constraints (SQLite disables them by default). |
| database.sqlite.journalMode | string | `"wal"` | Journal mode. WAL enables concurrent readers + single writer. |
| database.sqlite.mmapSize | int | `0` | Memory-mapped I/O size in bytes. 0 disables. 268435456 = 256 MB. |
| database.sqlite.path | string | `"./data/app.db"` | SQLite file path (only used when backend=sqlite) |
| database.sqlite.synchronous | string | `"normal"` | Synchronous mode. NORMAL is safe with WAL; avoids full fsync per commit. |
| database.url | string | `""` | Custom database URL (only used when backend=custom; stored in Secret) |
| deploymentAnnotations | object | `{}` | Annotations on the Deployment/StatefulSet resource |
| existingSecret | string | `""` | Name of an existing Secret to mount (alternative to secret.create) |
| extraEnv | object | `{}` | Extra non-sensitive environment variables (added to ConfigMap) |
| extraEnvFrom | list | `[]` | Extra envFrom sources |
| extraSecretEnv | object | `{}` | Extra sensitive environment variables (added to Secret) |
| extraVolumeMounts | list | `[]` | Extra volume mounts for the container |
| extraVolumes | list | `[]` | Extra volumes to add to the pod |
| fullnameOverride | string | `""` | Override the full release name |
| global | object | `{}` |  |
| image.digest | string | `""` | Image digest (takes precedence over tag, e.g. sha256:abcdef...) |
| image.pullPolicy | string | `"IfNotPresent"` | Image pull policy |
| image.registry | string | `"ghcr.io"` | Container image registry (e.g. ghcr.io, docker.io, gcr.io) |
| image.repository | string | `"patrykquantumnomad/fastapi-chassis"` | Container image repository (without registry prefix) |
| image.tag | string | `""` | Image tag (defaults to Chart.appVersion) |
| imagePullSecrets | list | `[]` | Image pull secrets for private registries |
| ingress.annotations | object | `{}` | Ingress annotations |
| ingress.className | string | `""` | Ingress class name (e.g. nginx, traefik) |
| ingress.enabled | bool | `false` | Enable Ingress |
| ingress.hosts | list | `[]` | Ingress host rules |
| ingress.tls | list | `[]` | Ingress TLS configuration |
| kubeVersionOverride | string | `""` | Override the detected Kubernetes version (for CI/testing). Affects apiVersion selection for Ingress, HPA, PDB, etc. |
| litefs.enabled | bool | `false` | Enable LiteFS distributed replication |
| litefs.image.digest | string | `""` | LiteFS image digest (takes precedence over tag) |
| litefs.image.registry | string | `""` | LiteFS image registry (empty = Docker Hub) |
| litefs.image.repository | string | `"flyio/litefs"` | LiteFS container image |
| litefs.image.tag | string | `"0.5"` | LiteFS image tag |
| litefs.lease | object | `{"consul":{"hostname":"","key":"","ttl":""},"type":"static"}` | Lease configuration for primary election. |
| litefs.lease.consul | object | `{"hostname":"","key":"","ttl":""}` | Consul lease settings (only when type=consul) |
| litefs.lease.consul.hostname | string | `""` | Consul HTTP address (e.g. "consul.consul:8500") |
| litefs.lease.consul.key | string | `""` | Consul KV key for lease |
| litefs.lease.consul.ttl | string | `""` | Lease TTL (e.g. "10s") |
| litefs.lease.type | string | `"static"` | Lease type: "static" (pod-0 is always primary) or "consul" |
| litefs.proxy | object | `{"db":"db","passthrough":[],"port":8080}` | Built-in HTTP proxy. Routes write requests to the primary node, serves reads from the local replica. The proxy port becomes the container's exposed port (replacing the app port). |
| litefs.proxy.db | string | `"db"` | SQLite database name within the FUSE mount |
| litefs.proxy.passthrough | list | `[]` | URL patterns to pass through without write detection |
| litefs.proxy.port | int | `8080` | Proxy listen port (exposed via Service) |
| litestream.enabled | bool | `false` | Enable Litestream sidecar for SQLite backup/restore |
| litestream.env | list | `[]` | Extra environment variables for the Litestream containers |
| litestream.existingSecret | string | `""` | Name of an existing Secret containing Litestream credentials (e.g. LITESTREAM_ACCESS_KEY_ID, LITESTREAM_SECRET_ACCESS_KEY). |
| litestream.image.digest | string | `""` | Litestream image digest (takes precedence over tag) |
| litestream.image.registry | string | `""` | Litestream image registry (empty = Docker Hub) |
| litestream.image.repository | string | `"litestream/litestream"` | Litestream container image |
| litestream.image.tag | string | `"0.3"` | Litestream image tag |
| litestream.replica | object | `{"bucket":"","endpoint":"","path":"","region":"","retentionDuration":"","syncInterval":"","type":"s3","url":""}` | Replica destination configuration. See https://litestream.io/reference/config/ for full options. |
| litestream.replica.bucket | string | `""` | S3/GCS bucket name |
| litestream.replica.endpoint | string | `""` | S3-compatible endpoint URL (for MinIO, R2, Backblaze, etc.) |
| litestream.replica.path | string | `""` | Path prefix within the bucket |
| litestream.replica.region | string | `""` | AWS region (S3 only) |
| litestream.replica.retentionDuration | string | `""` | Snapshot retention duration (e.g. "720h" for 30 days) |
| litestream.replica.syncInterval | string | `""` | WAL sync interval (e.g. "1s" for near-realtime) |
| litestream.replica.type | string | `"s3"` | Replica type: s3, gcs, abs, or sftp |
| litestream.replica.url | string | `""` | Full replica URL (alternative to individual fields). Used by the restore init container. Example: s3://my-bucket/backups/app.db |
| litestream.resources | object | `{"limits":{"memory":"128Mi"},"requests":{"cpu":"50m","memory":"64Mi"}}` | Resource requests/limits for the Litestream sidecar |
| metrics.enabled | bool | `true` | Enable Prometheus metrics endpoint (/metrics) |
| metrics.prefix | string | `"http"` | Metric name prefix |
| migrations.activeDeadlineSeconds | int | `120` | Job timeout (seconds) |
| migrations.backoffLimit | int | `3` | Maximum retries |
| migrations.enabled | bool | `false` | Run migrations as a pre-install/pre-upgrade Helm hook Job |
| nameOverride | string | `""` | Override the chart name |
| namespaceOverride | string | `""` | Override the release namespace |
| networkPolicy.databaseCIDR | string | `""` | Database CIDR for egress (leave empty to allow any destination) |
| networkPolicy.enabled | bool | `false` | Enable NetworkPolicy. PRODUCTION: Set to true and configure ingressFrom to restrict traffic to your ingress controller namespace. Without ingressFrom rules, enabling this blocks all inbound traffic to the service. |
| networkPolicy.extraEgress | list | `[]` | Extra egress rules |
| networkPolicy.ingressFrom | list | `[]` | Ingress source rules (e.g. allow from ingress controller namespace) |
| networkPolicy.redisCIDR | string | `""` | Redis CIDR for egress |
| nodeSelector | object | `{}` | Node selector |
| persistence.accessMode | string | `"ReadWriteOnce"` | Access mode. Must be ReadWriteOnce — never use RWX with SQLite. |
| persistence.size | string | `"10Gi"` | Volume size |
| persistence.storageClass | string | `""` | Storage class for the SQLite data volume. Use high-performance block storage (e.g. gp3, pd-ssd, local-path). Leave empty for cluster default. |
| podAnnotations | object | `{}` | Annotations on all pods |
| podAntiAffinityType | string | `""` | Simplified pod anti-affinity (Bitnami pattern #10). Set to "soft" (preferred) or "hard" (required) for automatic pod anti-affinity based on hostname. Ignored when affinity is set explicitly. |
| podDisruptionBudget.enabled | bool | `true` | Enable PDB (recommended when replicaCount >= 2) |
| podDisruptionBudget.maxUnavailable | string | `""` | Maximum unavailable pods |
| podDisruptionBudget.minAvailable | int | `1` | Minimum available pods (takes precedence over maxUnavailable) |
| podLabels | object | `{}` | Extra labels on all pods |
| probes.liveness.failureThreshold | int | `3` |  |
| probes.liveness.initialDelaySeconds | int | `15` |  |
| probes.liveness.periodSeconds | int | `30` |  |
| probes.liveness.timeoutSeconds | int | `5` |  |
| probes.readiness.failureThreshold | int | `3` |  |
| probes.readiness.initialDelaySeconds | int | `5` |  |
| probes.readiness.periodSeconds | int | `10` |  |
| probes.readiness.timeoutSeconds | int | `5` |  |
| probes.startup.failureThreshold | int | `12` |  |
| probes.startup.initialDelaySeconds | int | `5` | Startup probe gives the app up to 60s (5s * 12) to start |
| probes.startup.periodSeconds | int | `5` |  |
| probes.startup.timeoutSeconds | int | `3` |  |
| rateLimit.enabled | bool | `false` | Enable rate limiting |
| rateLimit.keyStrategy | string | `"ip"` | Key strategy: ip or authorization |
| rateLimit.requests | int | `100` | Max requests per window |
| rateLimit.storageBackend | string | `"redis"` | Storage backend: redis (recommended) or memory |
| rateLimit.trustProxyHeaders | bool | `true` | Trust proxy headers for client IP (set true behind ingress) |
| rateLimit.windowSeconds | int | `60` | Window duration (seconds) |
| redis.db | int | `0` | Redis DB index |
| redis.existingSecret | string | `""` | Use an existing Secret for the Redis password (Bitnami pattern #2). |
| redis.existingSecretPasswordKey | string | `""` | Key within the existing Secret containing the Redis password |
| redis.host | string | `"redis"` | Redis host |
| redis.password | string | `""` | Redis password (stored in Secret) |
| redis.port | int | `6379` | Redis port |
| replicaCount | int | `2` | Number of replicas (ignored when autoscaling is enabled). For SQLite backend, each replica has its own isolated database. Use replicaCount=1 unless you have a replication layer (e.g. LiteFS). |
| resourcePreset | string | `""` | Resource preset for dev/test (alternative to explicit resources). Valid values: nano, micro, small, medium, large, xlarge, 2xlarge. NOTE: Presets are for dev/test only. Set explicit resources for production. Explicit resources above take precedence over presets. |
| resources.limits.cpu | string | `"500m"` |  |
| resources.limits.memory | string | `"512Mi"` |  |
| resources.requests.cpu | string | `"100m"` |  |
| resources.requests.memory | string | `"256Mi"` |  |
| revisionHistoryLimit | int | `3` | Revision history limit for rollbacks |
| secret.create | bool | `true` | Create a Secret resource for sensitive env vars |
| security.headersEnabled | bool | `true` | Enable security response headers |
| security.hstsEnabled | bool | `true` | Enable HSTS |
| security.hstsMaxAge | int | `31536000` | HSTS max-age (seconds) |
| security.maxRequestBodyBytes | int | `5242880` | Max request body size (bytes) |
| security.trustedHosts | string | `""` | Trusted hosts (JSON array string). Set to your domain(s). |
| service.annotations | object | `{}` | Service annotations |
| service.port | int | `80` | Service port |
| service.type | string | `"ClusterIP"` | Service type |
| serviceAccount.annotations | object | `{}` | ServiceAccount annotations (e.g. for IAM roles / IRSA for Litestream S3 access) |
| serviceAccount.automount | bool | `false` | Automount API credentials |
| serviceAccount.create | bool | `true` | Create a ServiceAccount |
| serviceAccount.name | string | `""` | ServiceAccount name (defaults to fullname) |
| serviceMonitor.enabled | bool | `false` | Create a ServiceMonitor for Prometheus Operator |
| serviceMonitor.interval | string | `"30s"` | Scrape interval |
| serviceMonitor.labels | object | `{}` | Extra labels for ServiceMonitor discovery |
| serviceMonitor.metricRelabelings | list | `[]` | Metric relabeling configs |
| serviceMonitor.namespace | string | `""` | Namespace for the ServiceMonitor (defaults to release namespace) |
| serviceMonitor.relabelings | list | `[]` | Relabeling configs |
| serviceMonitor.scrapeTimeout | string | `"10s"` | Scrape timeout |
| sqlite.podManagementPolicy | string | `"OrderedReady"` | Pod management policy for the StatefulSet. "OrderedReady" (default) or "Parallel" for faster rollouts. |
| strategy | object | `{"maxSurge":1,"maxUnavailable":0}` | Rolling update strategy (Deployment only; StatefulSet uses RollingUpdate by default) |
| terminationGracePeriodSeconds | int | `45` | Termination grace period (seconds). Ensure this exceeds app.requestTimeout so in-flight requests can complete during shutdown. |
| tolerations | list | `[]` | Tolerations |
| topologySpreadConstraints | list | `[]` | Topology spread constraints for zone-aware scheduling |
| tracing.enabled | bool | `false` | Enable OpenTelemetry tracing |
| tracing.environment | string | `"production"` | Deployment environment label |
| tracing.otlpEndpoint | string | `"http://otel-collector.observability:4318/v1/traces"` | OTLP HTTP endpoint |
| tracing.otlpHeaders | string | `""` | OTLP headers (comma-separated key=value) |
| tracing.serviceName | string | `""` | Service name for traces |
| tracing.serviceVersion | string | `""` | Service version for traces |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
