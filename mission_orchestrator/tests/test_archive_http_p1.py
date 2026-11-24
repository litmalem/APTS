import json,os,sqlite3,tempfile,shutil,threading,urllib.request,urllib.error,unittest,gc
from contextlib import closing
from pathlib import Path
from http.server import ThreadingHTTPServer
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.api_service import MissionOrchestratorHandler

class TestArchiveHttp(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();target=Path(self.temp.name)/'test.db';shutil.copyfile(Path(__file__).parent/'data/mission_orchestrator.db',target)
  self.repo=MissionRepository(driver='sqlite',sqlite_path=str(target))
  # Record opened SQLite handles; transaction context managers do not close them.
  self._connections=[]
  self._original_sqlite_connect=self.repo._sqlite_connect
  def tracked_connect():
   conn=self._original_sqlite_connect()
   self._connections.append(conn)
   return conn
  self.repo._sqlite_connect=tracked_connect
  with closing(sqlite3.connect(target)) as db:
   self.mid,self.version=db.execute("SELECT mission_id,state_version FROM mission_states WHERE terminal=1 LIMIT 1").fetchone()
   self.active,_=db.execute("SELECT mission_id,state_version FROM mission_states WHERE terminal=0 LIMIT 1").fetchone()
  MissionOrchestratorHandler.service=CanonicalMissionService(repository=self.repo)
  self.srv=ThreadingHTTPServer(('127.0.0.1',0), MissionOrchestratorHandler)
  self.thread=threading.Thread(target=self.srv.serve_forever,daemon=True);self.thread.start()
  self.base=f'http://127.0.0.1:{self.srv.server_port}'
  self.prev=os.environ.get('MISSION_ARCHIVE_ADMIN_TOKEN');os.environ['MISSION_ARCHIVE_ADMIN_TOKEN']='local-test-token-not-for-production'
  os.environ['MISSION_HTTP_QUIET']='1'
 def tearDown(self):
  self.srv.shutdown();self.srv.server_close();self.thread.join(timeout=3)
  if self.prev is None:os.environ.pop('MISSION_ARCHIVE_ADMIN_TOKEN',None)
  else:os.environ['MISSION_ARCHIVE_ADMIN_TOKEN']=self.prev
  try:
   for conn in reversed(self._connections):
    conn.close()
   self.repo._sqlite_connect=self._original_sqlite_connect
   gc.collect()
  finally:
   self.temp.cleanup()
 def request(self,path, body=None,token=None):
  headers={}
  if body is not None:
   headers['Content-Type']='application/json'
  if token is not None:headers['X-Mission-Archive-Token']=token
  req=urllib.request.Request(self.base+path,headers=headers,data=json.dumps(body).encode() if body is not None else None,method='POST' if body is not None else 'GET')
  try:
   with urllib.request.urlopen(req,timeout=10) as res:return res.status,json.loads(res.read())
  except urllib.error.HTTPError as exc:return exc.code,json.loads(exc.read())
 def test_http_auth_error_filter_and_idempotency(self):
  path='/api/missions/'+self.mid+'/archive'
  payload={'expected_state_version':self.version,'reason':'HTTP acceptance verification','idempotency_key':'archive-http-accept-111'}
  self.assertEqual(self.request(path,body=payload)[0],403)
  self.assertEqual(self.request(path,body=payload,token='bad')[0],403)
  self.assertEqual(self.request(path,body=payload,token='local-test-token-not-for-production')[0],200)
  stat,data=self.request(path,body=payload,token='local-test-token-not-for-production')
  self.assertEqual(stat,200);self.assertTrue(data['idempotent_replay'])
  self.assertTrue(self.request(path)[1]['archive']['archived'])
  self.assertFalse(any(m['mission_id']==self.mid for m in self.request('/api/missions?visibility=ACTIVE&limit=200')[1]['missions']))
  self.assertTrue(any(m['mission_id']==self.mid for m in self.request('/api/missions?visibility=ARCHIVED&limit=200')[1]['missions']))
  self.assertEqual(self.request('/api/missions?visibility=INVALID')[0],400)
 def test_http_fail_closed_when_unconfigured(self):
  os.environ.pop('MISSION_ARCHIVE_ADMIN_TOKEN',None)
  self.assertEqual(self.request('/api/missions/'+self.mid+'/archive',body={'a':'b'},token='anything')[0],503)
if __name__=='__main__':unittest.main(verbosity=2)
