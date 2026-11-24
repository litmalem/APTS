from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mission_orchestrator.errors import (
    MissionAuthorizationConflict,
    MissionAuthorizationFailClosed,
    MissionGovernanceBindingConflict,
    MissionGovernanceProtocolError,
    MissionGovernanceUnavailable,
)
from mission_orchestrator.governance_binding import verify_authorization_binding, verify_binding_contract
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class FakeGovernanceClient:
    base_url = "http://fake-governance:8770"

    def __init__(self):
        self.scopes = []
        self.requests = []
        self.decisions = []
        self.events = []
        self.create_calls = 0
        self.evaluate_calls = 0
        self.revalidation_calls = 0
        self.fail_revalidation = False
        self.fail_create_after_commit_once = False
        self.fail_evaluate_after_commit_once = False
        self.malformed_decision = False
        self.emergency_stop = False

    @staticmethod
    def _hash(value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(raw).hexdigest()

    def health(self):
        return {"status": "ok", "component_id": "GOV-PLANE"}

    def create_scope_contract(self, payload):
        self.create_calls += 1
        scope_id = f"scope-test-{self.create_calls}"
        row = {
            "id": self.create_calls,
            "scope_contract_id": scope_id,
            "mission_id": payload["mission_id"],
            "name": payload["name"],
            "status": "ACTIVE",
            "policy_set_id": payload["policy_set_id"],
            "version": 1,
            "valid_from": payload.get("valid_from"),
            "valid_until": payload.get("valid_until"),
            "created_by": payload["created_by"],
            "approved_by": payload.get("approved_by"),
            "metadata": dict(payload.get("metadata") or {}),
            "targets": list(payload.get("targets") or []),
            "sources": list(payload.get("sources") or []),
            "action_constraints": list(payload.get("action_constraints") or []),
        }
        row["contract_hash"] = self._hash(row)
        self.scopes.append(row)
        if self.fail_create_after_commit_once:
            self.fail_create_after_commit_once = False
            raise MissionGovernanceUnavailable("simulated response loss after scope commit")
        return dict(row)

    def get_scope_contract(self, scope_contract_id):
        for row in self.scopes:
            if row["scope_contract_id"] == scope_contract_id:
                return dict(row)
        raise MissionGovernanceProtocolError("scope not found")

    def evaluate_authorization(self, payload):
        self.evaluate_calls += 1
        request_id = f"greq-test-{self.evaluate_calls}"
        decision_id = f"gdec-test-{self.evaluate_calls}"
        request = {
            "id": self.evaluate_calls,
            "request_id": request_id,
            "mission_id": payload["mission_id"],
            "scope_contract_id": payload.get("scope_contract_id"),
            "subject_component": payload["subject_component"],
            "action_class": payload["action_class"],
            "action_name": payload["action_name"],
            "resource_type": payload["resource_type"],
            "resource_value": payload["resource_value"],
            "context": dict(payload.get("context") or {}),
            "evidence_refs": list(payload.get("evidence_refs") or []),
            "requested_by": payload.get("requested_by"),
        }
        self.requests.append(request)
        scope = self.get_scope_contract(payload["scope_contract_id"])
        decision_value = "DENY" if self.emergency_stop else "ALLOW"
        reasons = ["EMERGENCY_STOP_ACTIVE"] if self.emergency_stop else ["ACTION_CONSTRAINT_ALLOW", "IP_MATCH"]
        constraints = {}
        if payload["action_class"] == "TASK_DELEGATION":
            rule = next((c for c in scope["action_constraints"]
                         if c["action_class"] == "TASK_DELEGATION"
                         and c["action_name"] == payload["action_name"]
                         and c["effect"] == "ALLOW"), None)
            allowed = ((rule or {}).get("constraints") or {}).get("allowed_capabilities", [])
            resource_allowed = (
                isinstance(allowed, list) and payload["resource_value"] in allowed
                and payload["subject_component"] == "APTS-MO01"
                and payload["resource_type"] == "SUBSYSTEM_CAPABILITY"
                and payload.get("context", {}).get("authorization_purpose") == "PRE_DELEGATION_ONLY"
                and payload.get("context", {}).get("target_action_authority_requested") is False
            )
            if not self.emergency_stop and not resource_allowed:
                decision_value = "DENY"
                reasons = ["SUBSYSTEM_CAPABILITY_NOT_ALLOWLISTED"]
            constraints = {
                "allowed_capabilities": allowed if isinstance(allowed, list) else [],
                "delegation_scope": {
                    "action_class": "TASK_DELEGATION",
                    "action_name": payload["action_name"],
                    "subject_component": payload["subject_component"],
                    "resource_type": payload["resource_type"],
                    "resource_value": payload["resource_value"],
                    "authorization_purpose": payload["context"].get("authorization_purpose"),
                    "delegation_authorized": decision_value == "ALLOW",
                    "execution_authorized": False,
                    "target_actuation": False,
                },
            }
        body = {
            "id": self.evaluate_calls,
            "decision_id": decision_id,
            "request_id": request_id,
            "mission_id": payload["mission_id"],
            "decision": decision_value,
            "risk_score": 0.2,
            "risk_level": "LOW",
            "reason_codes": reasons,
            "constraints": constraints,
            "requires_human_approval": False,
            "approval_request_id": None,
            "valid_from": "2026-09-02T09:00:00Z",
            "valid_until": "2026-09-02T09:05:00Z",
            "policy_set_id": scope["policy_set_id"],
            "policy_version": 1,
            "scope_contract_id": scope["scope_contract_id"],
            "scope_version": scope["version"],
        }
        body["decision_hash"] = self._hash(body)
        body["decision_status"] = "ACTIVE"
        self.decisions.append(dict(body))
        event_id = f"gevent-test-{self.evaluate_calls}"
        self.events.append(
            {
                "event_id": event_id,
                "event_type": "POLICY_DECISION_ISSUED",
                "mission_id": payload["mission_id"],
                "payload": {**body, "governance_event_id": event_id},
            }
        )
        response = dict(body)
        response["governance_event_id"] = event_id
        if self.malformed_decision:
            response["scope_contract_id"] = "scope-wrong"
        if self.fail_evaluate_after_commit_once:
            self.fail_evaluate_after_commit_once = False
            raise MissionGovernanceUnavailable("simulated response loss after decision commit")
        return response

    def revalidate_policy_decision(self, payload):
        self.revalidation_calls += 1
        valid = not self.fail_revalidation
        return {
            "revalidation_id": f"greval-test-{self.revalidation_calls}",
            "status": "VALID" if valid else "INVALID",
            "valid": valid,
            "delegation_authorized": valid,
            "execution_authorized": False,
            "decision_hash": payload["decision_hash"],
            "decision_id": payload["decision_id"],
            "request_id": payload["request_id"],
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "checked_at": "2026-10-12T09:00:00Z",
            "reason_codes": ["POLICY_DECISION_STILL_VALID"] if valid else ["EMERGENCY_STOP_ACTIVE"],
        }

    def mission_correlation_snapshot(self, mission_id):
        return {
            "schema_version": "governance-correlation-snapshot-v1",
            "mission_id": mission_id,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "scope_contracts": [dict(row) for row in self.scopes if row["mission_id"] == mission_id],
            "authorization_requests": [dict(row) for row in self.requests if row["mission_id"] == mission_id],
            "policy_decisions": [dict(row) for row in self.decisions if row["mission_id"] == mission_id],
            "events": [dict(row) for row in self.events if row["mission_id"] == mission_id],
            "audit_records": [],
        }


def mission_payload(key="mission-314"):
    return {
        "idempotency_key": key,
        "source_system": "PYTEST",
        "created_by": "pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "lab"},
        "success_criteria": [{"metric": "done", "expected": True}],
        "budgets": {"time_seconds": 1800},
        "required_subsystems": ["CTI", "PENTEST"],
        "metadata": {"environment": "LAB"},
    }


def scope_payload(key="scope-314", expected=0, max_actions=20):
    return {
        "expected_contract_version": expected,
        "idempotency_key": key,
        "actor": "pytest",
        "scope": {
            "targets": [{"target_type": "CIDR", "target_value": "127.0.0.0/8", "environment": "LAB"}],
            "excluded_targets": [{"target_type": "IP", "target_value": "127.0.0.254", "environment": "LAB"}],
            "network_ranges": [],
            "domains": ["lab.example.test"],
            "services": [{"name": "https", "protocol": "TCP", "port": 443, "target_ref": "lab.example.test"}],
        },
        "roe": {
            "allowed_action_classes": ["TARGET_RECON", "VULNERABILITY_VALIDATION"],
            "prohibited_action_classes": ["DESTRUCTIVE_ACTION", "CREDENTIAL_USE"],
            "allowed_time_window": {"start_at": "2026-09-01T00:00:00Z", "end_at": "2030-09-03T00:00:00Z"},
            "maximum_concurrency": 2,
            "destructive_actions_allowed": False,
            "credential_usage_allowed": False,
            "persistence_allowed": False,
            "human_approval_required_for": ["VULNERABILITY_VALIDATION"],
        },
        "constraints": {
            "max_actions": max_actions,
            "max_duration": 1800,
            "risk_threshold": "MODERATE",
            "resource_budget": {"max_network_requests": 500},
            "data_handling_policy": {"classification": "INTERNAL", "retention_days": 7, "export_allowed": False},
        },
        "reason": "pytest scope",
        "metadata": {"environment": "LAB"},
    }


def binding_payload(key="bind-314", expected=0):
    return {
        "expected_binding_version": expected,
        "idempotency_key": key,
        "actor": "pytest",
        "policy_set_id": "default-policy",
        "name": "Stage 3.1.4 test governance scope",
        "capabilities": [
            {
                "capability_id": "pentest.recon",
                "subject_component": "PENTEST-A01",
                "action_class": "TARGET_RECON",
                "action_name": "recon",
                "authorization_mode": "REQUIRED",
                "resource_types": ["IP", "HOST", "DOMAIN"],
                "max_risk_level": "MODERATE",
                "requires_human_approval": False,
            },
            {
                "capability_id": "pentest.validate",
                "subject_component": "PENTEST-A02",
                "action_class": "VULNERABILITY_VALIDATION",
                "action_name": "validate",
                "authorization_mode": "REQUIRED",
                "resource_types": ["IP", "HOST", "DOMAIN"],
                "max_risk_level": "MODERATE",
                "requires_human_approval": True,
            },
        ],
        "reason": "bind exact canonical scope to authoritative Governance",
        "metadata": {"test": True},
    }


def auth_payload(key="auth-314", capability="pentest.recon", resource="127.0.0.1"):
    return {
        "idempotency_key": key,
        "capability_id": capability,
        "resource_type": "IP",
        "resource_value": resource,
        "context": {"risk_score": 0.2, "risk_level": "LOW"},
        "evidence_refs": ["evidence://pytest/recon"],
        "requested_by": "pytest",
        "metadata": {"test": True},
    }


def service(tmp_path: Path, fake=None):
    fake = fake or FakeGovernanceClient()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    return CanonicalMissionService(repo, governance_client=fake), fake


def provision(svc):
    mission_id = svc.create_mission(mission_payload())["canonical_identity"]["mission_id"]
    scope = svc.put_mission_scope_contract(mission_id, scope_payload())
    return mission_id, scope


def test_governance_binding_binds_exact_canonical_scope_and_capabilities(tmp_path):
    svc, fake = service(tmp_path)
    mission_id, scope = provision(svc)
    result = svc.put_mission_governance_binding(mission_id, binding_payload())

    assert result["status"] == "bound"
    assert result["binding_version"] == 1
    assert result["binding_current_for_scope"] is True
    assert result["mission_governance_binding_id"].startswith("mgbind-")
    binding = result["binding"]
    assert verify_binding_contract(binding)
    assert binding["canonical_scope_binding"]["mission_scope_snapshot_id"] == scope["snapshot_id"]
    assert binding["canonical_scope_binding"]["mission_scope_sha256"] == scope["canonical_sha256"]
    assert binding["governance_authority"]["authorization_authority"] == "aptsGSS"
    assert binding["governance_authority"]["authorization_authority_component"] == "GOV-PLANE"
    assert binding["semantics"]["binding_mode"] == "CAPABILITY_BASED"
    assert binding["semantics"]["default_effect"] == "DENY"
    assert binding["semantics"]["fail_closed"] is True
    assert binding["semantics"]["dispatch_enabled"] is False
    assert fake.create_calls == 1
    external = fake.scopes[0]
    assert any(c["action_class"] == "TARGET_RECON" and c["effect"] == "ALLOW" for c in external["action_constraints"])
    assert any(c["action_class"] == "VULNERABILITY_VALIDATION" and c["effect"] == "REVIEW" for c in external["action_constraints"])
    delegation = next(c for c in external["action_constraints"] if c["action_class"] == "TASK_DELEGATION")
    assert delegation["action_name"] == "delegate_planned_task"
    assert delegation["constraints"]["allowed_capabilities"] == ["PENTEST:pentest.recon"]
    assert delegation["constraints"]["execution_authorized"] is False
    assert delegation["constraints"]["target_actuation"] is False
    assert any(c["action_class"] == "DESTRUCTIVE_ACTION" and c["effect"] == "DENY" for c in external["action_constraints"])


def test_governance_binding_retry_is_idempotent_without_duplicate_external_scope(tmp_path):
    svc, fake = service(tmp_path)
    mission_id, _ = provision(svc)
    payload = binding_payload("same-bind")
    first = svc.put_mission_governance_binding(mission_id, payload)
    second = svc.put_mission_governance_binding(mission_id, payload)
    assert second["idempotent_replay"] is True
    assert second["binding_snapshot_id"] == first["binding_snapshot_id"]
    assert fake.create_calls == 1


def test_governance_binding_recovers_after_lost_external_response(tmp_path):
    fake = FakeGovernanceClient()
    fake.fail_create_after_commit_once = True
    svc, _ = service(tmp_path, fake)
    mission_id, _ = provision(svc)
    payload = binding_payload("recover-bind")
    with pytest.raises(MissionGovernanceUnavailable):
        svc.put_mission_governance_binding(mission_id, payload)
    assert fake.create_calls == 1
    recovered = svc.put_mission_governance_binding(mission_id, payload)
    assert recovered["binding_version"] == 1
    assert fake.create_calls == 1, "retry must recover the externally committed scope instead of duplicating it"


def test_capability_binding_cannot_expand_roe_or_bypass_hard_deny(tmp_path):
    svc, fake = service(tmp_path)
    mission_id, _ = provision(svc)
    bad = binding_payload("bad-cap")
    bad["capabilities"][0]["action_class"] = "CREDENTIAL_USE"
    with pytest.raises(Exception, match="not allowed by the current canonical RoE"):
        svc.put_mission_governance_binding(mission_id, bad)
    assert fake.create_calls == 0

    hard = binding_payload("hard-cap")
    hard["capabilities"][0]["action_class"] = "DESTRUCTIVE_ACTION"
    with pytest.raises(Exception, match="hard-denied"):
        svc.put_mission_governance_binding(mission_id, hard)
    assert fake.create_calls == 0


def test_human_approval_requirement_cannot_be_weakened(tmp_path):
    svc, fake = service(tmp_path)
    mission_id, _ = provision(svc)
    bad = binding_payload("bad-approval")
    bad["capabilities"][1]["requires_human_approval"] = False
    with pytest.raises(Exception, match="cannot weaken"):
        svc.put_mission_governance_binding(mission_id, bad)
    assert fake.create_calls == 0


def test_stale_binding_version_rejected_before_external_side_effect(tmp_path):
    svc, fake = service(tmp_path)
    mission_id, _ = provision(svc)
    svc.put_mission_governance_binding(mission_id, binding_payload("v1", 0))
    with pytest.raises(MissionGovernanceBindingConflict, match="expected_binding_version"):
        svc.put_mission_governance_binding(mission_id, binding_payload("stale", 0))
    assert fake.create_calls == 1


def test_scope_revision_marks_binding_stale_and_blocks_authorization(tmp_path):
    svc, fake = service(tmp_path)
    mission_id, _ = provision(svc)
    svc.put_mission_governance_binding(mission_id, binding_payload())
    revised = scope_payload("scope-v2", 1, 10)
    svc.put_mission_scope_contract(mission_id, revised)
    current = svc.get_mission_governance_binding(mission_id)
    assert current["binding_status"] == "STALE_SCOPE"
    with pytest.raises(MissionGovernanceBindingConflict, match="stale"):
        svc.authorize_mission_capability(mission_id, auth_payload())
    assert fake.evaluate_calls == 0


def test_unknown_capability_and_out_of_scope_are_default_denied_locally(tmp_path):
    svc, fake = service(tmp_path)
    mission_id, _ = provision(svc)
    svc.put_mission_governance_binding(mission_id, binding_payload())

    with pytest.raises(MissionAuthorizationFailClosed, match="unknown or unbound"):
        svc.authorize_mission_capability(mission_id, auth_payload("unknown", "pentest.not-bound"))
    with pytest.raises(MissionAuthorizationFailClosed, match="RESOURCE_EXPLICITLY_EXCLUDED"):
        svc.authorize_mission_capability(mission_id, auth_payload("excluded", resource="127.0.0.254"))
    with pytest.raises(MissionAuthorizationFailClosed, match="RESOURCE_OUT_OF_CANONICAL_SCOPE"):
        svc.authorize_mission_capability(mission_id, auth_payload("outside", resource="10.10.10.10"))
    assert fake.evaluate_calls == 0


def test_authoritative_allow_decision_is_bound_with_full_provenance_but_does_not_dispatch(tmp_path):
    svc, fake = service(tmp_path)
    mission_id, _ = provision(svc)
    gov = svc.put_mission_governance_binding(mission_id, binding_payload())
    result = svc.authorize_mission_capability(mission_id, auth_payload())

    assert result["authorization_granted"] is True
    assert result["execution_authorized"] is False
    binding = result["authorization_binding"]
    assert verify_authorization_binding(binding)
    assert binding["governance_status"] == "AUTHORIZED"
    assert binding["pre_dispatch_revalidation_required"] is True
    assert binding["dispatch_enabled"] is False
    prov = binding["decision_provenance"]
    assert prov["authorization_request_id"].startswith("greq-test-")
    assert prov["policy_decision_id"].startswith("gdec-test-")
    assert len(prov["policy_decision_hash"]) == 64
    assert prov["scope_contract_id"] == gov["binding"]["governance_authority"]["governance_scope_contract_id"]
    assert prov["scope_version"] == 1
    assert prov["policy_set_id"] == "default-policy"
    assert prov["policy_version"] == 1
    assert prov["authorization_authority"] == "aptsGSS"
    assert prov["authorization_authority_component"] == "GOV-PLANE"
    assert fake.evaluate_calls == 1


def test_authorization_retry_is_idempotent_without_second_governance_decision(tmp_path):
    svc, fake = service(tmp_path)
    mission_id, _ = provision(svc)
    svc.put_mission_governance_binding(mission_id, binding_payload())
    payload = auth_payload("same-auth")
    first = svc.authorize_mission_capability(mission_id, payload)
    second = svc.authorize_mission_capability(mission_id, payload)
    assert second["idempotent_replay"] is True
    assert second["authorization_binding_id"] == first["authorization_binding_id"]
    assert second["authorization_binding"]["decision_provenance"]["policy_decision_id"] == first["authorization_binding"]["decision_provenance"]["policy_decision_id"]
    assert fake.evaluate_calls == 1

    changed = auth_payload("same-auth", resource="127.0.0.2")
    with pytest.raises(MissionAuthorizationConflict):
        svc.authorize_mission_capability(mission_id, changed)
    assert fake.evaluate_calls == 1


def test_authorization_recovers_after_lost_policydecision_response(tmp_path):
    fake = FakeGovernanceClient()
    svc, _ = service(tmp_path, fake)
    mission_id, _ = provision(svc)
    svc.put_mission_governance_binding(mission_id, binding_payload())
    fake.fail_evaluate_after_commit_once = True
    payload = auth_payload("recover-auth")
    with pytest.raises(MissionGovernanceUnavailable):
        svc.authorize_mission_capability(mission_id, payload)
    assert fake.evaluate_calls == 1
    recovered = svc.authorize_mission_capability(mission_id, payload)
    assert recovered["authorization_granted"] is True
    assert fake.evaluate_calls == 1, "retry must recover the externally committed PolicyDecision"


def test_emergency_stop_deny_is_persisted_as_authoritative_decision_provenance(tmp_path):
    fake = FakeGovernanceClient()
    fake.emergency_stop = True
    svc, _ = service(tmp_path, fake)
    mission_id, _ = provision(svc)
    svc.put_mission_governance_binding(mission_id, binding_payload())
    result = svc.authorize_mission_capability(mission_id, auth_payload("emergency-deny"))
    assert result["authorization_granted"] is False
    binding = result["authorization_binding"]
    assert binding["governance_status"] == "DENIED"
    assert "EMERGENCY_STOP_ACTIVE" in binding["decision_provenance"]["reason_codes"]
    assert binding["execution_authorized"] is False


def test_malformed_governance_decision_fails_closed_and_is_not_persisted(tmp_path):
    fake = FakeGovernanceClient()
    fake.malformed_decision = True
    svc, _ = service(tmp_path, fake)
    mission_id, _ = provision(svc)
    svc.put_mission_governance_binding(mission_id, binding_payload())
    with pytest.raises(MissionGovernanceProtocolError, match="scope_contract_id mismatch"):
        svc.authorize_mission_capability(mission_id, auth_payload("malformed"))
    history = svc.get_mission_authorization_history(mission_id)
    assert history["authorization_binding_count"] == 0


def test_stage314_does_not_mutate_envelope_state_or_scope_snapshot(tmp_path):
    svc, _ = service(tmp_path)
    mission_id, scope = provision(svc)
    envelope_before = svc.get_envelope(mission_id)["envelope"]
    state_before = svc.get_mission_state(mission_id)["mission_state"]
    svc.put_mission_governance_binding(mission_id, binding_payload())
    svc.authorize_mission_capability(mission_id, auth_payload())
    assert svc.get_envelope(mission_id)["envelope"] == envelope_before
    assert svc.get_mission_state(mission_id)["mission_state"] == state_before
    scope_after = svc.get_mission_scope_contract(mission_id)
    assert scope_after["snapshot_id"] == scope["snapshot_id"]
    assert scope_after["canonical_sha256"] == scope["canonical_sha256"]


def test_post_approval_reconciliation_appends_authoritative_allow_and_is_idempotent(tmp_path):
    svc, fake = service(tmp_path)
    mission_id, _ = provision(svc)
    svc.put_mission_governance_binding(mission_id, binding_payload())
    evaluate = fake.evaluate_authorization
    def issue_review(payload):
        response = evaluate(payload)
        row = fake.decisions[-1]
        row["decision"], row["reason_codes"] = "REVIEW", ["HUMAN_APPROVAL_REQUIRED"]
        row.pop("decision_hash", None)
        row["decision_hash"] = fake._hash(row)
        response.update(row)
        return response
    fake.evaluate_authorization = issue_review
    original = svc.authorize_mission_capability(mission_id, auth_payload())
    original_id = original["authorization_binding_id"]
    now = datetime.now(timezone.utc)
    latest = dict(fake.decisions[-1])
    latest.update({"id": 2, "decision_id": "gdec-after-approval", "decision": "ALLOW", "reason_codes": ["HUMAN_APPROVAL_GRANTED", "IP_MATCH"], "valid_from": now.isoformat().replace("+00:00", "Z"), "valid_until": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")})
    latest.pop("decision_hash", None)
    latest["decision_hash"] = fake._hash(latest)
    fake.decisions.append(latest)
    fake.events.append({"event_id": "gevent-after-approval", "event_type": "POLICY_DECISION_ISSUED", "mission_id": mission_id, "payload": {**latest, "governance_event_id": "gevent-after-approval"}})
    reconciled = svc.reconcile_mission_authorization(mission_id, original_id)
    assert reconciled["authorization_binding_id"] != original_id
    assert reconciled["governance_status"] == "AUTHORIZED" and reconciled["authorization_granted"] is True
    assert reconciled["execution_authorized"] is False
    assert reconciled["authorization_binding"]["reconciliation"]["supersedes_authorization_binding_id"] == original_id
    assert verify_authorization_binding(reconciled["authorization_binding"])
    history = svc.get_mission_authorization_history(mission_id)
    assert history["authorization_binding_count"] == 2
    assert [x["decision"] for x in history["authorization_bindings"]] == ["REVIEW", "ALLOW"]
    replay = svc.reconcile_mission_authorization(mission_id, original_id)
    assert replay["idempotent_replay"] is True
    assert replay["authorization_binding_id"] == reconciled["authorization_binding_id"]


def test_post_approval_reconciliation_rejects_expired_decision(tmp_path):
    svc, fake = service(tmp_path)
    mission_id, _ = provision(svc)
    svc.put_mission_governance_binding(mission_id, binding_payload())
    evaluate = fake.evaluate_authorization
    def issue_review(payload):
        response = evaluate(payload)
        row = fake.decisions[-1]
        row["decision"], row["reason_codes"] = "REVIEW", ["HUMAN_APPROVAL_REQUIRED"]
        row.pop("decision_hash", None)
        row["decision_hash"] = fake._hash(row)
        response.update(row)
        return response
    fake.evaluate_authorization = issue_review
    original = svc.authorize_mission_capability(mission_id, auth_payload())
    latest = dict(fake.decisions[-1])
    latest.update({"id": 2, "decision_id": "gdec-expired", "decision": "ALLOW", "reason_codes": ["HUMAN_APPROVAL_GRANTED"]})
    latest["valid_from"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    latest["valid_until"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    latest.pop("decision_hash", None)
    latest["decision_hash"] = fake._hash(latest)
    fake.decisions.append(latest)
    with pytest.raises(MissionAuthorizationFailClosed, match="not currently valid"):
        svc.reconcile_mission_authorization(mission_id, original["authorization_binding_id"])
    assert svc.get_mission_authorization_history(mission_id)["authorization_binding_count"] == 1


def test_health_declares_capability_binding_and_preserves_authority_separation(tmp_path):
    svc, _ = service(tmp_path)
    health = svc.health()
    assert "stage3.1.4-governance-authorization-binding-contract" in health["supported_controls"]
    assert health["governance_binding_enabled"] is True
    assert health["governance_binding_mode"] == "CAPABILITY_BASED_DEFAULT_DENY_FAIL_CLOSED"
    assert health["decision_provenance_mode"] == "AUTHORITATIVE_POLICYDECISION_IMMUTABLE_BINDING"
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["governance_authority_component"] == "GOV-PLANE"
    assert health["pre_dispatch_revalidation_required"] is True
    assert health["dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_governance_http_adapter_unwraps_aptsgss_transport_envelopes(monkeypatch):
    from mission_orchestrator.governance_binding import GovernanceClient

    client = GovernanceClient(base_url="http://governance.invalid")
    responses = {
        ("POST", "/api/governance/scope-contracts"): {
            "status": "completed",
            "scope_contract": {"scope_contract_id": "scope-1"},
        },
        ("GET", "/api/governance/scope-contracts/scope-1"): {
            "status": "completed",
            "scope_contract": {"scope_contract_id": "scope-1"},
        },
        ("POST", "/api/governance/authorization/evaluate"): {
            "status": "completed",
            "policy_decision": {"decision_id": "gdec-1"},
        },
        ("GET", "/api/governance/correlation/missions/mission-1"): {
            "status": "completed",
            "correlation_snapshot": {"mission_id": "mission-1"},
        },
    }

    def fake_request(method, path, payload=None):
        return responses[(method, path)]

    monkeypatch.setattr(client, "_request", fake_request)
    assert client.create_scope_contract({"mission_id": "mission-1"})["scope_contract_id"] == "scope-1"
    assert client.get_scope_contract("scope-1")["scope_contract_id"] == "scope-1"
    assert client.evaluate_authorization({"mission_id": "mission-1"})["decision_id"] == "gdec-1"
    assert client.mission_correlation_snapshot("mission-1")["mission_id"] == "mission-1"

    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: {"status": "completed", "unexpected": {}},
    )
    with pytest.raises(MissionGovernanceProtocolError, match="missing object field"):
        client.create_scope_contract({"mission_id": "mission-1"})
