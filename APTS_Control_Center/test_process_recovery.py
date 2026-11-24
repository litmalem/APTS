"""Process recovery and stop regressions; no real APTS services are modified."""
import os
import ctypes
import socket
import struct
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

import server as hub
import local_processes as processes
import windows_processes


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.procs = patch.dict(hub.PROCESSES, {}, clear=True)
        self.procs.start()
        self.addCleanup(self.procs.stop)
        self.row = {'pid': 12345, 'created': '2026-11-08T00:00:00Z',
                    'executable': 'C:/Python313/python.exe', 'ports': [8780],
                    'command': 'python.exe -u "D:/APTS/mission_orchestrator/run/run_stage6_10_mission.py" --port 8780'}

    def test_recovered_mission_and_web_have_same_stoppable_pid(self):
        with patch.object(processes, 'find', return_value=self.row), patch.object(hub, 'fetch', return_value={'ok': True}):
            for key in ('mission', 'mission_web'):
                state = hub.status(key)
                self.assertFalse(state['owned'])
                self.assertTrue(state['can_stop'])
                self.assertTrue(state['recognized'])
                self.assertEqual(state['pid'], 12345)
                self.assertEqual(state['process_owner'], 'mission')

    def test_unhealthy_recognized_service_can_still_be_stopped(self):
        with patch.object(processes, 'find', return_value=self.row), patch.object(hub, 'fetch', return_value={'ok': False}):
            self.assertTrue(hub.status('mission')['can_stop'])

    def test_unverified_service_is_not_stoppable(self):
        with patch.object(processes, 'find', return_value=None), patch.object(hub, 'fetch', return_value={'ok': True}), patch.object(processes, 'stop') as stop:
            self.assertFalse(hub.status('mission')['can_stop'])
            with self.assertRaisesRegex(ValueError, 'diverifikasi'):
                hub.action('mission_web', 'stop')
            stop.assert_not_called()

    def test_discovery_failure_is_visible(self):
        with patch.object(processes, 'find', side_effect=RuntimeError('Access denied')), patch.object(hub, 'fetch', return_value={'ok': True}):
            state = hub.status('mission')
            self.assertFalse(state['can_stop'])
            self.assertEqual(state['control_error'], 'Access denied')

    def test_stop_revalidates_and_checks_port(self):
        with patch.object(processes, 'find', return_value=self.row) as find, patch.object(processes, 'stop') as stop, patch.object(processes, 'port_open', return_value=False):
            result = hub.action('mission_web', 'stop')
            self.assertEqual(result['pid'], 12345)
            self.assertTrue(find.call_args.kwargs['fresh'])
            stop.assert_called_once_with(self.row, hub.module_config('mission')['port'])

    def test_remaining_listener_is_reported_as_failure(self):
        with patch.object(processes, 'find', return_value=self.row), patch.object(processes, 'stop'), patch.object(processes, 'port_open', return_value=True), patch.object(hub.time, 'monotonic', side_effect=[0, 6]):
            with self.assertRaisesRegex(RuntimeError, 'port layanan masih aktif'):
                hub.action('mission', 'stop')

    def test_socket_permission_error_cannot_mean_success(self):
        with patch.object(processes, 'find', return_value=self.row), patch.object(processes, 'stop'), patch.object(processes, 'port_open', side_effect=RuntimeError('TCP table unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'TCP table'):
                hub.action('mission', 'stop')

    def test_all_stop_recovers_and_deduplicates_three_processes(self):
        roots = {str(hub.module_config(k)['root']): None for k in ('mission', 'vulndesk', 'vulndesk_web')}
        def find(root, launcher, port, **kwargs):
            return {**self.row, 'ports': [port]} if root in roots and port in (8765, 8801, 8780) else None
        alive={8765,8801,8780}
        def stopped(key,verb):
            alive.discard(hub.module_config(key)['port'])
            return {'message':'stopped'}
        with patch.object(processes, 'port_open', side_effect=lambda port:port in alive), patch.object(hub, 'action', side_effect=stopped) as action:
            result = hub.action_all('stop')
            self.assertEqual([call.args for call in action.call_args_list], [('mission_web', 'stop'), ('vulndesk_web', 'stop'), ('vulndesk', 'stop')])
            self.assertEqual(len(result['results']), 3)

    def test_all_stop_continues_after_timeout(self):
        with patch.object(processes, 'port_open', return_value=True), patch.object(hub, 'action', side_effect=subprocess.TimeoutExpired('stop', 5)):
            result = hub.action_all('stop')
            self.assertEqual(len(result['results']), 8)
            self.assertTrue(all(not item['ok'] for item in result['results']))
            self.assertIn('8 gagal', result['message'])

    @unittest.skipUnless(os.name == 'nt', 'Windows argument parser')
    def test_only_exact_python_script_is_recognized(self):
        root = hub.module_config('mission')['root']
        launcher = hub.SPECS['mission'][1]
        self.assertTrue(processes.matches(self.row, root, launcher, 8780))
        bad = [
            {**self.row, 'ports': [9999]},
            {**self.row, 'executable': 'C:/tools/other.exe'},
            {**self.row, 'pid': 0},
            {**self.row, 'created': None},
            {**self.row, 'command': 'python.exe run/run_stage6_10_mission.py'},
            {**self.row, 'command': 'python.exe -c "print(1)" ' + self.row['command']},
            {**self.row, 'command': self.row['command'].replace('D:/APTS/', 'D:/other/')},
        ]
        for row in bad:
            with self.subTest(row=row):
                self.assertFalse(processes.matches(row, root, launcher, 8780))

    @unittest.skipUnless(os.name == 'nt', 'Windows argument parser')
    def test_quoted_path_with_spaces(self):
        root = str(Path('D:/APTS/test folder'))
        row = {**self.row, 'command': '"C:/Program Files/Python/python.exe" -u "' + root + '/server.py"'}
        self.assertTrue(processes.matches(row, root, 'server.py', 8780))

    def test_ambiguous_listeners_are_rejected(self):
        with patch.object(processes, 'listeners', return_value=[self.row, self.row]), patch.object(processes, 'matches', return_value=True):
            self.assertIsNone(processes.find('root', 'script.py', 8780))

    @unittest.skipUnless(os.name == 'nt', 'Windows argument parser')
    def test_relative_launcher_uses_process_directory(self):
        root=hub.module_config('mission')['root']
        row={**self.row,'command':'python.exe -u run/run_stage6_10_mission.py','cwd':root}
        self.assertTrue(processes.matches(row,root,hub.SPECS['mission'][1],8780))
        self.assertFalse(processes.matches({**row,'cwd':'D:/unrelated'},root,hub.SPECS['mission'][1],8780))

    def test_unknown_active_listener_is_a_global_failure(self):
        with patch.object(processes,'port_open',side_effect=lambda port:port==8780),patch.object(processes,'find',return_value=None):
            result=hub.action_all('stop')
        self.assertEqual(result['remaining'],['mission'])
        self.assertEqual(len(result['results']),1)
        self.assertFalse(result['results'][0]['ok'])
        self.assertIn('1 gagal',result['message'])

    def test_global_audit_detects_service_that_restarts(self):
        with patch.object(processes,'port_open',side_effect=lambda port:port==8780),patch.object(hub,'action',return_value={'message':'stopped'}):
            result=hub.action_all('stop')
        self.assertFalse(result['results'][0]['ok'])
        self.assertEqual(result['remaining'],['mission'])

    def test_unreadable_identity_is_reported(self):
        with patch.object(processes,'listeners',return_value=[{'pid':123,'ports':[8780],'identity_error':'Access denied'}]):
            with self.assertRaisesRegex(RuntimeError,'Access denied'):
                processes.find('root','script.py',8780)

    @unittest.skipUnless(os.name=='nt','Windows TCP API')
    def test_listener_table_does_not_depend_on_unset_state_field(self):
        raw=struct.pack('=7I',1,0,0x0100007f,socket.htons(8765),0,0,12345)
        def fill(buffer,size,*args):
            size._obj.value=len(raw)
            if buffer is None:return 122
            ctypes.memmove(buffer,raw,len(raw))
            return 0
        api=MagicMock()
        api.GetExtendedTcpTable.side_effect=fill
        with patch.object(windows_processes.C,'WinDLL',return_value=api):
            self.assertEqual(windows_processes.tcp_listeners(),[{'pid':12345,'port':8765}])

    def test_termination_error_is_not_reported_as_success(self):
        with patch.object(processes, 'find', return_value=self.row), patch.object(processes, 'stop', side_effect=RuntimeError('Identitas proses berubah')):
            with self.assertRaisesRegex(RuntimeError, 'berubah'):
                hub.action('mission', 'stop')

    def test_ui_uses_stop_capability_for_buttons_and_global_toggle(self):
        text = (hub.ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertIn("data.modules.some(m=>m.can_stop||m.ok)?", text)
        self.assertIn("${!m.can_stop||acting?'disabled':''}", text)


if __name__ == '__main__':
    unittest.main()
