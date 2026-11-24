from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def safe_json_loads(value: str | bytes | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    try:
        return json.loads(value)
    except Exception:
        return default
