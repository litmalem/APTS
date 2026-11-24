import unittest
from unittest.mock import patch
from test_control_center import hub

class GssWebTests(unittest.TestCase):
    def test_defaults_inherit_gss_root_and_env(self):
        with patch.dict(hub.CONFIG['modules'],{'gss':{'root':'D:/custom GSS','port':18770,'python':'python-local','env':{'KEY':'value'}},'gss_web':{'port':18802}}):
            cfg=hub.module_config('gss_web')
            self.assertEqual(cfg['root'],'D:/custom GSS');self.assertEqual(cfg['python'],'python-local');self.assertEqual(cfg['port'],18802)
            self.assertEqual(cfg['env'],{'KEY':'value'})
    def test_open_and_monitor(self):
        with patch.object(hub,'fetch',return_value={'ok':True}),patch.object(hub.webbrowser,'open_new_tab',return_value=True) as browser:
            result=hub.action('gss_web','open');self.assertEqual(result['url'],'http://127.0.0.1:8802');browser.assert_called_once()
            self.assertEqual(hub.health_path('gss_web'),'/health')
    def test_external_gss_web_not_stopped(self):
        with self.assertRaises(ValueError):hub.action('gss_web','stop')
