"""Paginated governance views and authenticated administration; no target execution."""
from datetime import datetime, timezone
from typing import Literal
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from .console_auth import require, capabilities
from .models import ScopeContractCreate
from .governance_service import _aware_utc

class Change(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=3, max_length=4000)
    expected_version: int = Field(ge=1)

class ScopeWrite(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    contract: ScopeContractCreate
    reason: str = Field(min_length=3, max_length=4000)
    previous_id: str | None = None
    expected_version: int | None = None
    apply_auto_recon_task_delegation_profile: bool = False
    workflow_profile: Literal['AUTO', 'NONE', 'PENTEST_AUTONOMOUS_BOUNDED_V1', 'WPT_FINGERPRINT_AUTONOMOUS_V1'] = 'AUTO'

class PolicyChange(Change):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(max_length=10000)
    status: Literal['DRAFT', 'ACTIVE', 'RETIRED']
    effective_from: datetime | None = None
    effective_until: datetime | None = None

TABLES = {
    'approvals': ('gov_approval_requests', 'approval_request_id', 'status', 'mission_id'),
    'scopes': ('gov_scope_contracts', 'scope_contract_id', 'status', 'mission_id'),
    'decisions': ('gov_policy_decisions', 'decision_id', 'decision', 'mission_id'),
    'policies': ('gov_policy_sets', 'policy_set_id', 'status', None),
    'audit': ('gov_audit_log', 'audit_id', 'event_type', 'mission_id'),
    'emergency-history': ('gov_emergency_actions', 'action_id', 'action_type', None),
}

def decode(row):
    row = dict(row)
    for key in list(row):
        if key.endswith('_json'):
            try: row[key[:-5]] = json.loads(row.pop(key) or 'null')
            except (ValueError, TypeError): row[key[:-5]] = None
    return row


def create_router(get_service):
    router = APIRouter(prefix='/api/governance/console', dependencies=[Depends(require('read'))])

    @router.get('/me')
    def me(p=Depends(require('read'))):
        return {'principal_id': p.principal_id, 'roles': sorted(p.roles), 'capabilities': capabilities(p)}

    @router.get('/overview')
    def overview():
        db = get_service().repo.db
        row = db.fetch_one("""SELECT
          (SELECT COUNT(*) FROM gov_approval_requests WHERE status='PENDING' AND expires_at>UTC_TIMESTAMP()) AS pending_approvals,
          (SELECT COUNT(*) FROM gov_scope_contracts WHERE status='ACTIVE' AND (valid_from IS NULL OR valid_from<=UTC_TIMESTAMP()) AND (valid_until IS NULL OR valid_until>UTC_TIMESTAMP())) AS active_scopes,
          (SELECT COUNT(*) FROM gov_scope_contracts WHERE status='ACTIVE' AND valid_until BETWEEN UTC_TIMESTAMP() AND DATE_ADD(UTC_TIMESTAMP(), INTERVAL 24 HOUR)) AS expiring_scopes,
          (SELECT COUNT(*) FROM gov_event_outbox WHERE delivery_status='FAILED') AS failed_events""")
        return {'counts': row, 'checked_at': datetime.now(timezone.utc).isoformat()}

    @router.get('/records/{kind}')
    def records(kind: str, q: str = Query('', max_length=255), mission_id: str = Query('', max_length=100),
                status: str = Query('', max_length=100), page: int = Query(1, ge=1, le=100000), limit: int = Query(25, ge=1, le=100)):
        if kind not in TABLES: raise HTTPException(404, 'Unknown record type')
        table, ident, state, mission = TABLES[kind]
        clauses, params = [], {'limit': limit, 'offset': (page-1)*limit}
        if q:
            params['q'] = '%' + q + '%'
            clauses.append(f"({ident} LIKE %(q)s" + (f" OR {mission} LIKE %(q)s" if mission else '') + ')')
        if mission_id and mission:
            clauses.append(f'{mission}=%(mission)s'); params['mission'] = mission_id
        if status:
            params['status'] = status
            if kind == 'approvals' and status in ('PENDING', 'EXPIRED'):
                clauses.append("(status='PENDING' AND expires_at>UTC_TIMESTAMP())" if status == 'PENDING' else "(status='EXPIRED' OR (status='PENDING' AND (expires_at IS NULL OR expires_at<=UTC_TIMESTAMP())))")
            elif kind == 'scopes' and status in ('ACTIVE', 'EXPIRED'):
                clauses.append("(status='ACTIVE' AND (valid_from IS NULL OR valid_from<=UTC_TIMESTAMP()) AND (valid_until IS NULL OR valid_until>UTC_TIMESTAMP()))" if status == 'ACTIVE' else "(status='EXPIRED' OR (status='ACTIVE' AND valid_until<=UTC_TIMESTAMP()))")
            else: clauses.append(f'{state}=%(status)s')
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        db = get_service().repo.db
        total = db.fetch_one(f'SELECT COUNT(*) AS n FROM {table}{where}', params)['n']
        extra = ", CASE WHEN status='PENDING' AND (expires_at IS NULL OR expires_at<=UTC_TIMESTAMP()) THEN 'EXPIRED' ELSE status END AS effective_status" if kind == 'approvals' else ''
        if kind == 'scopes':
            extra = ", CASE WHEN status='ACTIVE' AND valid_until<=UTC_TIMESTAMP() THEN 'EXPIRED' WHEN status='ACTIVE' AND valid_from>UTC_TIMESTAMP() THEN 'NOT_YET_VALID' ELSE status END AS effective_status"
        elif kind == 'decisions':
            extra = ", CASE WHEN decision_status='ACTIVE' AND valid_until<=UTC_TIMESTAMP() THEN 'EXPIRED' ELSE decision_status END AS effective_status"
        rows = db.fetch_all(f'SELECT *{extra} FROM {table}{where} ORDER BY id DESC LIMIT %(limit)s OFFSET %(offset)s', params)
        return {'items': [decode(r) for r in rows], 'total': total, 'page': page, 'limit': limit}

    @router.get('/approval/{ident}')
    def approval_detail(ident: str):
        s = get_service(); a = s.repo.get_approval_request(ident)
        if not a: raise HTTPException(404, 'Approval not found')
        request = s.repo.get_authorization_request(a['authorization_request_id'])
        risks = s.repo.db.fetch_all('SELECT * FROM gov_risk_assessments WHERE request_id=%(id)s ORDER BY id DESC LIMIT 1', {'id': a['authorization_request_id']})
        return {'approval': a, 'request': request, 'risk': [decode(r) for r in risks],
                'scope': s.repo.get_scope_contract(request['scope_contract_id']) if request and request.get('scope_contract_id') else None}

    @router.get('/policy/{ident}')
    def policy_detail(ident: str):
        s = get_service(); row = s.repo.get_policy_set(ident)
        if not row: raise HTTPException(404, 'Policy not found')
        return {'policy': row, 'rules': [decode(r) for r in s.repo.db.fetch_all('SELECT * FROM gov_policy_rules WHERE policy_set_id=%(id)s ORDER BY priority,id', {'id': ident})],
                'obligations': [decode(r) for r in s.repo.db.fetch_all('SELECT * FROM gov_compliance_obligations WHERE policy_set_id=%(id)s ORDER BY id', {'id': ident})],
                'rule_enforcement': 'Action permissions are enforced by scope action_constraints and the deterministic gate. Stored policy rules are inventory, not an executable rule editor.'}

    @router.get('/scopes/{ident}/delegation-readiness')
    def delegation_readiness(ident: str):
        # Authenticated read-only preflight; it does NOT create ALLOW decisions.
        from .delegation_preflight import inspect_delegation_scope
        try:
            return inspect_delegation_scope(get_service(), ident)
        except LookupError:
            raise HTTPException(404, 'Scope contract not found')

    @router.post('/scopes')
    def write_scope(body: ScopeWrite, p=Depends(require('scope'))):
        s = get_service(); contract = body.contract
        if not body.reason.strip(): raise HTTPException(422, 'Reason required')
        if not contract.mission_id.strip() or not contract.name.strip(): raise HTTPException(422, 'Mission and name required')
        if contract.valid_until and _aware_utc(contract.valid_until) <= (_aware_utc(contract.valid_from) or datetime.now(timezone.utc)):
            raise HTTPException(422, 'Validity end must be after start')
        keys = [(c.action_class, c.action_name) for c in contract.action_constraints]
        if len(keys) != len(set(keys)): raise HTTPException(422, 'Duplicate action class/name constraints')
        if len(contract.targets)>500 or len(contract.sources)>500 or len(keys)>200:
            raise HTTPException(422, 'Scope too large')
        if any(not t.target_value.strip() for t in contract.targets) or any(not x.source_id.strip() for x in contract.sources):
            raise HTTPException(422, 'Target/source values must not be empty')
        # All related scope/audit/outbox writes commit together. Lock predecessor
        # to serialize concurrent revisions; immutable old content is retained.
        with s.repo.db.connect():
            version = 1
            metadata = dict(contract.metadata)
            previous_metadata = None
            for key in ('supersedes_scope_id', 'revision_reason', 'revision_actor'): metadata.pop(key, None)
            if body.previous_id:
                old = s.repo.db.fetch_one('SELECT * FROM gov_scope_contracts WHERE scope_contract_id=%(id)s FOR UPDATE', {'id': body.previous_id})
                if not old: raise HTTPException(404, 'Previous scope not found')
                if old['status'] != 'ACTIVE' or old['version'] != body.expected_version: raise HTTPException(409, 'Scope changed; refresh before revising')
                if old['mission_id'] != contract.mission_id: raise HTTPException(422, 'Revision must retain mission identity')
                version = old['version'] + 1
                previous_metadata = old.get('metadata') or json.loads(old.get('metadata_json') or '{}')
                metadata['supersedes_scope_id'] = body.previous_id
            metadata.update(revision_reason=body.reason.strip(), revision_actor=p.principal_id)
            contract = contract.model_copy(update={'created_by': p.principal_id, 'approved_by': p.principal_id, 'metadata': metadata})
            try:
                from .workflow_profile import default_console_profile
                profile = body.workflow_profile
                if profile == 'AUTO':
                    profile = default_console_profile(
                        [t.model_dump(mode='json') for t in contract.targets],
                        contract.action_constraints, previous_metadata)
                new = s.create_scope_contract(
                    contract,
                    revision_version=version,
                    auto_recon_task_delegation_profile=body.apply_auto_recon_task_delegation_profile,
                    workflow_profile=profile,
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            if body.previous_id:
                s.repo.db.execute("UPDATE gov_scope_contracts SET status='REVOKED',updated_at=UTC_TIMESTAMP() WHERE scope_contract_id=%(id)s", {'id': body.previous_id})
                s.events.publish('SCOPE_CHANGED', mission_id=contract.mission_id, payload={'superseded_scope_id': body.previous_id, 'scope_contract_id': new['scope_contract_id'], 'scope_version': version})
            return {'scope_contract': new}

    @router.post('/scopes/{ident}/revoke')
    def revoke_scope(ident: str, body: Change, p=Depends(require('scope'))):
        s = get_service()
        with s.repo.db.connect():
            old = s.repo.db.fetch_one('SELECT * FROM gov_scope_contracts WHERE scope_contract_id=%(id)s FOR UPDATE', {'id': ident})
            if not old: raise HTTPException(404, 'Scope not found')
            if old['version'] != body.expected_version or old['status'] != 'ACTIVE': raise HTTPException(409, 'Scope changed')
            s.repo.db.execute("UPDATE gov_scope_contracts SET status='REVOKED',updated_at=UTC_TIMESTAMP() WHERE scope_contract_id=%(id)s", {'id': ident})
            s.audit.record('SCOPE_REVOKED', actor_id=p.principal_id, mission_id=old['mission_id'], subject_type='SCOPE_CONTRACT', subject_id=ident, payload={'reason': body.reason, 'version': old['version']})
            s.events.publish('SCOPE_CHANGED', mission_id=old['mission_id'], payload={'scope_contract_id': ident, 'status': 'REVOKED'})
        return {'status': 'REVOKED'}

    @router.post('/policies/{ident}')
    def change_policy(ident: str, body: PolicyChange, p=Depends(require('policy'))):
        s = get_service()
        def utc(x): return x.astimezone(timezone.utc).replace(tzinfo=None) if x and x.tzinfo else x
        start, end = utc(body.effective_from), utc(body.effective_until)
        if start and end and end <= start: raise HTTPException(422, 'Invalid validity interval')
        with s.repo.db.connect():
            old = s.repo.db.fetch_one('SELECT * FROM gov_policy_sets WHERE policy_set_id=%(id)s FOR UPDATE', {'id': ident})
            if not old: raise HTTPException(404, 'Policy not found')
            if old['version'] != body.expected_version: raise HTTPException(409, 'Policy changed; refresh')
            s.repo.db.execute('UPDATE gov_policy_sets SET name=%(name)s,description=%(description)s,status=%(status)s,effective_from=%(start)s,effective_until=%(end)s,version=version+1,updated_at=UTC_TIMESTAMP() WHERE policy_set_id=%(id)s', {'id': ident, 'name': body.name, 'description': body.description, 'status': body.status, 'start': start, 'end': end})
            new = s.repo.get_policy_set(ident)
            s.audit.record('POLICY_UPDATED', actor_id=p.principal_id, subject_type='POLICY_SET', subject_id=ident, payload={'before': old, 'after': new, 'reason': body.reason})
            for mission in s.repo.db.fetch_all("SELECT DISTINCT mission_id FROM gov_scope_contracts WHERE policy_set_id=%(id)s AND status='ACTIVE'", {'id': ident}):
                s.events.publish('POLICY_CHANGED', mission_id=mission['mission_id'], payload={'policy_set_id': ident, 'policy_version': new['version']})
        return {'policy': new}
    return router
