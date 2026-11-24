"""Regression coverage for URL allowlist persistence and path scope."""
import os
import unittest
from unittest.mock import patch
import test_profiler
app = test_profiler.app

class AllowlistPathTest(unittest.TestCase):
 setUpClass = classmethod(test_profiler.ProfilerAPITest.setUpClass.__func__)
 tearDownClass = classmethod(test_profiler.ProfilerAPITest.tearDownClass.__func__)
 call = test_profiler.ProfilerAPITest.call
 def test_path_roundtrip(self):
  entry='http://127.0.0.1//dvwa/'
  status,data=self.call('/api/remote-allowlist','POST',{'entry':entry})
  self.assertEqual(status,201)
  self.assertEqual(data['entry'],'http://127.0.0.1:80//dvwa/')
  self.assertIn(data['entry'],[x['entry'] for x in self.call('/api/remote-allowlist')[1]['entries']])
  self.assertTrue(app.is_remote_allowlisted(entry+'login.php'))
  for url in ('http://127.0.0.1/',entry+'../other',entry+'%252e%252e/other','http://127.0.0.1//dvwa-other/'):
   self.assertFalse(app.is_remote_allowlisted(url),url)
  self.assertEqual(self.call('/api/remote-allowlist','DELETE',{'entry':entry})[0],200)
  self.assertFalse(app.is_remote_allowlisted(entry))
 def test_environment_case_and_scheme(self):
  with patch.dict(os.environ,{'WTP_REMOTE_ALLOWLIST':'https://CASE.example.test/App/'}):
   self.assertTrue(app.is_remote_allowlisted('https://case.example.test/App/login'))
   self.assertFalse(app.is_remote_allowlisted('https://case.example.test/app/login'))
   self.assertFalse(app.is_remote_allowlisted('http://case.example.test:443/App/login'))
 def test_invalid_scopes(self):
  for suffix in ('/a/../b','/a/%2e%2e/b','/a/?q=1','/a/#b',':0/a'):
   with self.assertRaises(ValueError): app.normalize_allowlist_entry('http://invalid.example.test'+suffix)
