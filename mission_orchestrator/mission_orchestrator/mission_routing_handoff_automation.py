"""Replay-safe Mission planning -> routing -> governed Pentest handoff worker.

This worker creates only control-plane artifacts. It never dispatches a task,
starts a Pentest orchestration, authorizes target activity, or performs target
I/O. Pentest task materialization is attempted only when an authoritative GSS
TARGET_RECON ALLOW decision and a valid CTI PIP already exist.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Mapping

LOG = logging.getLogger(__name__)
ACTOR = "mission-auto-routing-handoff"


def _key(mission_id: str, task_id: str, step: str) -> str:
    digest = hashlib.sha256(f"{mission_id}:{task_id}:{step}".encode()).hexdigest()[:32]
    return f"auto-rh-{digest}-{step}"


def _version(service, mission_id: str) -> tuple[dict, dict]:
    state = service.repository.get_state(mission_id)
    vector = service.get_mission_version_vector(mission_id)
    if state is None or not vector.get("version_sha256"):
        raise ValueError("Mission lifecycle/version vector is unavailable")
    return state, vector


def _base(service, mission_id: str, task_id: str, step: str) -> dict:
    state, vector = _version(service, mission_id)
    return {
        "idempotency_key": _key(mission_id, task_id, step),
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "created_by": ACTOR,
        "reason": "Replay-safe autonomous routing of the validated Mission plan",
        "metadata": {"automation": "MISSION_ROUTING_HANDOFF_V1", "task_id": task_id},
    }


def find_target_recon_decision(snapshot: Mapping[str, Any], mission_id: str,
                               target: Mapping[str, Any], *,
                               scope_contract_id: str | None = None,
                               scope_version: int | None = None) -> dict | None:
    """Return a real, exact-scope GSS ALLOW decision, never a caller assertion."""
    if snapshot.get("authority") != "aptsGSS" or snapshot.get("mission_id") != mission_id:
        return None
    requests = {r.get("request_id"): r for r in snapshot.get("authorization_requests", [])
                if isinstance(r, dict)}
    matches = []
    for decision in snapshot.get("policy_decisions", []):
        if not isinstance(decision, dict) or decision.get("decision") != "ALLOW":
            continue
        if (scope_contract_id is not None
                and decision.get("scope_contract_id") != scope_contract_id):
            continue
        if (scope_version is not None
                and decision.get("scope_version") != scope_version):
            continue
        request = requests.get(decision.get("request_id"))
        if not request:
            continue
        if (request.get("mission_id") == mission_id
                and request.get("subject_component") == "PENTEST-SUB01"
                and request.get("action_class") == "TARGET_RECON"
                and request.get("resource_type") == target.get("target_type")
                and request.get("resource_value") == target.get("target_value")
                and decision.get("decision_hash")
                and decision.get("policy_version")):
            matches.append(decision)
    return matches[0] if len(matches) == 1 else None


def _activate_plan(service, mission_id: str) -> dict | None:
    active = service.repository.get_active_plan_version(mission_id)
    if active:
        return active
    validation = service.get_plan_validation(mission_id)
    if validation.get("validation_status") != "VALIDATED_FEASIBLE" or not validation.get("feasible"):
        return None
    state, vector = _version(service, mission_id)
    request = {
        "idempotency_key": "auto-rh-" + hashlib.sha256((mission_id + ":activate").encode()).hexdigest()[:32],
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "expected_plan_validation_id": validation["plan_validation_id"],
        "expected_plan_validation_sha256": validation["canonical_sha256"],
        "created_by": ACTOR,
        "reason": "Activate the feasible canonical Plan for governed task routing",
        "metadata": {"automation": "MISSION_ROUTING_HANDOFF_V1"},
    }
    service.activate_initial_plan_version(mission_id, request)
    return service.repository.get_active_plan_version(mission_id)


def _readiness(service, mission_id: str, active: dict) -> dict:
    existing = service.repository.get_task_readiness_projection_for_plan_version(
        mission_id, int(active["plan_version"]))
    if existing:
        return service.get_active_task_readiness_projection(mission_id)
    body = _base(service, mission_id, "plan", "readiness")
    body.update({
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]),
        "expected_active_plan_sha256": active["canonical_sha256"],
    })
    return service.create_task_readiness_projection(mission_id, body)


def _routing_for_task(service, mission_id: str, active: dict,
                      readiness: dict, task: dict) -> dict:
    task_id = task["planned_task_id"]
    repo = service.repository
    routing = repo.get_task_routing_intent_for_planned_task(
        mission_id, int(active["plan_version"]), task_id)
    if routing:
        routing = service.get_task_routing_intent(mission_id, routing["routing_intent_id"])
    else:
        body = _base(service, mission_id, task_id, "intent")
        body.update({
            "expected_active_plan_version_record_id": active["plan_version_record_id"],
            "expected_active_plan_version": int(active["plan_version"]),
            "expected_active_plan_sha256": active["canonical_sha256"],
            "expected_task_readiness_projection_id": readiness["projection_id"],
            "expected_task_readiness_projection_sha256": readiness["canonical_sha256"],
            "planned_task_id": task_id,
        })
        routing = service.create_task_routing_intent(mission_id, body)

    gate = repo.get_task_routing_eligibility_for_intent(mission_id, routing["routing_intent_id"])
    if gate:
        gate = service.get_task_routing_eligibility(mission_id, gate["eligibility_gate_id"])
    else:
        body = _base(service, mission_id, task_id, "eligibility")
        body.update({
            "expected_active_plan_version_record_id": active["plan_version_record_id"],
            "expected_active_plan_version": int(active["plan_version"]),
            "expected_active_plan_sha256": active["canonical_sha256"],
            "expected_task_readiness_projection_id": readiness["projection_id"],
            "expected_task_readiness_projection_sha256": readiness["canonical_sha256"],
            "expected_routing_intent_id": routing["routing_intent_id"],
            "expected_routing_intent_sha256": routing["canonical_sha256"],
            "planned_task_id": task_id,
        })
        gate = service.create_task_routing_eligibility_gate(mission_id, body)

    route = repo.get_task_route_decision_for_eligibility_gate(mission_id, gate["eligibility_gate_id"])
    if route:
        route = service.get_task_route_selection_decision(mission_id, route["route_decision_id"])
    else:
        body = _base(service, mission_id, task_id, "route")
        body.update({
            "expected_active_plan_version_record_id": active["plan_version_record_id"],
            "expected_active_plan_version": int(active["plan_version"]),
            "expected_active_plan_sha256": active["canonical_sha256"],
            "expected_task_readiness_projection_id": readiness["projection_id"],
            "expected_task_readiness_projection_sha256": readiness["canonical_sha256"],
            "expected_routing_intent_id": routing["routing_intent_id"],
            "expected_routing_intent_sha256": routing["canonical_sha256"],
            "expected_eligibility_gate_id": gate["eligibility_gate_id"],
            "expected_eligibility_gate_sha256": gate["canonical_sha256"],
            "planned_task_id": task_id,
        })
        route = service.create_task_route_selection_decision(mission_id, body)
    return route


def _request_target_recon_authorization(service, mission_id: str, received: dict) -> dict:
    """Request exact-target GSS authorization; never infer or grant an ALLOW.

    The current governance binding and canonical Mission scope are checked by
    authorize_mission_capability. GSS remains the sole decision authority.
    """
    envelope = (received or {}).get("envelope", {})
    identity = envelope.get("identity", {})
    work = envelope.get("work_context", {})
    targets = (work.get("scope") or {}).get("targets", [])
    task_id = identity.get("planned_task_id")
    if (identity.get("mission_id") != mission_id or not isinstance(task_id, str)
            or len(targets) != 1 or not isinstance(targets[0], dict)):
        return {"status": "BLOCKED", "reason_code": "EXACT_MISSION_TASK_TARGET_BINDING_REQUIRED"}
    target = targets[0]
    if target.get("target_type") != "URL" or not isinstance(target.get("target_value"), str):
        return {"status": "BLOCKED", "reason_code": "WPT_FINGERPRINTING_REQUIRES_EXACT_URL_TARGET"}
    try:
        current_binding = service.repository.get_current_governance_binding(mission_id)
        if not isinstance(current_binding, dict):
            return {"status": "BLOCKED", "reason_code": "CURRENT_GOVERNANCE_BINDING_REQUIRED"}
        if not service._binding_is_current_for_scope(current_binding):
            return {"status": "BLOCKED", "reason_code": "CURRENT_GOVERNANCE_BINDING_STALE"}
        binding_scope_id = current_binding.get("governance_scope_contract_id")
        binding_scope_version = current_binding.get("governance_scope_version")
        binding_version = current_binding.get("binding_version")
        if (not isinstance(binding_scope_id, str) or not binding_scope_id
                or type(binding_scope_version) is not int or type(binding_version) is not int):
            return {"status": "BLOCKED", "reason_code": "CURRENT_GOVERNANCE_BINDING_INCOMPLETE"}
        scope = service.repository.get_current_scope_contract(mission_id)
        if scope is None:
            return {"status": "BLOCKED", "reason_code": "CANONICAL_MISSION_SCOPE_REQUIRED"}
        from .governance_binding import resource_in_canonical_scope
        in_scope, reason = resource_in_canonical_scope(scope["contract"], target["target_value"])
        if not in_scope:
            return {"status": "BLOCKED", "reason_code": "TARGET_OUTSIDE_CURRENT_MISSION_SCOPE",
                    "detail": str(reason)[:240]}
        source_key = str((work.get("metadata") or {}).get("recon_target_key") or "")
        source_sha = str((work.get("metadata") or {}).get("recon_target_sha256") or "")
        # A GSS authorization is scoped to the exact Mission governance-binding
        # version. Reuse across binding renewal would replay a decision for an
        # obsolete GSS scope and fail Stage 4.3 lineage validation.
        seed = hashlib.sha256((mission_id + "\0" + task_id + "\0" +
            target["target_value"] + "\0" + source_key + "\0" + source_sha + "\0" +
            str(binding_version) + "\0" + binding_scope_id + "\0" +
            str(binding_scope_version)).encode()).hexdigest()[:40]
        result = service.authorize_mission_capability(mission_id, {
            "idempotency_key": "auto-wpt-target-recon-" + seed,
            "capability_id": "web_technology_fingerprinting",
            "resource_type": "URL",
            "resource_value": target["target_value"],
            "context": {
                "automation": "MISSION_AUTONOMOUS_WPT_TARGET_RECON_V1",
                "planned_task_id": task_id,
                "pentest_handoff_id": received.get("handoff_id"),
                "recon_target_key": source_key,
                "recon_target_sha256": source_sha,
                "execution_profile": "wpt.fingerprinting.v1",
                "max_requests": 6, "allowed_methods": ["GET"],
                "state_changing_requests": False,
                "mission_governance_binding_version": binding_version,
                "governance_scope_contract_id": binding_scope_id,
                "governance_scope_version": binding_scope_version,
                "authorization_purpose": "GOVERNED_WPT_FINGERPRINTING",
            },
            "evidence_refs": [
                "mission://" + mission_id + "/task-delegations/" + str(received.get("handoff_id") or "unknown"),
                "mission://" + mission_id + "/planned-tasks/" + task_id,
            ],
            "requested_by": ACTOR,
            "metadata": {"target_io_performed": False, "dispatch_performed": False},
        })
        binding = result.get("authorization_binding") or {}
        decision = binding.get("governance_decision") or {}
        return {"status": "REQUESTED", "decision": decision.get("decision"),
                "decision_id": decision.get("policy_decision_id"),
                "authorization_binding_id": result.get("authorization_binding_id"),
                "requires_human_approval": result.get("requires_human_approval"),
                "execution_authorized": False, "target_io_performed": False}
    except Exception as exc:
        LOG.info("Exact-target GSS authorization request deferred for %s: %s", mission_id, type(exc).__name__)
        return {"status": "DEFERRED", "reason_code": type(exc).__name__,
                "execution_authorized": False, "target_io_performed": False}


def _stage43_reference(service, mission_id: str, received: dict) -> dict | None:
    envelope = service.get_envelope(mission_id)["envelope"]
    pip_id = envelope.get("bindings", {}).get("pip", {}).get("pip_id")
    targets = received.get("envelope", {}).get("work_context", {}).get("scope", {}).get("targets", [])
    if not isinstance(pip_id, str) or len(targets) != 1:
        return None
    try:
        snapshot = service.governance_client.mission_correlation_snapshot(mission_id)
    except Exception:
        return None
    binding = service.repository.get_current_governance_binding(mission_id)
    if not isinstance(binding, dict) or not service._binding_is_current_for_scope(binding):
        return None
    decision = find_target_recon_decision(
        snapshot, mission_id, targets[0],
        scope_contract_id=binding.get("governance_scope_contract_id"),
        scope_version=binding.get("governance_scope_version"))
    if not decision:
        return None
    return {"pip_id": pip_id, "policy_decision_id": decision["decision_id"]}


def _start_local_orchestration(mission_id: str, planned_task_id: str,
                               handoff_id: str, task_result: dict) -> dict:
    """Create/read back the Stage 5.1 orchestration for a received task.

    Stage 4.3 materializes a scope/PIP/GSS-bound task. This continuation only
    creates the durable local planning graph; Stage 5.1 cannot execute agents,
    authorize tools, or perform target I/O. A deterministic request keeps the
    operation replay-safe across Mission worker restarts.
    """
    from urllib.parse import quote
    from .pentest_handoff import _pentest_task_api

    record = task_result.get("record") if isinstance(task_result, dict) else None
    if not isinstance(record, dict):
        raise ValueError("PENTEST_TASK_MATERIALIZATION_READBACK_MISSING")
    pentest_task_id = record.get("pentest_task_id")
    if (record.get("mission_id") != mission_id
            or record.get("upstream_task_id") != planned_task_id
            or not isinstance(pentest_task_id, str)
            or not pentest_task_id.startswith("pentest-task-")):
        raise ValueError("PENTEST_TASK_MATERIALIZATION_BINDING_MISMATCH")

    seed = hashlib.sha256((mission_id + "\0" + planned_task_id + "\0" + pentest_task_id).encode()).hexdigest()[:40]
    pentest_url = (os.environ.get("MISSION_PENTEST_BASE_URL") or "http://127.0.0.1:8790").rstrip("/")
    task_path = "/api/pentest/tasks/" + quote(pentest_task_id, safe="")
    existing_response = _pentest_task_api(pentest_url, "GET", task_path + "/agentic-orchestration")
    if existing_response is None:
        payload = {
            "schema_version": "apts-stage5.1-agentic-orchestrator-start-request-v1",
            "request_id": "paostart-auto-" + seed,
            "idempotency_key": "idem-paostart-auto-" + seed,
            "actor": "MISSION_AUTO_ROUTING_HANDOFF",
            "strategy": "CANONICAL_STAGE5_SPECIALIST_PIPELINE",
            "metadata": {
                "automation": "MISSION_ROUTING_HANDOFF_V1",
                "mission_id": mission_id,
                "upstream_task_id": planned_task_id,
                "handoff_id": handoff_id,
                "execution_authorized": False,
                "specialist_execution_started": False,
                "target_io_performed": False,
            },
        }
        started = _pentest_task_api(
            pentest_url, "POST", task_path + "/agentic-orchestration/start", payload)
        if started.get("status") == "conflict":
            existing_response = _pentest_task_api(
                pentest_url, "GET", task_path + "/agentic-orchestration")
            if existing_response is None:
                raise ValueError("PENTEST_ORCHESTRATION_CONFLICT_NOT_READABLE")
            orchestration = existing_response.get("orchestration")
        else:
            orchestration = started.get("orchestration")
    else:
        orchestration = existing_response.get("orchestration")

    if (not isinstance(orchestration, dict)
            or orchestration.get("mission_id") != mission_id
            or orchestration.get("upstream_task_id") != planned_task_id
            or orchestration.get("pentest_task_id") != pentest_task_id
            or orchestration.get("orchestration_status") != "ACTIVE"):
        raise ValueError("PENTEST_ORCHESTRATION_DURABLE_READBACK_INVALID")
    return {
        "status": "ACTIVE",
        "orchestration_id": orchestration["orchestration_id"],
        "pentest_task_id": pentest_task_id,
        "upstream_task_id": planned_task_id,
        "mission_id": mission_id,
        "execution_started": False,
        "tool_invocation_performed": False,
        "target_io_performed": False,
    }


def _gss_allows_automatic_recon_binding(service, mission_id: str) -> tuple[bool, str, str]:
    """Require a current, explicit, non-review GSS TARGET_RECON source rule.

    This check permits creation of a Mission capability binding only. It does
    not create a task delegation authorization or execution authorization.
    Those remain separate fresh GSS decisions.
    """
    from .canonical import sha256_hex
    from .gss_scope_sync import KEY, fetch

    scope_record = service.repository.get_current_scope_contract(mission_id)
    if not isinstance(scope_record, dict):
        return False, 'MISSION_SCOPE_MISSING', ''
    scope_contract = scope_record.get('contract') or {}
    metadata = (scope_contract.get('metadata') or {}).get(KEY)
    if not isinstance(metadata, dict) or not metadata.get('source_snapshot_sha256'):
        return False, 'AUTHORITATIVE_GSS_SCOPE_REQUIRED', ''
    try:
        source = fetch(service, mission_id)
    except Exception as exc:
        return False, 'GSS_SOURCE_UNAVAILABLE:' + type(exc).__name__, ''
    source_sha = sha256_hex(source)
    if source_sha != metadata.get('source_snapshot_sha256'):
        return False, 'GSS_SCOPE_CHANGED', ''

    allowed, reason = automatic_recon_binding_policy(scope_contract, source)
    return allowed, reason, source_sha


def automatic_recon_binding_policy(scope_contract: dict, source: dict) -> tuple[bool, str]:
    """Explain the same policy gate to routing and the non-executing WPT inbox."""
    # The source scope must explicitly permit this action class. DENY wins;
    # REVIEW or any approval requirement prevents autonomous binding.
    rules = [item for item in source.get('action_constraints', [])
             if isinstance(item, dict)
             and str(item.get('action_class') or '').strip().upper() == 'TARGET_RECON']
    allows = []
    for item in rules:
        effect = str(item.get('effect') or '').strip().upper()
        approval = item.get('requires_approval', effect == 'REVIEW')
        if isinstance(approval, str) and approval.strip().lower() in ('true', 'false'):
            approval = approval.strip().lower() == 'true'
        elif type(approval) is int and approval in (0, 1):
            approval = bool(approval)
        if effect == 'DENY':
            return False, 'GSS_TARGET_RECON_DENIED'
        if effect == 'REVIEW' or approval is True:
            return False, 'GSS_TARGET_RECON_REQUIRES_APPROVAL'
        if approval not in (False, None) or effect not in ('ALLOW', 'REVIEW', 'DENY'):
            return False, 'GSS_TARGET_RECON_RULE_INVALID'
        if effect == 'ALLOW':
            allows.append(item)
    if not allows:
        return False, 'GSS_TARGET_RECON_ALLOW_REQUIRED'

    roe = scope_contract.get('roe') or {}
    if ('TARGET_RECON' not in (roe.get('allowed_action_classes') or [])
            or 'TARGET_RECON' in (roe.get('prohibited_action_classes') or [])
            or 'TARGET_RECON' in (roe.get('human_approval_required_for') or [])):
        return False, 'MISSION_ROE_BLOCKS_AUTOMATIC_RECON_BINDING'
    if not (scope_contract.get('scope') or {}).get('targets'):
        return False, 'MISSION_SCOPE_HAS_NO_ALLOWED_TARGETS'
    return True, 'EXPLICIT_GSS_TARGET_RECON_ALLOW'


def _ensure_pentest_governance_binding(service, mission_id: str, route: dict) -> dict:
    """Create a narrow capability definition from current GSS scope, if absent.

    The binding is only a policy request boundary. GSS still decides the
    separate TASK_DELEGATION request, and Stage 6 still performs fresh
    authorization before any target I/O.
    """
    current = service.repository.get_current_governance_binding(mission_id)
    authorization = service.repository.get_delegation_authorization_for_route(
        mission_id, route['route_decision_id'])
    from .pentest_handoff import expired_task_delegation_decision
    expired_decision = expired_task_delegation_decision(service, mission_id, authorization)
    renewal_pending = bool(
        expired_decision and current is not None
        and int(current['binding_version']) <= int(authorization['governance_binding_version']))
    if (current is not None and service._binding_is_current_for_scope(current)
            and not renewal_pending):
        return {'status': 'CURRENT', 'binding_version': current.get('binding_version')}

    allowed, reason, source_sha = _gss_allows_automatic_recon_binding(service, mission_id)
    if not allowed:
        return {'status': 'WAITING_GSS_POLICY', 'reason_code': reason}

    scope_record = service.repository.get_current_scope_contract(mission_id)
    scope_sha = scope_record['canonical_sha256']
    binding_version = 0 if current is None else int(current['binding_version'])
    renewal_fingerprint = ''
    if renewal_pending:
        renewal_fingerprint = '\0expired-task-delegation\0' + str(
            expired_decision.get('decision_id') or authorization['policy_decision_id']) + '\0' + str(
            expired_decision.get('decision_hash') or authorization['policy_decision_hash'])
    seed = hashlib.sha256((mission_id + '\0' + source_sha + '\0' + scope_sha
                           + renewal_fingerprint).encode()).hexdigest()[:40]
    request = {
        'expected_binding_version': binding_version,
        'idempotency_key': 'auto-wpt-govbind-' + seed,
        'actor': 'mission-auto-wpt-governance-binding',
        'policy_set_id': 'default-policy',
        'name': 'Governed WPT fingerprinting and Pentest task handoff',
        'capabilities': [
            {
                'capability_id': 'pentest.recon',
                'subject_component': 'PENTEST-SUB01',
                'action_class': 'TARGET_RECON',
                'action_name': 'recon',
                'authorization_mode': 'REQUIRED',
                'resource_types': ['URL'],
                'max_risk_level': 'LOW',
                'requires_human_approval': False,
                'constraints': {'purpose': 'GOVERNED_PENTEST_TASK_HANDOFF'},
            },
            {
                'capability_id': 'web_technology_fingerprinting',
                'subject_component': 'PENTEST-SUB01',
                'action_class': 'TARGET_RECON',
                'action_name': 'web_technology_fingerprinting',
                'authorization_mode': 'REQUIRED',
                'resource_types': ['URL'],
                'max_risk_level': 'LOW',
                'requires_human_approval': False,
                'constraints': {
                    'execution_profile': 'wpt.fingerprinting.v1',
                    'max_requests': 6,
                    'allowed_methods': ['GET'],
                    'state_changing_requests': False,
                },
            },
        ],
        'reason': 'Bind only low-risk Recon and bounded WPT fingerprinting permitted by the current explicit GSS scope',
        'metadata': {
            'automation': 'MISSION_AUTONOMOUS_WPT_GOVERNANCE_BINDING_V2',
            'gss_source_snapshot_sha256': source_sha,
            'mission_scope_sha256': scope_sha,
            'renewal_reason': 'EXPIRED_TASK_DELEGATION_ALLOW' if renewal_pending else 'CURRENT_SCOPE_BINDING',
            'renewed_policy_decision_id': (authorization.get('policy_decision_id')
                                           if renewal_pending else None),
            'renewed_policy_decision_hash': (authorization.get('policy_decision_hash')
                                             if renewal_pending else None),
            'execution_authorized': False,
            'task_delegation_authorized': False,
            'target_io_performed': False,
        },
    }
    # Add the follow-up capability only when the source explicitly permits its
    # exact technique. Existing fingerprint-only scopes remain fingerprint-only.
    rules = ((scope_record['contract'].get('metadata') or {}).get('gss_scope_sync') or {}).get('action_constraints') or []
    execution_rules = [r for r in rules if r.get('action_class') == 'TARGET_RECON'
        and r.get('action_name') in ('AUTHORIZE_TARGET_EXECUTION','*')]
    technique = 'BOUNDED_WEB_SURFACE_ENUMERATION'
    if (execution_rules and all(r.get('effect') == 'ALLOW' and not r.get('requires_approval')
            and technique in (r.get('constraints') or {}).get('allowed_techniques', [])
            and technique not in (r.get('constraints') or {}).get('prohibited_techniques', [])
            and (r.get('constraints') or {}).get('execution_profile') in (None,'wpt.bounded-enumeration.v1')
            and 'GET' in (r.get('constraints') or {}).get('allowed_methods',['GET'])
            for r in execution_rules)):
        request['capabilities'].append({
            'capability_id':'web_surface_enumeration','subject_component':'PENTEST-SUB01',
            'action_class':'TARGET_RECON','action_name':'web_surface_enumeration',
            'authorization_mode':'REQUIRED','resource_types':['URL'],'max_risk_level':'LOW',
            'requires_human_approval':False,'constraints':{'execution_profile':'wpt.bounded-enumeration.v1',
                'max_requests':5,'allowed_methods':['GET'],'state_changing_requests':False}})
    # Add the governed validation capability only when the source scope explicitly
    # authorizes a safe, read-only VULNERABILITY_VALIDATION execution technique for
    # the target. Recon-only scopes never gain validation authority. This never
    # authorizes exploitation, credential use, or any state-changing action.
    _SAFE_VALIDATION = ('HTTP_HEADER_INSPECTION', 'SAFE_VERSION_CONFIGURATION_CONFIRMATION', 'HTTP_RESPONSE_METADATA')
    validation_rules = [r for r in rules if r.get('action_class') == 'VULNERABILITY_VALIDATION'
        and r.get('action_name') in ('AUTHORIZE_TARGET_EXECUTION', '*')]
    permitted_validation = [technique for technique in _SAFE_VALIDATION if validation_rules and all(
        r.get('effect') == 'ALLOW' and not r.get('requires_approval')
        and technique in (r.get('constraints') or {}).get('allowed_techniques', [])
        and technique not in (r.get('constraints') or {}).get('prohibited_techniques', [])
        for r in validation_rules)]
    if permitted_validation:
        request['capabilities'].append({
            'capability_id': 'pentest.validate', 'subject_component': 'PENTEST-SUB01',
            'action_class': 'VULNERABILITY_VALIDATION', 'action_name': 'validate',
            'authorization_mode': 'REQUIRED', 'resource_types': ['URL'], 'max_risk_level': 'MODERATE',
            'requires_human_approval': False, 'constraints': {
                'allowed_techniques': permitted_validation, 'allowed_methods': ['GET', 'HEAD'],
                'state_changing_requests': False, 'read_only': True}})
    result = service.put_mission_governance_binding(mission_id, request)
    return {'status': 'BOUND', 'binding_version': result.get('binding_version'),
            'governance_scope_contract_id': result.get('governance_scope_contract_id'),
            'execution_authorized': False, 'target_io_performed': False}


def _handoff(service, mission_id: str, route: dict) -> dict:
    from .pentest_handoff import handoff_to_pentest
    if (route.get("decision_status") != "ROUTE_SELECTED"
            or route.get("selected_subsystem") != "PENTEST"
            or route.get("selected_capability") != "pentest.recon"):
        return {"status": "no_pentest_route", "route_decision_id": route.get("route_decision_id")}
    binding = _ensure_pentest_governance_binding(service, mission_id, route)
    if binding.get('status') == 'WAITING_GSS_POLICY':
        return {'status': 'waiting_gss_policy', 'governance_binding': binding,
                'execution_authorized': False, 'target_io_performed': False}
    request = {"route_decision_id": route["route_decision_id"], "requested_by": ACTOR}
    result = handoff_to_pentest(service, mission_id, request)
    if not result.get("handoff_received"):
        return {"status": "waiting_gss_delegation_allow", **result}
    if result.get("stage43_materialized"):
        orchestration = _start_local_orchestration(
            mission_id, result["upstream_task_id"], result["handoff_id"], result["pentest_task"])
        return {"status": "orchestration_active", "orchestration": orchestration, **result}
    from pentest_subsystem.mission_handoff import PentestHandoffInbox
    received = PentestHandoffInbox().get(result["handoff_id"])
    target_authorization = _request_target_recon_authorization(service, mission_id, received or {})
    reference = _stage43_reference(service, mission_id, received or {})
    if not reference:
        return {"status": "waiting_cti_pip_or_gss_target_recon_allow",
                "target_recon_authorization": target_authorization, **result}
    result = handoff_to_pentest(service, mission_id, {**request, "stage43_cti": reference})
    if result.get("stage43_materialized"):
        orchestration = _start_local_orchestration(
            mission_id, result["upstream_task_id"], result["handoff_id"], result["pentest_task"])
        return {"status": "orchestration_active", "orchestration": orchestration, **result}
    return {"status": "waiting_cti_or_gss_validation", **result}


def process_mission(service, mission_id: str) -> dict:
    state = service.repository.get_state(mission_id)
    if not state or state.get("state") not in {"PLANNING", "REPLANNING"}:
        return {"status": "unchanged", "mission_id": mission_id,
                "state": None if not state else state.get("state")}
    active = _activate_plan(service, mission_id)
    if not active:
        return {"status": "waiting_feasible_plan", "mission_id": mission_id}
    readiness = _readiness(service, mission_id, active)
    ready = [item for item in readiness.get("task_readiness", [])
             if item.get("readiness_status") == "READY"
             and item.get("required_subsystem") == "PENTEST"]
    planned = service.list_planned_tasks(mission_id).get("planned_tasks", [])
    by_id = {item.get("planned_task_id"): item for item in planned}
    results = []
    for item in ready:
        task_id = item.get("planned_task_id")
        row = by_id.get(task_id)
        if not row or not isinstance(task_id, str):
            continue
        spec = (row.get("planned_task") or {}).get("specification") or {}
        if spec.get("required_capability") != "pentest.recon":
            continue
        route = _routing_for_task(service, mission_id, active, readiness, item)
        try:
            results.append(_handoff(service, mission_id, route))
        except Exception as exc:
            # Keep the worker alive and retry after upstream state/approval changes.
            LOG.warning("Governed Pentest handoff deferred for %s/%s: %s", mission_id, task_id, exc, exc_info=True)
            results.append({"status": "deferred_by_guard", "planned_task_id": task_id,
                            "reason": str(exc)[:500]})
    return {"status": "completed" if results else "no_ready_pentest_task",
            "mission_id": mission_id, "state": state.get("state"),
            "plan_version": active.get("plan_version"), "results": results,
            "execution_authorized": False, "dispatch_performed": False,
            "target_io_performed": False}


def sweep(service) -> None:
    """Retry routing and governed delivery for every planning/replanning Mission."""
    offset = 0
    ids = []
    for state_name in ("PLANNING", "REPLANNING"):
        offset = 0
        while True:
            page = service.list_missions(state=state_name, limit=100, offset=offset)
            ids.extend(row["mission_id"] for row in page.get("missions", []))
            offset += len(page.get("missions", []))
            if offset >= int(page.get("mission_count", 0)) or not page.get("missions"):
                break
    for mission_id in dict.fromkeys(ids):
        try:
            process_mission(service, mission_id)
        except Exception:
            LOG.exception("Autonomous routing/handoff deferred for %s", mission_id)
