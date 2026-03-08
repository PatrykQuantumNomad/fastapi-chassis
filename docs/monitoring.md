# Monitoring

This document describes Prometheus metrics and alert rules for the FastAPI template.

## Metrics

When `APP_METRICS_ENABLED=true`, the application exposes Prometheus metrics at `/metrics`. The default metric prefix is `http` (configurable via `APP_METRICS_PREFIX`).

### Metric Names

The starlette-exporter middleware emits standard HTTP metrics. When `APP_METRICS_PREFIX=http` (default):

- `http_requests_total` — Counter of requests by method, path, status
- `http_request_duration_seconds` — Histogram of request duration
- `http_requests_in_progress` — Gauge of in-flight requests

### Adapting the Prefix

If you change `APP_METRICS_PREFIX` (e.g. to `fastapi_template`), update your Prometheus scrape config and alert rules accordingly. For example, with `APP_METRICS_PREFIX=fastapi`:

- `fastapi_requests_total`
- `fastapi_request_duration_seconds`
- `fastapi_requests_in_progress`

Replace `http_` with your prefix in the alert expressions below.

## Alert Rules

The file `ops/monitoring/prometheus-alerts.yml` defines alert rules. Configure Prometheus to load it:

```yaml
rule_files:
  - /path/to/ops/monitoring/prometheus-alerts.yml
```

### Alerts (default prefix `http`)

| Alert | Condition | Severity | Description |
| --- | --- | --- | --- |
| FastAPIHigh5xxRate | >5% of requests return 5xx for 10m | critical | High server error rate |
| FastAPIHighLatencyP95 | p95 latency >1s for 10m | warning | Elevated latency |
| FastAPIReadinessFailures | Readiness returns 503 for 5m | critical | App unhealthy |
| FastAPIRateLimitSpike | 429 responses >1/s for 10m | warning | Rate limit rejections increasing |

### Custom Prefix

When using a custom `APP_METRICS_PREFIX`, update the alert expressions in `prometheus-alerts.yml`. Replace `http_` with your prefix in:

- `http_requests_total` → `{prefix}_requests_total`
- `http_request_duration_seconds_bucket` → `{prefix}_request_duration_seconds_bucket`

Example for `APP_METRICS_PREFIX=myapp`:

```yaml
expr: |
  sum(rate(myapp_requests_total{status=~"5.."}[5m]))
  / clamp_min(sum(rate(myapp_requests_total[5m])), 0.001)
  > 0.05
```
