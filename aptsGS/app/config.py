from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("GOV_HOST", "127.0.0.1")
    port: int = int(os.getenv("GOV_PORT", "8770"))
    log_level: str = os.getenv("GOV_LOG_LEVEL", "INFO")
    decision_ttl_seconds: int = int(os.getenv("GOV_DECISION_TTL_SECONDS", "300"))
    approval_ttl_seconds: int = int(os.getenv("GOV_APPROVAL_TTL_SECONDS", "900"))
    # AL-025: default validity window of an autonomy-level authorization grant.
    # Level re-authorization is annual by default (365 days); incident downgrade
    # lowers the ceiling before expiry. See app/authorization_level.py.
    level_grant_ttl_seconds: int = int(os.getenv("GOV_LEVEL_GRANT_TTL_SECONDS", str(365 * 24 * 3600)))
    approval_principals_file: str = os.getenv("GOV_APPROVAL_PRINCIPALS_FILE", "")
    outbox_poll_seconds: float = float(os.getenv("GOV_OUTBOX_POLL_SECONDS", "2.0"))
    debug: bool = _as_bool(os.getenv("GOV_DEBUG"), False)
    # Optional organization-level preapproval profile. When enabled, GSS adds
    # only the non-actuating Recon task-delegation rule to newly issued or
    # revised scopes that already explicitly ALLOW TARGET_RECON.
    auto_recon_task_delegation: bool = _as_bool(
        os.getenv("GSS_AUTO_RECON_TASK_DELEGATION"), False
    )

    db_driver: str = os.getenv("GOV_DB_DRIVER", "mysql").strip().lower()
    sqlite_path: str = os.getenv("GOV_SQLITE_PATH", str(Path(__file__).resolve().parents[1] / "data" / "governance.sqlite3"))
    db_host: str = os.getenv("GOV_DB_HOST", "127.0.0.1")
    db_port: int = int(os.getenv("GOV_DB_PORT", "3306"))
    db_name: str = os.getenv("GOV_DB_NAME", "apts_governance")
    db_user: str = os.getenv("GOV_DB_USER", "root")
    db_password: str = os.getenv("GOV_DB_PASSWORD", "")

    cti_event_api_url: str = os.getenv(
        "CTI_EVENT_API_URL",
        "http://127.0.0.1:8765/api/cti/events/publish",
    )
    cti_event_api_timeout_seconds: float = float(
        os.getenv("CTI_EVENT_API_TIMEOUT_SECONDS", "5")
    )

    @property
    def db_config(self) -> dict:
        if self.db_driver == "sqlite":
            return {"driver": "sqlite", "path": self.sqlite_path}
        return {
            "host": self.db_host,
            "port": self.db_port,
            "user": self.db_user,
            "password": self.db_password,
            "database": self.db_name,
            "charset": "utf8mb4",
        }


settings = Settings()
