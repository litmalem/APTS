from __future__ import annotations

import os
import sys
import types
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG_PATH = os.path.join(ROOT, "cti_services")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if "cti_services" not in sys.modules:
    pkg = types.ModuleType("cti_services")
    pkg.__path__ = [PKG_PATH]
    sys.modules["cti_services"] = pkg

from cti_services.contracts import policy_decision_hash_payload
from cti_services.common import sha256_object
from cti_services.governance_client import (
    GovernanceClient,
    GovernanceProtocolError,
    GovernanceUnavailableError,
)


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.last_url = None
        self.last_json = None
        self.last_timeout = None

    def post(self, url, json, timeout):
        self.last_url = url
        self.last_json = json
        self.last_timeout = timeout
        if self.error:
            raise self.error
        return self.response

    def get(self, url, timeout):
        self.last_url = url
        self.last_timeout = timeout
        if self.error:
            raise self.error
        return self.response


class GovernanceClientTests(unittest.TestCase):
    def _decision_body(self, decision="ALLOW"):
        policy_decision = {
            "request_id": "greq-1",
            "decision_id": "gdec-1",
            "mission_id": "mission-1",
            "decision": decision,
            "risk_score": 5.0,
            "risk_level": "LOW",
            "reason_codes": ["ACTION_CONSTRAINT_ALLOW", "SOURCE_ALLOWED"],
            "constraints": {"read_only": True},
            "requires_human_approval": False,
            "approval_request_id": None,
            "valid_from": "2026-08-14T00:00:00+00:00",
            "valid_until": "2099-08-14T00:05:00+00:00",
            "policy_set_id": "default-policy",
            "policy_version": 1,
            "scope_contract_id": "scope-1",
            "scope_version": 1,
            "supersedes_decision_id": None,
            "governance_event_id": "gevent-issued-1",
        }
        policy_decision["decision_hash"] = sha256_object(
            policy_decision_hash_payload(policy_decision)
        )
        return {"status": "completed", "policy_decision": policy_decision}

    def test_cti_source_read_contract_matches_aptsgss(self):
        session = FakeSession(response=FakeResponse(body=self._decision_body("ALLOW")))
        client = GovernanceClient(
            enabled=True,
            base_url="http://127.0.0.1:8770",
            timeout_seconds=3,
            session=session,
        )
        decision = client.evaluate_cti_source_read(
            mission_id="mission-1",
            scope_contract_id="scope-1",
            source_id="nvd-cve",
            action_name="INCREMENTAL_FETCH",
            context={"environment": "LAB", "reversible": True, "blast_radius": 1},
        )
        self.assertEqual(session.last_url, "http://127.0.0.1:8770/api/governance/authorization/evaluate")
        self.assertEqual(session.last_json["subject_component"], "CTI-A02")
        self.assertEqual(session.last_json["action_class"], "CTI_SOURCE_READ")
        self.assertEqual(session.last_json["resource_type"], "CTI_SOURCE")
        self.assertEqual(session.last_json["resource_value"], "nvd-cve")
        self.assertEqual(decision["decision"], "ALLOW")
        self.assertTrue(decision["execution_authorized"])
        self.assertEqual(decision["authority"], "aptsGSS")
        self.assertEqual(decision["governance_event_id"], "gevent-issued-1")
        self.assertTrue(decision["decision_hash_verified"])
        self.assertEqual(decision["authorization_request"]["resource_value"], "nvd-cve")

    def test_disabled_governance_is_unavailable_not_allow(self):
        client = GovernanceClient(enabled=False, session=FakeSession())
        with self.assertRaises(GovernanceUnavailableError):
            client.evaluate_cti_source_read(mission_id="m1", source_id="nvd-cve")

    def test_invalid_decision_is_protocol_error(self):
        body = self._decision_body("ALLOW")
        body["policy_decision"]["decision"] = "MAYBE"
        client = GovernanceClient(enabled=True, session=FakeSession(response=FakeResponse(body=body)))
        with self.assertRaises(GovernanceProtocolError):
            client.evaluate_cti_source_read(mission_id="m1", source_id="nvd-cve")

    def test_hash_tampering_is_protocol_error(self):
        body = self._decision_body("ALLOW")
        body["policy_decision"]["constraints"] = {"read_only": False}
        client = GovernanceClient(enabled=True, session=FakeSession(response=FakeResponse(body=body)))
        with self.assertRaises(GovernanceProtocolError):
            client.evaluate_cti_source_read(
                mission_id="mission-1", scope_contract_id="scope-1", source_id="nvd-cve"
            )

    def test_pre_dispatch_revalidation_contract(self):
        body = {
            "status": "completed",
            "revalidation": {
                "revalidation_id": "greval-1",
                "status": "VALID",
                "valid": True,
                "execution_authorized": True,
                "reason_codes": ["POLICY_DECISION_STILL_VALID"],
                "decision_id": "gdec-1",
                "request_id": "greq-1",
                "mission_id": "mission-1",
                "decision": "ALLOW",
                "decision_status": "ACTIVE",
                "decision_hash": "a" * 64,
                "scope_contract_id": "scope-1",
                "scope_version": 1,
                "current_scope_version": 1,
                "policy_set_id": "default-policy",
                "policy_version": 1,
                "current_policy_version": 1,
                "emergency_stop_active": False,
                "checked_at": "2026-08-15T00:00:00+00:00",
                "authority": "aptsGSS",
                "authority_component": "GOV-PLANE",
                "governance_event_id": "gevent-revalidation-1",
            },
        }
        session = FakeSession(response=FakeResponse(body=body))
        client = GovernanceClient(
            enabled=True,
            base_url="http://127.0.0.1:8770",
            session=session,
        )
        result = client.revalidate_policy_decision(
            task_id="task-1",
            decision_id="gdec-1",
            request_id="greq-1",
            mission_id="mission-1",
            decision_hash="a" * 64,
            scope_contract_id="scope-1",
            scope_version=1,
            policy_set_id="default-policy",
            policy_version=1,
            subject_component="CTI-A02",
            action_class="CTI_SOURCE_READ",
            action_name="INCREMENTAL_FETCH",
            resource_type="CTI_SOURCE",
            resource_value="nvd-cve",
        )
        self.assertEqual(
            session.last_url,
            "http://127.0.0.1:8770/api/governance/authorization/revalidate",
        )
        self.assertEqual(session.last_json["task_id"], "task-1")
        self.assertEqual(session.last_json["resource_value"], "nvd-cve")
        self.assertTrue(result["valid"])
        self.assertTrue(result["execution_authorized"])
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["governance_event_id"], "gevent-revalidation-1")

    def test_pre_dispatch_revalidation_rejects_hash_mismatch(self):
        body = {
            "status": "completed",
            "revalidation": {
                "revalidation_id": "greval-2",
                "status": "VALID",
                "valid": True,
                "execution_authorized": True,
                "reason_codes": ["POLICY_DECISION_STILL_VALID"],
                "decision_id": "gdec-1",
                "request_id": "greq-1",
                "mission_id": "mission-1",
                "decision_status": "ACTIVE",
                "decision_hash": "b" * 64,
                "checked_at": "2026-08-15T00:00:00+00:00",
                "authority": "aptsGSS",
                "authority_component": "GOV-PLANE",
                "governance_event_id": "gevent-revalidation-2",
            },
        }
        client = GovernanceClient(enabled=True, session=FakeSession(response=FakeResponse(body=body)))
        with self.assertRaises(GovernanceProtocolError):
            client.revalidate_policy_decision(
                task_id="task-1",
                decision_id="gdec-1",
                request_id="greq-1",
                mission_id="mission-1",
                decision_hash="a" * 64,
                scope_contract_id="scope-1",
                scope_version=1,
                policy_set_id="default-policy",
                policy_version=1,
                subject_component="CTI-A02",
                action_class="CTI_SOURCE_READ",
                action_name="INCREMENTAL_FETCH",
                resource_type="CTI_SOURCE",
                resource_value="nvd-cve",
            )

    def test_get_mission_correlation_snapshot_validates_contract(self):
        snapshot = {
            "schema_version": "governance-correlation-snapshot-v1",
            "mission_id": "mission-1",
            "scope_contracts": [],
            "authorization_requests": [],
            "policy_decisions": [],
            "events": [],
            "audit_records": [],
        }
        session = FakeSession(response=FakeResponse(body={
            "status": "completed",
            "correlation_snapshot": snapshot,
        }))
        client = GovernanceClient(enabled=True, base_url="http://127.0.0.1:8770", session=session)
        result = client.get_mission_correlation_snapshot("mission-1")
        self.assertEqual(
            session.last_url,
            "http://127.0.0.1:8770/api/governance/correlation/missions/mission-1",
        )
        self.assertEqual(result["mission_id"], "mission-1")

    def test_get_mission_correlation_snapshot_rejects_wrong_mission(self):
        snapshot = {
            "mission_id": "other-mission",
            "scope_contracts": [],
            "authorization_requests": [],
            "policy_decisions": [],
            "events": [],
            "audit_records": [],
        }
        client = GovernanceClient(
            enabled=True,
            session=FakeSession(response=FakeResponse(body={
                "status": "completed",
                "correlation_snapshot": snapshot,
            })),
        )
        with self.assertRaises(GovernanceProtocolError):
            client.get_mission_correlation_snapshot("mission-1")

    def test_get_policy_decision_validates_identity_and_status_shape(self):
        body = self._decision_body("ALLOW")
        body["policy_decision"]["decision_status"] = "ACTIVE"
        session = FakeSession(response=FakeResponse(body=body))
        client = GovernanceClient(enabled=True, base_url="http://127.0.0.1:8770", session=session)
        decision = client.get_policy_decision(
            "gdec-1", expected_mission_id="mission-1", expected_scope_contract_id="scope-1"
        )
        self.assertEqual(session.last_url, "http://127.0.0.1:8770/api/governance/decisions/gdec-1")
        self.assertEqual(decision["decision_status"], "ACTIVE")
        self.assertFalse(decision["decision_hash_verified"])


if __name__ == "__main__":
    unittest.main()
