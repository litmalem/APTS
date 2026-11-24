"""Two-phase initialization; CTI owns intelligence, Mission owns envelope lineage.

No target actions or lifecycle transitions are performed by this module.
"""
from copy import deepcopy
import json
import re
import uuid

from .canonical import build_envelope, canonical_json, new_envelope_id, sha256_hex, utcnow_iso, verify_envelope
from .errors import MissionValidationError, MissionStateConflict, MissionNotFound, MissionIdempotencyConflict
from .mission_events import build_event_record

BINDING_KEY = 'pip_initialization'
GATES = {'QG-H' + str(n) for n in range(1, 11)}


def normalize(payload):
    fields = {'pip_id', 'pip_version', 'expected_envelope_version', 'idempotency_key', 'actor', 'reason'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise MissionValidationError('pip-binding requires exactly: ' + ', '.join(sorted(fields)))
    p = dict(payload)
    for key in fields - {'expected_envelope_version'}:
        if not isinstance(p[key], str) or not p[key].strip() or len(p[key]) > (2000 if key == 'reason' else 128):
            raise MissionValidationError(key + ' must be a non-empty bounded string')
        p[key] = p[key].strip()
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+', p['pip_id']):
        raise MissionValidationError('Invalid pip_id')
    if not re.fullmatch(r'[1-9][0-9]*', p['pip_version']):
        raise MissionValidationError('pip_version must be a positive revision string')
    if type(p['expected_envelope_version']) is not int or p['expected_envelope_version'] < 1:
        raise MissionValidationError('expected_envelope_version must be a positive integer')
    return p


def validate_pip(record, mission_id, p, scope):
    """Verify CTI bytes and its freshly evaluated gates; never accept client artifact bytes."""
    if not isinstance(record, dict) or not isinstance(record.get('artifact'), dict):
        raise MissionValidationError('Malformed CTI PIP response')
    a = record['artifact']
    mb = a.get('mission_binding') or {}
    if (record.get('pip_id') != p['pip_id'] or a.get('pip_id') != p['pip_id'] or
            str(record.get('revision')) != p['pip_version'] or str(a.get('revision')) != p['pip_version'] or
            record.get('mission_id') != mission_id or mb.get('mission_id') != mission_id):
        raise MissionValidationError('PIP identity, revision or mission lineage mismatch')
    if record.get('immutable') is not True:
        raise MissionValidationError('PIP must be published and immutable')
    if (mb.get('mission_scope_sha256') != scope['canonical_sha256'] or
            mb.get('mission_scope_snapshot_id') != scope['snapshot_id'] or
            mb.get('scope') != scope['contract']['scope']):
        raise MissionValidationError('PIP must reference the exact current Mission scope snapshot and scope')
    material = deepcopy(a)
    integ = material.pop('integrity', {})
    if isinstance(material.get('quality'), dict):
        for key in ('validation_results', 'readiness', 'hard_gate_passed'):
            material['quality'].pop(key, None)
    digest = sha256_hex(material)
    if integ.get('sha256') != digest or record.get('canonical_sha256') != digest:
        raise MissionValidationError('CTI PIP canonical hash mismatch')
    results = record.get('validation_results')
    if (not isinstance(results, list) or {r.get('gate_id') for r in results if isinstance(r, dict)} != GATES or
            any(not isinstance(r, dict) or r.get('passed') is not True for r in results)):
        raise MissionValidationError('CTI must return all ten freshly evaluated hard gates; update VulnDesk')
    if record.get('readiness') not in {'PARTIAL', 'ACTIONABLE', 'VALIDATION_READY'}:
        raise MissionValidationError('PIP is not ready for initialization')
    semantics = a.get('semantics') or {}
    if semantics.get('execution_authorized') is not False or semantics.get('execution_command') is not False:
        raise MissionValidationError('PIP must not confer execution authority')
    return digest


def history(repo, mission_id):
    if repo.get_by_mission_id(mission_id) is None:
        raise MissionNotFound(mission_id)
    with repo._lock:
        conn = repo._connect()
        try:
            cur = conn.cursor()
            ph = '?' if repo.driver == 'sqlite' else '%s'
            cur.execute('SELECT canonical_json FROM mission_envelopes WHERE mission_id=' + ph + ' ORDER BY envelope_version', (mission_id,))
            envelopes = [json.loads(row['canonical_json']) for row in cur.fetchall()]
            previous = None
            for e in envelopes:
                if not verify_envelope(e):
                    raise RuntimeError('Mission envelope history integrity failed')
                link = e.get(BINDING_KEY)
                if link and (previous is None or link.get('previous_envelope_sha256') != previous['integrity']['canonical_sha256'] or link.get('previous_envelope_id') != previous['identity']['envelope_id']):
                    raise RuntimeError('Mission envelope predecessor integrity failed')
                previous = e
            return envelopes
        finally:
            conn.close()


def response(envelope, replay=False):
    return {'status': 'bound', 'idempotent_replay': replay, 'mission_id': envelope['identity']['mission_id'],
            'envelope_version': envelope['identity']['envelope_version'], 'envelope': envelope,
            'pip_binding': envelope['bindings']['pip'], 'execution_authorized': False, 'target_actuation': False}


def bind(service, mission_id, payload):
    p = normalize(payload)
    fingerprint = sha256_hex(p)
    envelopes = history(service.repository, mission_id)
    for e in envelopes:
        previous = e.get(BINDING_KEY) or {}
        if previous.get('idempotency_key') == p['idempotency_key']:
            if previous.get('request_sha256') != fingerprint:
                raise MissionIdempotencyConflict('PIP binding key reused with different payload')
            return response(e, True)
    old = envelopes[-1]
    if old['identity']['envelope_version'] != p['expected_envelope_version']:
        raise MissionStateConflict('Stale expected_envelope_version')
    state = service.repository.get_state(mission_id)
    if state['state'] != 'CREATED' or any(old['bindings']['pip'].values()):
        raise MissionStateConflict('PIP initialization requires CREATED and an empty PIP binding')
    scope = service.get_mission_scope_contract(mission_id)
    if scope is None:
        raise MissionValidationError('Create Mission Scope Contract before building/binding PIP')
    pip = service.cti_client.get_pip(p['pip_id'])
    digest = validate_pip(pip, mission_id, p, scope)
    core = deepcopy(old)
    core.pop('integrity')
    core['identity'].update(envelope_id=new_envelope_id(), envelope_version=p['expected_envelope_version'] + 1)
    core['bindings']['pip'] = {'pip_id': p['pip_id'], 'pip_version': p['pip_version']}
    core[BINDING_KEY] = {**p, 'request_sha256': fingerprint, 'bound_at': utcnow_iso(),
                         'previous_envelope_id': old['identity']['envelope_id'],
                         'previous_envelope_sha256': old['integrity']['canonical_sha256'],
                         'pip_sha256': digest, 'pip_readiness': pip['readiness'],
                         'scope_snapshot_id': scope['snapshot_id'], 'scope_sha256': scope['canonical_sha256']}
    envelope = build_envelope(core)
    committed, replay = append_atomic(service.repository, old, envelope, state, scope)
    return response(committed, replay)


def append_atomic(repo, old, envelope, state, scope):
    """CAS and append envelope + hash-chain event in one SQLite/MySQL transaction."""
    mid = old['identity']['mission_id']
    init = envelope[BINDING_KEY]
    with repo._lock:
        conn = repo._connect()
        try:
            sqlite = repo.driver == 'sqlite'
            if sqlite:
                conn.execute('BEGIN IMMEDIATE')
            else:
                conn.begin()
            cur = conn.cursor()
            def execute(sql, params=()):
                cur.execute(sql if sqlite else sql.replace('?', '%s'), params)
            lock = '' if sqlite else ' FOR UPDATE'
            execute('SELECT mission_id FROM global_missions WHERE mission_id=?' + lock, (mid,))
            if cur.fetchone() is None:
                raise MissionNotFound(mid)
            execute('SELECT * FROM mission_states WHERE mission_id=?' + lock, (mid,))
            current_state = dict(cur.fetchone())
            execute('SELECT * FROM mission_envelopes WHERE mission_id=? ORDER BY envelope_version DESC LIMIT 1' + lock, (mid,))
            latest = json.loads(cur.fetchone()['canonical_json'])
            found = latest.get(BINDING_KEY) or {}
            if found.get('idempotency_key') == init['idempotency_key']:
                if found.get('request_sha256') != init['request_sha256']:
                    raise MissionIdempotencyConflict('Concurrent PIP idempotency conflict')
                conn.rollback()
                return latest, True
            if (current_state['state'] != 'CREATED' or current_state['state_version'] != state['state_version'] or
                    latest['integrity']['canonical_sha256'] != old['integrity']['canonical_sha256']):
                raise MissionStateConflict('Mission changed during PIP verification; refresh and retry')
            execute('SELECT * FROM mission_scope_contract_heads WHERE mission_id=?' + lock, (mid,))
            current_scope = cur.fetchone()
            if current_scope is None or current_scope['current_sha256'] != scope['canonical_sha256']:
                raise MissionStateConflict('Mission scope changed during PIP verification')
            ident = envelope['identity']
            execute('''INSERT INTO mission_envelopes (envelope_id,mission_id,envelope_version,schema_version,
                       canonical_sha256,canonical_json,created_at) VALUES (?,?,?,?,?,?,?)''',
                    (ident['envelope_id'], mid, ident['envelope_version'], envelope['schema_version'],
                     envelope['integrity']['canonical_sha256'], canonical_json(envelope), init['bound_at'] if sqlite else repo._mysql_dt(init['bound_at'])))
            execute('SELECT * FROM mission_events WHERE mission_id=? ORDER BY id DESC LIMIT 1' + lock, (mid,))
            row = cur.fetchone()
            previous = repo._mission_event_row(dict(row)) if row is not None else None
            event = build_event_record(event_id='mevt-' + str(uuid.uuid4()), mission_id=mid,
                                      correlation_id=ident['correlation_id'], event_type='MISSION_PIP_BOUND',
                                      payload={**init, 'envelope_id': ident['envelope_id'],
                                               'envelope_sha256': envelope['integrity']['canonical_sha256']},
                                      occurred_at=init['bound_at'], previous_event=previous,
                                      source_component='APTS-MO01', state_version=state['state_version'],
                                      causation_id=ident['envelope_id'])
            columns = ['event_id','mission_id','schema_version','trace_id','correlation_id','causation_id',
                       'parent_event_id','source_component','event_type','state_version','plan_version','policy_version',
                       'payload_json','previous_event_sha256','canonical_sha256','occurred_at','recorded_at']
            event['payload_json'] = canonical_json(event['payload'])
            event['recorded_at'] = event['occurred_at']
            execute('INSERT INTO mission_events (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')',
                    tuple(repo._mysql_dt(event[k]) if not sqlite and k in {'occurred_at','recorded_at'} else event.get(k) for k in columns))
            conn.commit()
            return envelope, False
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def build_pip(service, mission_id, payload):
    allowed = {'asset_profiles','cpe_claims','vulnerability_correlations','attack_mappings','attack_paths',
               'threat_contexts','risk_priorities','normalized_objects','provenance_records','assumptions_and_gaps'}
    if not isinstance(payload, dict) or set(payload) - allowed or any(not isinstance(v, list) for v in payload.values()):
        raise MissionValidationError('pip-build accepts only CTI evidence collection arrays')
    stored = service.repository.get_by_mission_id(mission_id)
    if stored is None:
        raise MissionNotFound(mission_id)
    if service.repository.get_state(mission_id)['state'] != 'CREATED' or any(stored.envelope['bindings']['pip'].values()):
        raise MissionStateConflict('Initialization build requires CREATED and no bound PIP')
    scope = service.get_mission_scope_contract(mission_id)
    if scope is None:
        raise MissionValidationError('Mission Scope Contract is required')
    body = {**payload, 'mission_id': mission_id, 'mission_binding': {
        'scope': scope['contract']['scope'], 'scope_allowed': True,
        'mission_scope_sha256': scope['canonical_sha256'], 'mission_scope_snapshot_id': scope['snapshot_id']}}
    return service.cti_client.build_pip(body)
