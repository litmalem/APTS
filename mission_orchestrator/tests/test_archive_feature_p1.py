import os,sqlite3,tempfile,shutil,unittest,json,gc
from contextlib import closing
from pathlib import Path
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.archive_mission import ArchiveConflict,ArchiveValidationError

BASE=Path(__file__).parent/'data/mission_orchestrator.db'
class ArchiveFeatureTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'mo.db'
  shutil.copyfile(BASE,self.path)
  self.repo=MissionRepository(driver='sqlite',sqlite_path=str(self.path))
  # sqlite3.Connection.__exit__ commits/rolls back but does NOT close the file.
  # Track connections opened by the repository so Windows can delete the fixture.
  self._connections=[]
  self._original_sqlite_connect=self.repo._sqlite_connect
  def tracked_connect():
   conn=self._original_sqlite_connect()
   self._connections.append(conn)
   return conn
  self.repo._sqlite_connect=tracked_connect
  self.service=CanonicalMissionService(repository=self.repo)
  with closing(sqlite3.connect(self.path)) as conn:
   self.terminal=conn.execute("SELECT mission_id,state_version FROM mission_states WHERE terminal=1 LIMIT 1").fetchone()
   self.active=conn.execute("SELECT mission_id,state_version FROM mission_states WHERE terminal=0 LIMIT 1").fetchone()
   self.before=(conn.execute('select count(*) from global_missions').fetchone()[0],conn.execute('select count(*) from mission_events').fetchone()[0],conn.execute('select count(*) from mission_state_transitions').fetchone()[0])
 def tearDown(self):
  try:
   for conn in reversed(self._connections):
    conn.close()
   self.repo._sqlite_connect=self._original_sqlite_connect
   # Dispose of any connections opened in MissionRepository.__init__.
   gc.collect()
  finally:
   self.temp.cleanup()
 def test_archive_visibility_lineage_and_idempotency(self):
  mid,sv=self.terminal
  total=self.service.list_missions(visibility='ALL')['mission_count']
  payload=dict(expected_state_version=sv,actor_id='testing-operator',reason='Acceptance testing only',idempotency_key='unique-archive-test-1')
  first=self.service.archive_mission(mid,payload)
  self.assertTrue(first['archived']);self.assertFalse(first['idempotent_replay'])
  second=self.service.archive_mission(mid,payload)
  self.assertTrue(second['idempotent_replay']);self.assertEqual(first['archive_event_id'],second['archive_event_id'])
  self.assertEqual(self.service.list_missions(visibility='ACTIVE')['mission_count'],total-1)
  self.assertEqual(self.service.list_missions(visibility='ARCHIVED')['mission_count'],1)
  self.assertEqual(self.service.list_missions(visibility='ALL')['mission_count'],total)
  self.assertTrue(self.service.get_archive_status(mid)['archive']['archived'])
  self.assertEqual(self.service.get_dashboard_summary()['mission_counts']['archived'],1)
  self.assertEqual(self.service.get_dashboard_summary()['mission_counts']['historical_total'],total)
  self.assertFalse(any(i['mission_id']==mid for i in self.service.get_operator_attention(limit=200)['items']))
  with closing(sqlite3.connect(self.path)) as c:
   self.assertEqual(self.before,(c.execute('select count(*) from global_missions').fetchone()[0],c.execute('select count(*) from mission_events').fetchone()[0],c.execute('select count(*) from mission_state_transitions').fetchone()[0]))
   self.assertEqual(1,c.execute('select count(*) from mission_archive_history').fetchone()[0])
  with self.assertRaises(ArchiveConflict):self.service.archive_mission(mid,{**payload,'reason':'Different reason repeated'})
 def test_active_and_stale_rejected(self):
  mid,sv=self.active
  with self.assertRaises(ArchiveConflict):self.service.archive_mission(mid,dict(expected_state_version=sv,actor_id='archive-admin',reason='Active mission not allowed',idempotency_key='unique-test-active-1'))
  mid,sv=self.terminal
  with self.assertRaises(ArchiveConflict):self.service.archive_mission(mid,dict(expected_state_version=sv+1,actor_id='archive-admin',reason='Wrong version rejected',idempotency_key='unique-test-stale-1'))
 def test_invalid_payload_and_visibility(self):
  mid,sv=self.terminal
  with self.assertRaises(ArchiveValidationError):self.service.archive_mission(mid,dict(expected_state_version=True,actor_id='x',reason='short',idempotency_key='aa'))
  with self.assertRaises(ArchiveValidationError):self.service.list_missions(visibility='SUSPICIOUS')
 def test_nonterminal_still_visible(self):
  m=self.service.list_missions(visibility='ACTIVE',limit=200)
  self.assertTrue(any(not x['terminal'] for x in m['missions']))
  self.assertTrue(all(not x['archived'] for x in m['missions']))
if __name__=='__main__':unittest.main(verbosity=2)
