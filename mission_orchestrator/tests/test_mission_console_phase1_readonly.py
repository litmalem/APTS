from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_phase1_console_read_models_are_read_only(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source_db = root / "data" / "mission_orchestrator.db"
    db = tmp_path / "mission_orchestrator.db"
    shutil.copy2(source_db, db)

    repo = MissionRepository(sqlite_path=str(db))
    service = CanonicalMissionService(repository=repo)
    before = _sha256(db)

    missions = service.list_missions(limit=5)
    summary = service.get_dashboard_summary()
    attention = service.get_operator_attention(limit=5)

    after = _sha256(db)
    assert before == after
    assert missions["read_only"] is True
    assert summary["read_only"] is True
    assert attention["read_only"] is True
    assert missions["mission_count"] == summary["mission_counts"]["total"]
    assert len(missions["missions"]) <= 5


def test_phase1_console_filters_existing_missions(tmp_path):
    root = Path(__file__).resolve().parents[1]
    db = tmp_path / "mission_orchestrator.db"
    shutil.copy2(root / "data" / "mission_orchestrator.db", db)
    service = CanonicalMissionService(repository=MissionRepository(sqlite_path=str(db)))

    running = service.list_missions(state="RUNNING", limit=200)
    assert all(item["state"] == "RUNNING" for item in running["missions"])
    assert running["mission_count"] == len(running["missions"])


def test_phase1_read_models_remain_present_after_phase2_extension():
    root = Path(__file__).resolve().parents[1]
    web = root / "mission_web"
    assert (web / "index.html").is_file()
    assert (web / "app.css").is_file()
    assert (web / "app.js").is_file()
    js = (web / "app.js").read_text(encoding="utf-8")
    assert "/api/dashboard/summary" in js
    assert "/api/missions?" in js
    assert "/api/operator/attention" in js
