"""
Custom logging filters for reducing noise in production logs.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import logging

from .request_context import get_correlation_id, get_request_id


class SuppressEndpointFilter(logging.Filter):
    """
    Logging filter that suppresses access log entries for specified endpoints.

    In production, endpoints like /metrics (scraped by Prometheus every ~15s)
    and /healthcheck (polled by Kubernetes) generate enormous log volumes
    with no diagnostic value. This filter silences them.

    Usage:
        uvicorn_access = logging.getLogger("uvicorn.access")
        uvicorn_access.addFilter(SuppressEndpointFilter(["/metrics", "/healthcheck"]))
    """

    def __init__(self, endpoints: list[str]) -> None:
        """
        Initialize the filter with endpoints to suppress.

        Args:
            endpoints: List of URL paths to suppress from access logs.
                       Example: ["/metrics", "/healthcheck"]
        """
        super().__init__()
        self.endpoints = endpoints

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Determine if the log record should be emitted.

        Args:
            record: The log record to evaluate.

        Returns:
            True if the record should be logged, False to suppress it.
        """
        message = record.getMessage()
        return not any(endpoint in message for endpoint in self.endpoints)


class RequestContextFilter(logging.Filter):
    """
    Inject request-scoped context fields into every log record.

    Ensures formatters can safely reference ``%(request_id)s`` and
    ``%(correlation_id)s`` for both in-request logs and startup/background logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach tracing IDs to the record and always allow emission."""
        # Preserve explicitly-provided IDs (e.g., access-style middleware logs).
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        if not hasattr(record, "correlation_id"):
            record.correlation_id = get_correlation_id()
        return True
