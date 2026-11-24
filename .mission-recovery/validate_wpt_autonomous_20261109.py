"""Create one governed LAB measurement to validate the repaired AUTO flow."""
import json
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.request import Request, build_opener, ProxyHandler, HTTPCookieProcessor

OUTPUT = Path('D:/APTS/docs/wpt-autonomous-live-validation-20261109.json')
if OUTPUT.exists():
    raise RuntimeError('Validation manifest already exists; inspect it instead of duplicating work')
op = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
origin = 'http://127.0.0.1:8802'

def post(path, data, csrf=None):
    headers = {'Content-Type': 'application/json', 'Origin': origin}
    if csrf: headers['X-CSRF-Token'] = csrf
    req = Request(origin + path, data=json.dumps(data).encode(), headers=headers)
    with op.open(req, timeout=30) as response: return json.load(response)

login = post('/api/login', {'quick_login': True})
csrf = login['csrf']
try:
    mission = post('/api/human/missions', {
        'client_request_id': 'wpt-autonomous-repair-validation-20261109',
        'mission_kind': 'AUTHORIZED_PENTEST', 'objective_type': 'AUTHORIZED_PENTEST',
        'objective': 'Validate autonomous bounded WPT fingerprinting after runtime repair for http://127.0.0.1:80//dvwa/',
        'success_criteria': ['Governed WPT fingerprint result sealed and delivered to Recon'],
        'budgets': {'max_actions': 20, 'max_duration_seconds': 1800},
        'metadata': {'purpose': 'WPT_AUTONOMOUS_REPAIR_VALIDATION',
                     'related_mission_id': 'mission-gmo-f3ef7325-c13a-4a46-b9b6-d97b505b1433'}}, csrf)
    mid = (mission.get('mission_id') or (mission.get('canonical_identity') or {}).get('mission_id')
           or ((mission.get('envelope') or {}).get('identity') or {}).get('mission_id'))
    if not mid:
        raise RuntimeError('Mission response missing identity: ' + str(list(mission)))
    manifest = {'mission_id': mid, 'target': 'http://127.0.0.1:80//dvwa/', 'mission_create': mission}
    OUTPUT.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    scope = post('/api/governance/console/scopes', {
        'contract': {'mission_id': mid, 'name': 'Autonomous WPT repair validation — DVWA LAB',
                     'created_by': login['principal_id'], 'policy_set_id': 'default-policy',
                     'targets': [{'target_type': 'URL', 'target_value': manifest['target'], 'environment': 'LAB'}],
                     'action_constraints': [], 'sources': []},
        'reason': 'User requested completion of autonomous WPT repair; one bounded six-GET validation on the same approved LAB target.'}, csrf)
    manifest['scope'] = scope
    OUTPUT.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    saved = scope['scope_contract']
    assert saved['metadata']['gss_workflow_profile']['profile_id'] == 'WPT_FINGERPRINT_AUTONOMOUS_V1'
    print(json.dumps({'mission_id': mid, 'scope_contract_id': saved['scope_contract_id'],
                      'profile': saved['metadata']['gss_workflow_profile']['profile_id']}), flush=True)
finally:
    post('/api/logout', {}, csrf)
