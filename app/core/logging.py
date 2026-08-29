"""Structured JSON logging with secret sanitization.
Governing spec: BE-01, BE-13-R15.
"""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict


# Mask patterns for common secrets
SECRET_PATTERNS = [
    re.compile(r"(AIza[0-9A-Za-z-_]{35})"),                      # Google API key
    re.compile(r"(eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]+)"), # JWT
    re.compile(r"(postgresql://[^:]+:)([^@]+)(@)"),              # DB password
]


def sanitize_message(msg: str) -> str:
    """Scrub sensitive keys and tokens from log messages."""
    for pattern in SECRET_PATTERNS:
        msg = pattern.sub(r"[REDACTED]", msg)
    return msg


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_message(record.getMessage()),
        }

        # Include request_id if available
        if hasattr(record, "request_id"):
            log_obj["request_id"] = getattr(record, "request_id")

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


def setup_logging(log_level: str = "INFO") -> None:
    """Configure root logger with JSON formatting."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = [handler]


logger = logging.getLogger("verity")
