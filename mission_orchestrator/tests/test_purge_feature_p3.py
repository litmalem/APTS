import gc
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mission_orchestrator.archive_mission import ArchiveConflict
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService

BASE = Path(__file__).parent / "data/mission_orchestrator.db"


class PurgeFeatureP3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "mission.db"
        shutil.copyfile(BASE, self.path)
        self.repo = MissionRepository(driver="sqlite", sqlite_path=str(self.path))
        self.service = CanonicalMissionService(repository=self.repo)
        self.old_env = {key: os.environ.get(key) for key in ("MISSION_PURGE_MIN_RETENTION_DAYS", "MISSION_PURGE_REQUESTOR_ACTOR", "MISSION_PURGE_APPROVER_ACTOR")}
        os.environ["MISSION_PURGE_MIN_RETENTION_DAYS"] = "30"
        os.environ["MISSION_PURGE_REQUESTOR_ACTOR"] = "purge-requester-test"
        os.environ["MISSION_PURGE_APPROVER_ACTOR"] = "purge-approver-test"
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute("""SELECT ms.mission_id, ms.state_version FROM mission_states ms
                WHERE ms.terminal=1 AND NOT EXISTS (SELECT 1 FROM global_missions c WHERE c.parent_mission_id=ms.mission_id)
                LIMIT 1""").fetchone()
            self.mid, self.version = row

    def tearDown(self):
        for key, value in self.old_env.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
        gc.collect()
        self.temp.cleanup()

    def test_purge_requires_retention_and_second_principal_and_keeps_tombstone(self):
        self.service.archive_mission(self.mid, {
            "expected_state_version": self.version,
            "actor_id": "archive-test-operator",
            "reason": "Archive for P3 purge test",
            "idempotency_key": "p3-archive-test-001",
        })
        with closing(sqlite3.connect(self.path)) as conn:
            old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat().replace("+00:00", "Z")
            conn.execute("UPDATE mission_archive_state SET archived_at=? WHERE mission_id=?", (old, self.mid))
            conn.commit()
        request = self.service.request_mission_purge(self.mid, {
            "reason": "Approved lifecycle ended; purge under retention policy",
            "idempotency_key": "p3-purge-request-0001",
        })
        approval = {"request_id": request["request_id"], "challenge": request["challenge"], "approval_reason": "Independent review confirms retention and scope", "legal_hold_check": "CLEAR", "external_dependency_check": "CLEAR"}
        with self.assertRaises(ArchiveConflict):
            self.repo.approve_and_purge_mission(self.mid, actor_id="purge-requester-test", retention_days=30, **approval)
        result = self.service.approve_and_purge_mission(self.mid, approval)
        self.assertTrue(result["purged"])
        self.assertIsNone(self.repo.get_by_mission_id(self.mid))
        with closing(sqlite3.connect(self.path)) as conn:
            ledger = conn.execute("SELECT mission_id, requested_by, approved_by, manifest_sha256, previous_hash, record_hash FROM mission_purge_ledger WHERE request_id=?", (request["request_id"],)).fetchone()
            self.assertEqual(self.mid, ledger[0])
            self.assertEqual("purge-requester-test", ledger[1])
            self.assertEqual("purge-approver-test", ledger[2])
            self.assertEqual(64, len(ledger[3]))
            self.assertEqual(64, len(ledger[5]))

    def test_retention_period_is_enforced_at_request_time(self):
        self.service.archive_mission(self.mid, {
            "expected_state_version": self.version,
            "actor_id": "archive-test-operator",
            "reason": "Archive for retention test",
            "idempotency_key": "p3-archive-retention-001",
        })
        with self.assertRaises(ArchiveConflict):
            self.service.request_mission_purge(self.mid, {
                "reason": "Attempt before retention expires for policy test",
                "idempotency_key": "p3-purge-early-0001",
            })


if __name__ == "__main__":
    unittest.main(verbosity=2)
