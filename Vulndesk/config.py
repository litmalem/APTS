from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv


def _runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


_RUNTIME_BASE_DIR = _runtime_base_dir()
load_dotenv(_RUNTIME_BASE_DIR / ".env")


class Config:
    APP_TITLE = os.getenv("APP_TITLE", "VulnDesk - Vulnerability Viewer")
    DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

    NVD_API_URL = os.getenv("NVD_API_URL", "https://services.nvd.nist.gov/rest/json/cves/2.0")
    NVD_API_KEY = os.getenv("NVD_API_KEY", "").strip()
    # NVD CVE API 2.0 supports up to 2,000 results per page.
    NVD_PAGE_SIZE = max(1, min(int(os.getenv("NVD_PAGE_SIZE", "2000")), 2000))
    NVD_TIMEOUT_SECONDS = int(os.getenv("NVD_TIMEOUT_SECONDS", "90"))
    NVD_REQUEST_DELAY_SECONDS = float(os.getenv("NVD_REQUEST_DELAY_SECONDS", "0.6"))
    NVD_MAX_RETRIES = max(0, int(os.getenv("NVD_MAX_RETRIES", "5")))
    NVD_BACKOFF_BASE_SECONDS = float(os.getenv("NVD_BACKOFF_BASE_SECONDS", "2"))
    NVD_DB_BATCH_SIZE = max(1, min(int(os.getenv("NVD_DB_BATCH_SIZE", "100")), 2000))
    NVD_DB_PARENT_WRITE_BATCH_SIZE = max(1, int(os.getenv("NVD_DB_PARENT_WRITE_BATCH_SIZE", "100")))
    NVD_DB_CHILD_WRITE_BATCH_SIZE = max(1, int(os.getenv("NVD_DB_CHILD_WRITE_BATCH_SIZE", "500")))
    NVD_DB_MAX_STATEMENT_BYTES = max(64 * 1024, int(os.getenv("NVD_DB_MAX_STATEMENT_BYTES", str(512 * 1024))))
    NVD_DB_TRANSIENT_RETRIES = max(0, int(os.getenv("NVD_DB_TRANSIENT_RETRIES", "2")))
    NVD_DB_RETRY_BASE_SECONDS = max(0.1, float(os.getenv("NVD_DB_RETRY_BASE_SECONDS", "1")))

    # Exact NVD source JSON is gzip-compressed and split into small rows.
    # This avoids max_allowed_packet failures from unusually large CVEs while
    # preserving the Raw JSON tab. Values: compressed_chunks, plain, none.
    NVD_RAW_JSON_STORAGE = os.getenv("NVD_RAW_JSON_STORAGE", "compressed_chunks").strip().lower()
    NVD_RAW_JSON_CHUNK_BYTES = max(32 * 1024, min(int(os.getenv("NVD_RAW_JSON_CHUNK_BYTES", str(128 * 1024))), 512 * 1024))
    NVD_SKIP_UNCHANGED = os.getenv("NVD_SKIP_UNCHANGED", "true").lower() == "true"
    NVD_INCREMENTAL_WINDOW_DAYS = max(
        1,
        min(int(os.getenv("NVD_INCREMENTAL_WINDOW_DAYS", "120")), 120),
    )
    NVD_INCREMENTAL_INITIAL_START = os.getenv(
        "NVD_INCREMENTAL_INITIAL_START",
        "2024-01-01T00:00:00+00:00",
    )

    # NVD Official CPE Dictionary / Product API 2.0
    NVD_CPE_API_URL = os.getenv("NVD_CPE_API_URL", "https://services.nvd.nist.gov/rest/json/cpes/2.0")
    NVD_CPE_PAGE_SIZE = int(os.getenv("NVD_CPE_PAGE_SIZE", "100"))
    NVD_CPE_TIMEOUT_SECONDS = int(os.getenv("NVD_CPE_TIMEOUT_SECONDS", "90"))
    NVD_CPE_REQUEST_DELAY_SECONDS = float(os.getenv("NVD_CPE_REQUEST_DELAY_SECONDS", "0.6"))
    NVD_CPE_AUTO_FETCH_ON_MATCH = os.getenv("NVD_CPE_AUTO_FETCH_ON_MATCH", "true").lower() == "true"

    MITRE_ATTACK_API_ROOT = os.getenv("MITRE_ATTACK_API_ROOT", "https://attack-taxii.mitre.org/api/v21")
    MITRE_ENTERPRISE_COLLECTION_ID = os.getenv(
        "MITRE_ENTERPRISE_COLLECTION_ID",
        "x-mitre-collection--1f5f1533-f617-4ca8-9ab4-6a02367fa019",
    )
    MITRE_INCLUDE_REVOKED = os.getenv("MITRE_INCLUDE_REVOKED", "false").lower() == "true"
    MITRE_INCLUDE_DEPRECATED = os.getenv("MITRE_INCLUDE_DEPRECATED", "false").lower() == "true"
    MITRE_TIMEOUT_SECONDS = int(os.getenv("MITRE_TIMEOUT_SECONDS", "90"))

    CWE_API_ROOT = os.getenv("CWE_API_ROOT", "https://cwe-api.mitre.org/api/v1")
    CWE_TIMEOUT_SECONDS = int(os.getenv("CWE_TIMEOUT_SECONDS", "60"))
    CWE_DEFAULT_VIEW_ID = int(os.getenv("CWE_DEFAULT_VIEW_ID", "1000"))
    CWE_DEFAULT_RANGE_START = int(os.getenv("CWE_DEFAULT_RANGE_START", "1"))
    CWE_DEFAULT_RANGE_END = int(os.getenv("CWE_DEFAULT_RANGE_END", "1500"))

    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_NAME = os.getenv("DB_NAME", "vulndesk")
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_POOL_RECYCLE_SECONDS = max(30, int(os.getenv("DB_POOL_RECYCLE_SECONDS", "300")))
    DB_POOL_TIMEOUT_SECONDS = max(5, int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "30")))
    DB_CONNECT_TIMEOUT_SECONDS = max(5, int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "15")))
    DB_READ_TIMEOUT_SECONDS = max(30, int(os.getenv("DB_READ_TIMEOUT_SECONDS", "180")))
    DB_WRITE_TIMEOUT_SECONDS = max(30, int(os.getenv("DB_WRITE_TIMEOUT_SECONDS", "180")))

    # APTS Governance & Safety Plane integration. CTI source acquisition is
    # fail-closed: aptsGSS must return an explicit ALLOW before CTI-INF04 runs.
    GOVERNANCE_ENABLED = os.getenv("GOVERNANCE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    GOVERNANCE_BASE_URL = os.getenv("GOVERNANCE_BASE_URL", "http://127.0.0.1:8770").strip().rstrip("/")
    GOVERNANCE_TIMEOUT_SECONDS = max(0.5, float(os.getenv("GOVERNANCE_TIMEOUT_SECONDS", "5")))

    @classmethod
    def sqlalchemy_url(cls) -> str:
        if cls.DATABASE_URL:
            return cls.DATABASE_URL
        return (
            f"mysql+pymysql://{cls.DB_USER}:{cls.DB_PASSWORD}"
            f"@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}?charset=utf8mb4"
        )

    @classmethod
    def app_base_dir(cls) -> Path:
        return _RUNTIME_BASE_DIR

    @classmethod
    def data_dir(cls) -> Path:
        return cls.app_base_dir() / "data"

    @classmethod
    def upload_dir(cls) -> Path:
        env_dir = (os.getenv("DATASET_UPLOAD_DIR") or "").strip()
        if env_dir:
            custom = Path(env_dir)
            return custom if custom.is_absolute() else cls.app_base_dir() / custom
        return cls.data_dir() / "uploads"
