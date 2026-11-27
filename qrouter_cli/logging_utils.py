"""Opt-in structured stderr logging with a strict metadata allowlist."""

import json
import os
import sys
from datetime import datetime, timezone

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
_SAFE_FIELDS = {"component", "operation", "source", "status", "error_type", "error_code", "http_status", "duration_ms"}


def emit_log(event: str, level: str = "INFO", **fields) -> None:
    configured = os.environ.get("QROUTER_LOG_LEVEL", "OFF").upper()
    if configured not in _LEVELS or level not in _LEVELS or _LEVELS[level] < _LEVELS[configured]:
        return
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": level, "event": event[:80]}
    for key, value in fields.items():
        if key not in _SAFE_FIELDS or not isinstance(value, (str, int, float, bool, type(None))):
            continue
        if isinstance(value, str):
            value = value[:120]
        record[key] = value
    sys.stderr.write(json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n")
    sys.stderr.flush()
