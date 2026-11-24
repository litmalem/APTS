import gc
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from mission_orchestrator.archive_mission import ArchiveConflict
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


BASE = Path(__file__).parent / "data/mission_orchestrator.db"


class RestoreFeatureP2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "mission.db"
        shutil.copyfile(BASE, self.path)
        self.repo = MissionRepository(driver="sqlite", sqlite_path=str(self.path))
        self.connections = []
        original = self.repo._sqlite_connect
        self.original_sqlite_connect = original

        def tracked_connect():
            conn = original()
            self.connections.append(conn)
            return conn

        self.repo._sqlite_connect = tracked_connect
        self.service = CanonicalMissionService(repository=self.repo)
        with closing(sqlite3.connect(self.path)) as conn:
            self.mid, self.version = conn.execute(
                "SELECT mission_id, state_version FROM mission_states WHERE terminal=1 LIMIT 1"
            ).fetchone()
            self.canonical_before = (
                conn.execute("SELECT count(*) FROM global_missions").fetchone()[0],
                conn.execute("SELECT count(*) FROM mission_events").fetchone()[0],
                conn.execute("SELECT count(*) FROM mission_state_transitions").fetchone()[0],
                conn.execute("SELECT state, state_version FROM mission_states WHERE mission_id=?", (self.mid,)).fetchone(),
            )

    def tearDown(self):
        for conn in reversed(self.connections):
            conn.close()
        self.repo._sqlite_connect = self.original_sqlite_connect
        gc.collect()
        self.temp.cleanup()

    def payload(self, key, reason):
        return {
            "expected_state_version": self.version,
            "actor_id": "restore-test-operator",
            "reason": reason,
            "idempotency_key": key,
        }

    def test_restore_removes_visibility_marker_and_appends_audit(self):
        self.service.archive_mission(self.mid, self.payload("archive-restore-test-01", "Archive before restore test"))
        first = self.service.restore_mission(self.mid, self.payload("restore-test-idempotency-01", "Return to operational list"))
        replay = self.service.restore_mission(self.mid, self.payload("restore-test-idempotency-01", "Return to operational list"))

        self.assertFalse(first["archived"])
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(first["restore_event_id"], replay["restore_event_id"])
        self.assertFalse(self.service.get_archive_status(self.mid)["archive"]["archived"])
        self.assertTrue(any(m["mission_id"] == self.mid for m in self.service.list_missions(visibility="ACTIVE", limit=200)["missions"]))
        self.assertFalse(any(m["mission_id"] == self.mid for m in self.service.list_missions(visibility="ARCHIVED", limit=200)["missions"]))

        with closing(sqlite3.connect(self.path)) as conn:
            canonical_after = (
                conn.execute("SELECT count(*) FROM global_missions").fetchone()[0],
                conn.execute("SELECT count(*) FROM mission_events").fetchone()[0],
                conn.execute("SELECT count(*) FROM mission_state_transitions").fetchone()[0],
                conn.execute("SELECT state, state_version FROM mission_states WHERE mission_id=?", (self.mid,)).fetchone(),
            )
            history = conn.execute("SELECT operation, previous_hash, record_hash FROM mission_archive_history WHERE mission_id=? ORDER BY id", (self.mid,)).fetchall()
        self.assertEqual(self.canonical_before, canonical_after)
        self.assertEqual(["ARCHIVE", "RESTORE"], [row[0] for row in history])
        self.assertEqual(history[0][2], history[1][1])

    def test_restore_rejects_unarchived_and_stale_missions(self):
        with self.assertRaises(ArchiveConflict):
            self.service.restore_mission(self.mid, self.payload("restore-unarchived-test-01", "Mission is not archived"))
        self.service.archive_mission(self.mid, self.payload("archive-stale-restore-01", "Prepare stale restore test"))
        with self.assertRaises(ArchiveConflict):
            self.service.restore_mission(self.mid, {**self.payload("restore-stale-test-01", "Stale state rejected"), "expected_state_version": self.version + 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
