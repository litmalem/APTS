from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .db_adapter import make_json_safe, to_json


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat().replace("+00:00", "Z")


def to_db_datetime(value: Any) -> Optional[datetime]:
    """Normalize a timestamp for MariaDB ``DATETIME`` columns.

    Domain/runtime objects keep UTC timestamps as ISO-8601 strings (including
    the ``Z`` suffix) because that form is unambiguous in events and JSON.
    MariaDB ``DATETIME``, however, is timezone-naive and PyMySQL should receive
    a Python ``datetime`` rather than an RFC-3339/ISO string such as
    ``2026-08-14T01:49:34.385403Z``.

    This helper accepts native datetimes and common ISO/SQL timestamp strings,
    converts timezone-aware values to UTC, and strips timezone information only
    at the persistence boundary. ``None``/blank values remain ``None``.
    """
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith(("Z", "z")):
            text = f"{text[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"Unsupported datetime value: {value!r}") from exc

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def canonical_json(value: Any) -> str:
    return json.dumps(make_json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_object(value: Any) -> str:
    return sha256_text(canonical_json(value))


def clamp(value: Any, low: float = 0.0, high: float = 1.0, default: float = 0.0) -> float:
    try:
        v = float(value)
    except Exception:
        v = default
    return max(low, min(high, v))


def listify(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def safe_json_loads(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def evidence_ref(prefix: str, *parts: Any) -> str:
    raw = ":".join(str(p) for p in parts if p not in (None, ""))
    return f"{prefix}:{sha256_text(raw)[:20]}"


def normalize_identifier(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def severity_to_score(value: Any, cvss: Any = None) -> float:
    try:
        if cvss is not None:
            return clamp(float(cvss) / 10.0)
    except Exception:
        pass
    sev = str(value or "").strip().upper()
    return {"CRITICAL": 0.95, "HIGH": 0.80, "MEDIUM": 0.55, "LOW": 0.30, "NONE": 0.05}.get(sev, 0.50)


def db_insert_if_table(db: Any, table: str, sql: str, params: Dict[str, Any]) -> int:
    try:
        if db.table_exists(table):
            return db.execute(sql, params)
    except Exception:
        return 0
    return 0


def db_execute_if_table(db: Any, table: str, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
    try:
        if db.table_exists(table):
            return db.execute(sql, params or {})
    except Exception:
        return 0
    return 0


def db_fetch_all_if_table(db: Any, table: str, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    try:
        if db.table_exists(table):
            return db.fetch_all(sql, params or {})
    except Exception:
        return []
    return []


def db_fetch_one_if_table(db: Any, table: str, sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    try:
        if db.table_exists(table):
            return db.fetch_one(sql, params or {})
    except Exception:
        return None
    return None


def json_param(value: Any) -> str:
    return to_json(value)
