from __future__ import annotations

from contextlib import contextmanager
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import Config


class Base(DeclarativeBase):
    pass


_database_url = Config.sqlalchemy_url()
_engine_kwargs = {
    "pool_pre_ping": True,
    "echo": False,
    "future": True,
}
if _database_url.startswith("mysql+"):
    _engine_kwargs["pool_recycle"] = Config.DB_POOL_RECYCLE_SECONDS
    _engine_kwargs["pool_timeout"] = Config.DB_POOL_TIMEOUT_SECONDS
    _engine_kwargs["connect_args"] = {
        "connect_timeout": Config.DB_CONNECT_TIMEOUT_SECONDS,
        "read_timeout": Config.DB_READ_TIMEOUT_SECONDS,
        "write_timeout": Config.DB_WRITE_TIMEOUT_SECONDS,
    }

engine = create_engine(_database_url, **_engine_kwargs)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
    except Exception:
        try:
            session.rollback()
        finally:
            session.close()
        raise
    else:
        session.close()


def _ensure_dataset_upload_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("dataset_uploads"):
        return

    columns = {col["name"] for col in inspector.get_columns("dataset_uploads")}
    statements: list[str] = []
    if "stored_file_path" not in columns:
        statements.append("ALTER TABLE dataset_uploads ADD COLUMN stored_file_path VARCHAR(500) NULL AFTER file_name")
    if "file_size_bytes" not in columns:
        statements.append("ALTER TABLE dataset_uploads ADD COLUMN file_size_bytes BIGINT NULL AFTER stored_file_path")

    if not statements:
        return

    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))


def _ensure_cwe_catalog_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("cwe_catalog"):
        return

    columns = {col["name"] for col in inspector.get_columns("cwe_catalog")}
    statements: list[str] = []

    # MariaDB/MySQL ALTER TABLE ADD COLUMN IF NOT EXISTS is not available in all
    # deployments used by this desktop app, so we inspect first and then add.
    column_specs = [
        ("description_text", "ALTER TABLE cwe_catalog ADD COLUMN description_text MEDIUMTEXT NULL AFTER cwe_url"),
        ("extended_description", "ALTER TABLE cwe_catalog ADD COLUMN extended_description MEDIUMTEXT NULL AFTER description_text"),
        ("abstraction", "ALTER TABLE cwe_catalog ADD COLUMN abstraction VARCHAR(80) NULL AFTER extended_description"),
        ("structure_value", "ALTER TABLE cwe_catalog ADD COLUMN structure_value VARCHAR(80) NULL AFTER abstraction"),
        ("status_value", "ALTER TABLE cwe_catalog ADD COLUMN status_value VARCHAR(80) NULL AFTER structure_value"),
        ("likelihood_of_exploit", "ALTER TABLE cwe_catalog ADD COLUMN likelihood_of_exploit VARCHAR(80) NULL AFTER status_value"),
        ("source_name", "ALTER TABLE cwe_catalog ADD COLUMN source_name VARCHAR(100) NULL DEFAULT 'MITRE CWE' AFTER likelihood_of_exploit"),
        ("api_version", "ALTER TABLE cwe_catalog ADD COLUMN api_version VARCHAR(50) NULL AFTER source_name"),
        ("api_synced_at", "ALTER TABLE cwe_catalog ADD COLUMN api_synced_at DATETIME NULL AFTER api_version"),
        ("related_weaknesses_json", "ALTER TABLE cwe_catalog ADD COLUMN related_weaknesses_json LONGTEXT NULL AFTER api_synced_at"),
        ("alternate_terms_json", "ALTER TABLE cwe_catalog ADD COLUMN alternate_terms_json LONGTEXT NULL AFTER related_weaknesses_json"),
        ("raw_json", "ALTER TABLE cwe_catalog ADD COLUMN raw_json LONGTEXT NULL AFTER alternate_terms_json"),
    ]

    for column_name, sql in column_specs:
        if column_name not in columns:
            statements.append(sql)

    if not statements:
        return

    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))



def _ensure_vulnerability_longtext_columns() -> None:
    if engine.dialect.name not in {"mysql", "mariadb"}:
        return
    inspector = inspect(engine)
    if not inspector.has_table("vulnerabilities"):
        return
    columns = {column["name"]: column for column in inspector.get_columns("vulnerabilities")}
    statements: list[str] = []
    for name in ("description_text", "raw_json"):
        column = columns.get(name)
        if column is None:
            continue
        type_name = str(column.get("type", "")).upper()
        if "LONGTEXT" not in type_name:
            statements.append(
                f"ALTER TABLE vulnerabilities MODIFY COLUMN `{name}` LONGTEXT NULL"
            )
    if statements:
        with engine.begin() as conn:
            for sql in statements:
                conn.execute(text(sql))

def _drop_redundant_nvd_indexes() -> None:
    """Remove exact duplicate indexes found in older VulnDesk schemas.

    The migration is conservative: an index is dropped only when the named
    replacement index is also present. It therefore does not remove the sole
    index on a column in installations with a different schema history.
    """
    if engine.dialect.name not in {"mysql", "mariadb"}:
        return

    redundant_pairs = [
        ("vulnerabilities", "uq_vuln_cve_id", "uq_vulnerabilities_cve_id"),
        ("vulnerabilities", "idx_vuln_modified_at", "idx_vulnerabilities_modified_at"),
        ("vulnerabilities", "idx_vuln_pref_severity", "idx_vulnerabilities_preferred_severity"),
        ("vulnerabilities", "idx_vuln_pref_score", "idx_vulnerabilities_preferred_score"),
        ("cpe_matches", "idx_cpe_vulnerability_id", "idx_cpe_matches_vulnerability_id"),
        ("reference_links", "idx_ref_vulnerability_id", "idx_reference_links_vulnerability_id"),
    ]

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table_name, drop_name, keep_name in redundant_pairs:
            if not inspector.has_table(table_name):
                continue
            names = {idx["name"] for idx in inspector.get_indexes(table_name)}
            names.update(
                constraint["name"]
                for constraint in inspector.get_unique_constraints(table_name)
                if constraint.get("name")
            )
            if drop_name in names and keep_name in names:
                conn.execute(
                    text(f"ALTER TABLE `{table_name}` DROP INDEX `{drop_name}`")
                )


def init_database():
    import orm_models  # noqa: F401
    import orm_models_mitre  # noqa: F401
    import orm_models_dataset  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_dataset_upload_columns()
    _ensure_cwe_catalog_columns()
    _ensure_vulnerability_longtext_columns()
    _drop_redundant_nvd_indexes()
