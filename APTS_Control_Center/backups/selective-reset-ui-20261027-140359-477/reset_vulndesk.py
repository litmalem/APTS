"""Preview and clear Vulndesk operational records while retaining reference catalogs."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


# Runtime evidence, CTI agent state, user supplied dataset rows, and WPT bridge
# records. Static NVD/CWE/CPE/MITRE catalogs and service/source configuration
# are deliberately excluded.
TABLES = (
    "cti_missions", "cti_events", "cti_plans", "cti_task_contracts",
    "cti_action_proposals", "cti_decision_traces", "cti_event_deliveries",
    "cti_raw_artifacts", "cti_normalized_objects", "cti_provenance_records",
    "cti_asset_profiles", "cti_cpe_resolution_claims", "cti_enrichment_requirements",
    "cti_vulnerability_correlations", "cti_attack_mappings",
    "cti_attack_graph_snapshots", "cti_attack_paths", "cti_threat_contexts",
    "cti_beliefs", "cti_intentions", "cti_priority_portfolios",
    "cti_pip_artifacts", "cti_pip_validation_results", "cti_audit_log",
    "cti_policy_decision_revocations", "cti_source_state",
    "cti_wpt_verified_evidence", "pentest_enrichment_requests",
    "pentest_enrichment_request_results", "target_detected_technologies",
    "target_discovered_endpoints", "target_input_points", "target_cpe_candidates",
    "pentest_local_vulnerability_candidates", "pentest_vulnerability_local_candidates",
    "pentest_vulnerability_candidates", "dataset_uploads", "tweet_topic_records",
    "topic_master_records", "sync_audit",
)


def _load():
    from db import engine
    from config import Config
    return engine, Config


def _quote(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _present_tables(conn) -> list[str]:
    rows = conn.exec_driver_sql("SHOW TABLES").fetchall()
    names = {str(row[0]) for row in rows}
    return [name for name in TABLES if name in names]


def _file_inventory(config) -> tuple[Path, list[Path], int]:
    root = Path(config.upload_dir()).resolve()
    app_root = Path(config.app_base_dir()).resolve()
    if root == app_root or root in app_root.parents:
        raise RuntimeError("Dataset upload directory is too broad; refusing to clear it")
    if root.exists() and any(p.is_symlink() for p in [root, *root.rglob("*")]):
        raise RuntimeError("Dataset upload directory contains a symlink; refusing to clear it")
    files = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
    return root, files, sum(p.stat().st_size for p in files)


def preview() -> dict:
    engine, config = _load()
    with engine.connect() as conn:
        tables = _present_tables(conn)
        counts = [{"table": name, "rows": int(conn.exec_driver_sql(
            f"SELECT COUNT(*) FROM {_quote(name)}").scalar_one())} for name in tables]
    root, files, size = _file_inventory(config)
    return {"module": "Vulndesk", "database": config.DB_NAME,
            "tables": counts, "upload_directory": str(root),
            "uploaded_files": len(files), "uploaded_bytes": size}


def _backup(conn, tables: list[str], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = conn.connection.driver_connection
    cursor = raw.cursor()
    try:
        with target.open("w", encoding="utf-8", newline="\n") as out:
            out.write("SET FOREIGN_KEY_CHECKS=0;\n")
            for table in tables:
                cursor.execute("SHOW CREATE TABLE " + _quote(table))
                ddl = cursor.fetchone()[1]
                out.write("DROP TABLE IF EXISTS " + _quote(table) + ";\n" + ddl + ";\n")
                cursor.execute("SELECT * FROM " + _quote(table))
                columns = len(cursor.description or ())
                for row in cursor.fetchall():
                    values = ",".join(["%s"] * columns)
                    statement = cursor.mogrify(
                        "INSERT INTO " + _quote(table) + " VALUES (" + values + ");", row
                    )
                    out.write((statement.decode("utf-8") if isinstance(statement, bytes) else statement) + "\n")
            out.write("SET FOREIGN_KEY_CHECKS=1;\n")
    finally:
        cursor.close()


def prepare(backup_dir: Path) -> dict:
    engine, config = _load()
    backup_dir.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn:
        tables = _present_tables(conn)
        counts = [{"table": name, "rows": int(conn.exec_driver_sql(
            f"SELECT COUNT(*) FROM {_quote(name)}").scalar_one())} for name in tables]
        db_backup = backup_dir / "vulndesk-operational-before.sql"
        _backup(conn, tables, db_backup)
    root, files, size = _file_inventory(config)
    file_backup = backup_dir / "vulndesk-dataset-uploads"
    if files:
        shutil.copytree(root, file_backup, dirs_exist_ok=False)
    return {"tables": counts, "backup_sql": str(db_backup),
            "backup_files": str(file_backup) if files else None,
            "uploaded_files": len(files), "uploaded_bytes": size}


def apply(backup_dir: Path) -> dict:
    engine, config = _load()
    if not (backup_dir / "vulndesk-operational-before.sql").is_file():
        raise RuntimeError("Vulndesk backup is missing; reset cancelled")
    db_backup = backup_dir / "vulndesk-operational-before.sql"
    with engine.connect() as conn:
        tables = _present_tables(conn)
        counts = [{"table": name, "rows": int(conn.exec_driver_sql(
            f"SELECT COUNT(*) FROM {_quote(name)}").scalar_one())} for name in tables]
    root, files, size = _file_inventory(config)
    file_backup = backup_dir / "vulndesk-dataset-uploads"
    if files and not file_backup.is_dir():
        raise RuntimeError("Vulndesk dataset-file backup is missing; reset cancelled")
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        try:
            for table in tables:
                cur.execute("DELETE FROM " + _quote(table))
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            cur.execute("SET FOREIGN_KEY_CHECKS=1")
            cur.close()
        with engine.connect() as verify:
            remaining = {name: int(verify.exec_driver_sql(
                f"SELECT COUNT(*) FROM {_quote(name)}").scalar_one()) for name in tables}
        if any(remaining.values()):
            raise RuntimeError("Vulndesk operational rows remain after reset")
        if root.exists():
            for child in root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
    finally:
        raw.close()
    return {"module": "Vulndesk", "tables": counts, "rows_removed": sum(x["rows"] for x in counts),
            "uploaded_files_removed": len(files), "uploaded_bytes_removed": size,
            "backup_sql": str(db_backup), "backup_files": str(file_backup) if files else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--prepare-backup-dir", type=Path)
    parser.add_argument("--apply-backup-dir", type=Path)
    args = parser.parse_args()
    modes=[args.preview,args.prepare_backup_dir is not None,args.apply_backup_dir is not None]
    if sum(bool(x) for x in modes)!=1: parser.error("choose exactly one of --preview, --prepare-backup-dir, or --apply-backup-dir")
    result = preview() if args.preview else prepare(args.prepare_backup_dir.resolve()) if args.prepare_backup_dir else apply(args.apply_backup_dir.resolve())
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
