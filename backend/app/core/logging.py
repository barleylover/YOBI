from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

SESSION_PATTERN = re.compile(r"/(session_[a-f0-9]+)(?:/|$)")


def configure_logging(level: str) -> logging.Logger:
    logging.basicConfig(level=level.upper(), format="%(message)s")
    return logging.getLogger("yobi")


def safe_session_hash(path: str) -> str | None:
    match = SESSION_PATTERN.search(path)
    if not match:
        return None
    return hashlib.sha256(match.group(1).encode("utf-8")).hexdigest()


def log_event(logger: logging.Logger, **fields: Any) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    logger.info(json.dumps(record, ensure_ascii=True, separators=(",", ":")))

