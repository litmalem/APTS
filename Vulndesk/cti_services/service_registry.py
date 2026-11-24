from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .architecture import CTI_COMPONENTS
from .db_adapter import DbAdapter, to_json


class ServiceRegistry:
    """Runtime registry for harmonized CTI components.

    Historical builds used ``vulndesk_service_registry`` with only service names.
    The harmonized architecture needs an explicit Agent/Service/Data Artifact
    classification and a separate computational mechanism. This class therefore
    uses ``cti_component_registry`` while keeping the old public methods so the
    UI and existing integration code remain backward compatible.

    Important database-binding rule
    -------------------------------
    ``DEFAULT_SERVICES`` intentionally keeps ``config`` as a native Python dict
    because it is convenient for the in-memory component definition. PyMySQL,
    however, cannot bind a dict directly as a SQL parameter. Before an INSERT or
    UPDATE is executed, ``_registry_insert_params`` removes the native ``config``
    field and serializes it into the ``config_json`` column.
    """

    TABLE = "cti_component_registry"

    DEFAULT_SERVICES = [
        {
            **component.as_registry_row(),
            "service_side": "vulndesk",
            "status": "idle" if component.component_type != "Data Artifact" else "available",
            "config": (
                {"host": "127.0.0.1", "port": 8765}
                if component.service_key == "pentest_enrichment_api_service"
                else {"architecture_version": "2026-08-harmonized"}
            ),
        }
        for component in CTI_COMPONENTS
    ]

    def __init__(self, db: Optional[DbAdapter] = None):
        self.db = db or DbAdapter()

    @staticmethod
    def _registry_insert_params(service: Dict[str, Any]) -> Dict[str, Any]:
        """Build SQL-safe parameters for a component registry row.

        ``service`` may contain an in-memory ``config`` dictionary. That field is
        not a database column and must never be passed to PyMySQL. It is converted
        to a JSON string for ``config_json`` instead.

        Keeping this conversion here (rather than auto-serializing every dict in
        ``DbAdapter``) avoids changing the semantics of unrelated SQL statements
        that may legitimately use tuple/list parameters.
        """
        params = {
            key: value
            for key, value in service.items()
            if key != "config"
        }
        params["config_json"] = to_json(service.get("config") or {})
        return params

    def ensure_schema(self) -> None:
        self.db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.TABLE} (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                component_id VARCHAR(32) NOT NULL,
                service_key VARCHAR(120) NOT NULL,
                service_name VARCHAR(180) NOT NULL,
                component_type VARCHAR(40) NOT NULL,
                mechanism VARCHAR(220) NOT NULL,
                authority_boundary VARCHAR(255) NOT NULL,
                optional_component TINYINT(1) NOT NULL DEFAULT 0,
                service_side VARCHAR(30) NOT NULL DEFAULT 'vulndesk',
                enabled TINYINT(1) NOT NULL DEFAULT 1,
                status VARCHAR(30) NOT NULL DEFAULT 'idle',
                config_json LONGTEXT NULL,
                sort_order INT NOT NULL DEFAULT 0,
                last_run_at DATETIME NULL,
                last_error TEXT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE KEY uq_cti_component_id (component_id),
                UNIQUE KEY uq_cti_component_service_key (service_key),
                KEY idx_cti_component_type (component_type),
                KEY idx_cti_component_status (status),
                KEY idx_cti_component_enabled (enabled),
                KEY idx_cti_component_sort (sort_order)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )

    def ensure_default_services(self) -> None:
        """Create/update the canonical CTI component registry rows.

        The method is idempotent. Existing runtime values such as ``enabled``,
        ``status``, ``config_json``, ``last_run_at`` and ``last_error`` are not
        overwritten during the duplicate-key update. This preserves operator
        settings and runtime state while allowing architecture metadata to be
        harmonized safely.
        """
        self.ensure_schema()

        for service in self.DEFAULT_SERVICES:
            params = self._registry_insert_params(service)

            self.db.execute(
                f"""
                INSERT INTO {self.TABLE}
                    (component_id, service_key, service_name, component_type, mechanism,
                     authority_boundary, optional_component, service_side, enabled, status,
                     config_json, sort_order)
                VALUES
                    (%(component_id)s, %(service_key)s, %(service_name)s, %(component_type)s,
                     %(mechanism)s, %(authority_boundary)s, %(optional_component)s,
                     %(service_side)s, %(enabled)s, %(status)s, %(config_json)s, %(sort_order)s)
                ON DUPLICATE KEY UPDATE
                    component_id = VALUES(component_id),
                    service_name = VALUES(service_name),
                    component_type = VALUES(component_type),
                    mechanism = VALUES(mechanism),
                    authority_boundary = VALUES(authority_boundary),
                    optional_component = VALUES(optional_component),
                    service_side = VALUES(service_side),
                    sort_order = VALUES(sort_order),
                    updated_at = CURRENT_TIMESTAMP
                """,
                params,
            )

    def list_services(self) -> List[Dict[str, Any]]:
        self.ensure_default_services()
        return self.db.fetch_all(
            f"""
            SELECT id, component_id, service_key, service_name, component_type, mechanism,
                   authority_boundary, optional_component, service_side, enabled, status,
                   last_run_at, last_error, config_json, sort_order
            FROM {self.TABLE}
            ORDER BY sort_order, service_name
            """
        )

    def ensure_service(
        self,
        service_key: str,
        service_name: str,
        config: Optional[Dict[str, Any]] = None,
        component_id: str = "CTI-EXT",
        component_type: str = "Infrastructure Service",
        mechanism: str = "Deterministic adapter",
        authority_boundary: str = "No CTI reasoning authority",
    ) -> None:
        self.ensure_schema()
        self.db.execute(
            f"""
            INSERT INTO {self.TABLE}
                (component_id, service_key, service_name, component_type, mechanism,
                 authority_boundary, service_side, enabled, status, config_json, sort_order)
            VALUES
                (%(component_id)s, %(service_key)s, %(service_name)s, %(component_type)s,
                 %(mechanism)s, %(authority_boundary)s, 'vulndesk', 1, 'idle', %(config_json)s, 999)
            ON DUPLICATE KEY UPDATE
                service_name = VALUES(service_name), updated_at = CURRENT_TIMESTAMP
            """,
            {
                "component_id": component_id,
                "service_key": service_key,
                "service_name": service_name,
                "component_type": component_type,
                "mechanism": mechanism,
                "authority_boundary": authority_boundary,
                "config_json": to_json(config or {}),
            },
        )

    def set_enabled(self, service_key: str, enabled: bool) -> None:
        self.ensure_default_services()

        # Data artifacts are outputs rather than active workers. Keep them registered.
        row = self.db.fetch_one(
            f"SELECT component_type FROM {self.TABLE} WHERE service_key=%(service_key)s",
            {"service_key": service_key},
        )
        if row and row.get("component_type") == "Data Artifact":
            return

        self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET enabled = %(enabled)s, updated_at = CURRENT_TIMESTAMP
            WHERE service_key = %(service_key)s
            """,
            {"service_key": service_key, "enabled": 1 if enabled else 0},
        )

    def update_status(self, service_key: str, status: str, error: Optional[str] = None) -> None:
        self.ensure_default_services()
        self.db.execute(
            f"""
            UPDATE {self.TABLE}
            SET status = %(status)s,
                last_error = %(error)s,
                last_run_at = %(last_run_at)s,
                updated_at = CURRENT_TIMESTAMP
            WHERE service_key = %(service_key)s
            """,
            {
                "service_key": service_key,
                "status": status,
                "error": error,
                "last_run_at": datetime.now(),
            },
        )

    def is_enabled(self, service_key: str) -> bool:
        self.ensure_default_services()
        row = self.db.fetch_one(
            f"SELECT enabled FROM {self.TABLE} WHERE service_key = %(service_key)s",
            {"service_key": service_key},
        )
        return bool(row and int(row.get("enabled", 0)) == 1)

    def get_config(self, service_key: str) -> Dict[str, Any]:
        import json

        self.ensure_default_services()
        row = self.db.fetch_one(
            f"SELECT config_json FROM {self.TABLE} WHERE service_key = %(service_key)s",
            {"service_key": service_key},
        )
        if not row or row.get("config_json") is None:
            return {}

        value = row["config_json"]
        if isinstance(value, dict):
            return value

        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def get_component(self, service_key: str) -> Optional[Dict[str, Any]]:
        self.ensure_default_services()
        return self.db.fetch_one(
            f"SELECT * FROM {self.TABLE} WHERE service_key=%(service_key)s LIMIT 1",
            {"service_key": service_key},
        )
