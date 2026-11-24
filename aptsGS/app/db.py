from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, Optional, Sequence

import pymysql
from pymysql.cursors import DictCursor

from .config import settings


class DatabaseError(RuntimeError):
    pass


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(type(obj).__name__)


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def normalize_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not params:
        return {}
    out: Dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, dict):
            out[key] = to_json(value)
        else:
            out[key] = value
    return out


class Db:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = dict(config if config is not None else settings.db_config)
        self.driver = self.config.pop("driver", "mysql")
        if self.driver not in {"mysql", "sqlite"}:
            raise DatabaseError("Unsupported governance database driver")
        self._transaction_connection = ContextVar(f"gov_db_connection_{id(self)}", default=None)

    @contextmanager
    def connect(self):
        existing = self._transaction_connection.get()
        if existing is not None:
            yield existing
            return
        if self.driver == "sqlite":
            path = Path(self.config["path"]).expanduser().resolve()
            # Missing databases fail closed; migration/bootstrap owns creation.
            raw = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=30,
                detect_types=sqlite3.PARSE_DECLTYPES, isolation_level=None)
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA foreign_keys=ON")
            raw.execute("PRAGMA busy_timeout=30000")
            raw.execute("PRAGMA synchronous=FULL")
            raw.execute("BEGIN IMMEDIATE")
            conn = SQLiteConnection(raw)
        else:
            conn = pymysql.connect(
                cursorclass=DictCursor, autocommit=False,
                connect_timeout=10, read_timeout=30, write_timeout=30, **self.config)

        token = self._transaction_connection.set(conn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._transaction_connection.reset(token)
            conn.close()

    def ping(self) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
                return bool(row and row.get("ok") == 1)

    def fetch_one(self, sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[dict]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, normalize_params(params))
                row = cur.fetchone()
                return dict(row) if row else None

    def fetch_all(self, sql: str, params: Optional[Dict[str, Any]] = None) -> list[dict]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, normalize_params(params))
                return [dict(row) for row in cur.fetchall()]

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, normalize_params(params))
                return int(cur.lastrowid or cur.rowcount or 0)

    def execute_many(self, sql: str, rows: Iterable[Dict[str, Any]]) -> int:
        safe_rows = [normalize_params(row) for row in rows]
        if not safe_rows:
            return 0
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, safe_rows)
                return int(cur.rowcount or 0)

    def execute_transaction(self, statements: Sequence[tuple[str, Dict[str, Any]]]) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                for sql, params in statements:
                    cur.execute(sql, normalize_params(params))


# Preserve MySQL row types so policy/date/hash serialization remains stable.
sqlite3.register_converter("DATETIME", lambda value: datetime.fromisoformat(value.decode("utf-8")))
sqlite3.register_converter("DECIMAL_TEXT", lambda value: Decimal(value.decode("ascii")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def sqlite_sql(sql):
    """Translate the fixed repository dialect, never interpolate parameter values."""
    sql = re.sub(r"%\(([A-Za-z_][A-Za-z0-9_]*)\)s", r":\1", sql)
    sql = re.sub(r"\bFOR\s+UPDATE\b", "", sql, flags=re.I)
    sql = re.sub(r"UTC_TIMESTAMP\(\)", "CURRENT_TIMESTAMP", sql, flags=re.I)
    sql = re.sub(r"DATE_ADD\(CURRENT_TIMESTAMP,\s*INTERVAL 24 HOUR\)",
                 "datetime(CURRENT_TIMESTAMP, '+24 hours')", sql, flags=re.I)
    # MySQL UPDATE evaluates assignments left-to-right; SQLite uses old RHS values.
    sql = re.sub(r"DATE_ADD\(CURRENT_TIMESTAMP,\s*INTERVAL LEAST\(60,\s*POW\(2,\s*LEAST\(attempt_count,\s*5\)\)\) SECOND\)",
                 "datetime(CURRENT_TIMESTAMP, '+' || MIN(60, (1 << MIN(attempt_count + 1, 5))) || ' seconds')", sql, flags=re.I)
    if re.search(r"\b(?:FOR UPDATE|DATE_ADD|UTC_TIMESTAMP|INTERVAL|ON DUPLICATE)\b", sql, re.I):
        raise DatabaseError("Unsupported SQL in governance SQLite backend")
    return sql


def sqlite_params(params):
    values = normalize_params(params)
    return {key: str(value) if isinstance(value, Decimal) else (value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value).isoformat(sep=" ") if isinstance(value, datetime)
            else value.isoformat() if isinstance(value, date) else value for key,value in values.items()}


class SQLiteCursor:
    def __init__(self, raw):
        self.raw = raw.cursor()
        self.is_insert = False
    def __enter__(self): return self
    def __exit__(self, *args): self.raw.close()
    def execute(self, sql, params=None):
        self.is_insert = sql.lstrip().upper().startswith("INSERT")
        self.raw.execute(sqlite_sql(sql), sqlite_params(params))
        return self.raw.rowcount
    def executemany(self, sql, rows):
        self.is_insert = sql.lstrip().upper().startswith("INSERT")
        self.raw.executemany(sqlite_sql(sql), [sqlite_params(row) for row in rows])
        return self.raw.rowcount
    @property
    def rowcount(self): return self.raw.rowcount
    @property
    def lastrowid(self): return self.raw.lastrowid if self.is_insert else 0
    def fetchone(self):
        row = self.raw.fetchone()
        return dict(row) if row is not None else None
    def fetchall(self): return [dict(row) for row in self.raw.fetchall()]


class SQLiteConnection:
    def __init__(self, raw): self.raw = raw
    def cursor(self): return SQLiteCursor(self.raw)
    def commit(self): self.raw.commit()
    def rollback(self): self.raw.rollback()
    def close(self): self.raw.close()
