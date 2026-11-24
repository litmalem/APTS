"""One-time, user-approved DVWA Recon policy revision via authenticated APIs."""
import json
import re
import sqlite3
import sys
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.request import Request, build_opener, ProxyHandler, HTTPCookieProcessor

ROOT = Path('D:/APTS')
sys.path.insert(0, str(ROOT / 'mission_orchestrator'))
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.gss_scope_sync import fetch

MID = 'mission-gmo-17a8fa8a-c6d9-4da5-aad2-0fc73113239c'
TARGET = 'http://127.0.0.1:80//dvwa/'
op = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

def call(url, data=None, headers=None):
    request = Request(url, data=None if data is None else json.dumps(data).encode(),
                      headers={'Content-Type': 'application/json', **(headers or {})})
    with op.open(request, timeout=30) as response:
        return json.load(response)

source = fetch(CanonicalMissionService(), MID)
assert source['scope_contract_id'] == 'scope-1d53c50c-50a8-4c22-9b5b-9537afbd95d7'
assert source['version'] == 1 and source['action_constraints'] == []
assert [(t['target_value'], t['environment']) for t in source['targets']] == [(TARGET, 'LAB')]
backup = ROOT / 'backups/wpt-waiting-policy-20261109'
backup.mkdir(exist_ok=False)
(backup / 'source-scope-before.json').write_text(json.dumps(source, indent=2), encoding='utf-8')
html = op.open('http://127.0.0.1:8800/', timeout=10).read().decode()
control_token = re.search(r"window.CONTROL_TOKEN='([^']+)'", html).group(1)

def action(module, verb):
    result = call('http://127.0.0.1:8800/api/action', {'module': module, 'action': verb},
                  {'X-Control-Token': control_token})
    print(module, verb, result, flush=True)

action('mission', 'stop')
try:
    for name in ['mission_orchestrator.db', 'pentest_subsystem.db',
                 'wpt_governed_intake.db', 'execution_subsystem.db']:
        with sqlite3.connect(ROOT / 'mission_orchestrator/data' / name) as src, sqlite3.connect(backup / name) as dest:
            src.backup(dest)
    with sqlite3.connect(ROOT / 'WebTechnologyProfiler/data/profiler.sqlite3') as src, sqlite3.connect(backup / 'profiler.sqlite3') as dest:
        src.backup(dest)
    origin = {'Origin': 'http://127.0.0.1:8802'}
    login = call('http://127.0.0.1:8802/api/login', {'quick_login': True}, origin)
    contract = {k: source[k] for k in ['mission_id', 'name', 'policy_set_id', 'valid_from',
                                      'valid_until', 'created_by', 'approved_by', 'metadata']}
    contract['targets'] = [{k: t[k] for k in ['target_type', 'target_value', 'environment', 'allowed', 'notes']}
                           for t in source['targets']]
    contract['sources'] = []
    contract['action_constraints'] = [
        {'action_class': 'TARGET_RECON', 'action_name': name, 'effect': 'ALLOW',
         'max_risk_level': 'LOW', 'requires_approval': False,
         'constraints': {'max_network_requests': 6, 'allowed_methods': ['GET'],
                         'state_changing_requests': False}}
        for name in ['recon', 'web_technology_fingerprinting']]
    body = {'contract': contract, 'previous_id': source['scope_contract_id'],
            'expected_version': source['version'], 'apply_auto_recon_task_delegation_profile': True,
            'reason': 'User explicitly approved bounded LAB DVWA Recon and WPT fingerprinting in Codex chat on 2026-11-09; six GET requests, no state changes.'}
    (backup / 'scope-revision-request.json').write_text(json.dumps(body, indent=2), encoding='utf-8')
    result = call('http://127.0.0.1:8802/api/governance/console/scopes', body,
                  {**origin, 'X-CSRF-Token': login['csrf']})
    (backup / 'scope-revision-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    revised = result['scope_contract']
    print('Scope revised', revised['scope_contract_id'], revised['version'], flush=True)
    call('http://127.0.0.1:8802/api/logout', {}, {**origin, 'X-CSRF-Token': login['csrf']})
    action('wpt', 'stop')
    action('wpt', 'start')
finally:
    action('mission', 'start')
