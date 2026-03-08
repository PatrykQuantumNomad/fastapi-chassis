"""
Root logging bootstrap.

Configures the Python root logger *before* the app builder runs, so that
early startup messages (settings validation, import errors, etc.) already
use the correct format.

The app builder's `setup_logging()` step later applies the full
dictConfig (with per-logger levels, filters, etc.) on top of this.

Author: Patryk Golabek
Copyright: 2026 Patryk Golabek
"""

import logging
import sys

from .log_config.filters import RequestContextFilter
from .settings import Settings


def configure_root_logging(settings: Settings) -> None:
    """
    Bootstrap the root logger with the format specified in settings.

    Args:
        settings: Application settings (uses log_level and log_format).
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()

    # Avoid stacking handlers when create_app() is called multiple times
    # (common in tests). Clear existing handlers first.
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.addFilter(RequestContextFilter())

    if settings.log_format == "json":
        from pythonjsonlogger.json import JsonFormatter

        handler.setFormatter(
            JsonFormatter(
                fmt=(
                    "%(asctime)s %(levelname)s %(name)s"
                    " %(request_id)s %(correlation_id)s %(message)s"
                ),
                datefmt="%Y-%m-%dT%H:%M:%S",
                rename_fields={
                    "asctime": "timestamp",
                    "levelname": "level",
                    "name": "logger",
                },
            )
        )
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt=settings.log_text_template,
                datefmt=settings.log_date_format,
            )
        )

    root.addHandler(handler)
