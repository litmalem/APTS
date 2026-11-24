from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

try:
    import pymysql
    from pymysql.cursors import DictCursor
except Exception:  # Allows import before dependencies are installed.
    pymysql = None
    DictCursor = None


class DatabaseError(RuntimeError):
    pass


class JsonEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        return super().default(obj)


def make_json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(v) for v in value]
    return value


def to_json(value: Any) -> str:
    return json.dumps(make_json_safe(value), cls=JsonEncoder, ensure_ascii=False)


def normalize_sql_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return SQL-driver-safe named parameters.

    PyMySQL eagerly escapes every value in a parameter mapping, including keys
    that are not referenced by the SQL statement. A native Python ``dict`` is
    not a valid scalar SQL parameter and raises::

        TypeError: dict can not be used as parameter

    The harmonized CTI runtime frequently works with structured dictionaries,
    so a dict that reaches this boundary is serialized to JSON. Other values,
    including tuples/lists that may intentionally be used by PyMySQL for an
    ``IN (...)`` expression, are left unchanged.

    Domain services should still explicitly use ``to_json`` for JSON columns;
    this function is a defensive integration boundary, not a substitute for
    clear persistence contracts.
    """
    if not params:
        return {}

    def contains_mapping(value):
        if isinstance(value, dict):
            return True
        return isinstance(value, (list, tuple)) and any(contains_mapping(item) for item in value)

    normalized: Dict[str, Any] = {}
    for key, value in params.items():
        if contains_mapping(value):
            normalized[key] = to_json(value)
        else:
            normalized[key] = value
    return normalized


class DbAdapter:
    """Small PyMySQL adapter used by Pentest CTI services.

    This version is MariaDB-safe. It never uses CAST(... AS JSON), because
    MariaDB treats JSON as LONGTEXT with JSON_VALID semantics and does not
    support MySQL-style JSON casting in the same way.

    All named SQL parameters pass through ``normalize_sql_params`` so an
    accidental native dictionary cannot crash PyMySQL during parameter binding.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or self._load_config()
        self._column_cache: Dict[str, set[str]] = {}
        self._table_cache: Dict[str, bool] = {}

    @staticmethod
    def _load_config() -> Dict[str, Any]:
        path = os.getenv("PENTEST_DB_CONFIG_JSON")
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return DbAdapter._normalize_config(json.load(f))

        if os.path.exists("db_config.json"):
            with open("db_config.json", "r", encoding="utf-8") as f:
                return DbAdapter._normalize_config(json.load(f))

        return {
            "host": os.getenv("PENTEST_DB_HOST") or os.getenv("DB_HOST", "127.0.0.1"),
            "port": int(os.getenv("PENTEST_DB_PORT") or os.getenv("DB_PORT", "3306")),
            "user": os.getenv("PENTEST_DB_USER") or os.getenv("DB_USER", "root"),
            "password": (
                os.getenv("PENTEST_DB_PASSWORD")
                if os.getenv("PENTEST_DB_PASSWORD") is not None
                else os.getenv("DB_PASSWORD", "")
            ),
            "database": os.getenv("PENTEST_DB_NAME") or os.getenv("DB_NAME", "cti_pentest"),
            "charset": "utf8mb4",
        }

    @staticmethod
    def _normalize_config(data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "host": data.get("host", data.get("DB_HOST", "127.0.0.1")),
            "port": int(data.get("port", data.get("DB_PORT", 3306))),
            "user": data.get("user", data.get("username", data.get("DB_USER", "root"))),
            "password": data.get("password", data.get("DB_PASSWORD", "")),
            "database": data.get("database", data.get("db", data.get("DB_NAME", "cti_pentest"))),
            "charset": data.get("charset", "utf8mb4"),
        }

    @contextmanager
    def connect(self):
        if pymysql is None:
            raise DatabaseError("pymysql is not installed. Run: pip install pymysql")

        conn = pymysql.connect(cursorclass=DictCursor, autocommit=False, **self.config)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetch_all(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        safe_params = normalize_sql_params(params)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, safe_params)
                return [dict(r) for r in cur.fetchall()]

    def fetch_one(self, sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        safe_params = normalize_sql_params(params)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, safe_params)
                row = cur.fetchone()
                return dict(row) if row else None

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        safe_params = normalize_sql_params(params)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, safe_params)
                return int(cur.lastrowid or cur.rowcount or 0)

    def execute_many(self, sql: str, rows: Iterable[Dict[str, Any]]) -> int:
        safe_rows = [normalize_sql_params(row) for row in rows]
        if not safe_rows:
            return 0

        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, safe_rows)
                return int(cur.rowcount or 0)

    def table_exists(self, table_name: str) -> bool:
        if table_name in self._table_cache:
            return self._table_cache[table_name]

        row = self.fetch_one(
            """
            SELECT COUNT(*) AS n
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = %(table_name)s
            """,
            {"table_name": table_name},
        )
        exists = bool(row and int(row.get("n") or 0) > 0)
        self._table_cache[table_name] = exists
        return exists

    def columns(self, table_name: str) -> set[str]:
        if table_name in self._column_cache:
            return self._column_cache[table_name]

        rows = self.fetch_all(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE() AND table_name = %(table_name)s
            ORDER BY ordinal_position
            """,
            {"table_name": table_name},
        )
        cols = {r["column_name"] for r in rows}
        self._column_cache[table_name] = cols
        return cols

    def has_column(self, table_name: str, column_name: str) -> bool:
        return column_name in self.columns(table_name)

    def select_columns(self, table_name: str, wanted: Sequence[str]) -> str:
        cols = self.columns(table_name)
        present = [c for c in wanted if c in cols]
        return ", ".join(f"`{c}`" for c in present) if present else "*"

    def execute_transaction(self, statements: Sequence[tuple[str, Dict[str, Any]]]) -> List[int]:
        """Execute multiple statements in one database transaction.

        The harmonized CTI runtime uses this for version/state transitions that
        must not be partially committed (for example PIP publication metadata).
        """
        results: List[int] = []
        with self.connect() as conn:
            with conn.cursor() as cur:
                for sql, params in statements:
                    cur.execute(sql, normalize_sql_params(params))
                    results.append(int(cur.lastrowid or cur.rowcount or 0))
        return results

    def clear_schema_cache(self) -> None:
        self._column_cache.clear()
        self._table_cache.clear()
