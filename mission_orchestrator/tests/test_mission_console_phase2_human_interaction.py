from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from mission_orchestrator.errors import MissionConcurrencyConflict
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class GovernanceVisibilityClient:
    base_url = "http://governance.example.test:8770"

    def mission_correlation_snapshot(self, mission_id: str):
        return {
            "schema_version": "governance-correlation-snapshot-v1",
            "mission_id": mission_id,
            "authority": "aptsGSS",
            "scope_contracts": [],
            "authorization_requests": [
                {
                    "request_id": "greq-phase2",
                    "mission_id": mission_id,
                    "action_class": "CONTROLLED_EXPLOITATION",
                    "action_name": "RUN_TOOL",
                    "resource_type": "TARGET",
                    "resource_value": "lab-target",
                    "request_status": "REVIEW",
                }
            ],
            "policy_decisions": [
                {
                    "decision_id": "gdec-phase2",
                    "request_id": "greq-phase2",
                    "mission_id": mission_id,
                    "decision": "REVIEW",
                    "requires_human_approval": True,
                    "approval_request_id": "gapproval-phase2",
                }
            ],
            "events": [],
            "audit_records": [],
            "counts": {
                "scope_contracts": 0,
                "authorization_requests": 1,
                "policy_decisions": 1,
                "events": 0,
                "audit_records": 0,
            },
        }

    def get_approval_request(self, approval_request_id: str):
        assert approval_request_id == "gapproval-phase2"
        return {
            "approval_request_id": approval_request_id,
            "mission_id": "any",
            "risk_level": "HIGH",
            "required_approver_role": "SECURITY_APPROVER",
            "status": "PENDING",
        }


def _service_with_copy(tmp_path: Path, *, governance_client=None) -> CanonicalMissionService:
    root = Path(__file__).resolve().parents[1]
    db = tmp_path / "mission_orchestrator.db"
    shutil.copy2(root / "data" / "mission_orchestrator.db", db)
    return CanonicalMissionService(
        repository=MissionRepository(sqlite_path=str(db)),
        governance_client=governance_client,
    )


def test_phase2_console_exposes_only_bounded_human_interaction_surface():
    root = Path(__file__).resolve().parents[1]
    js = (root / "mission_web" / "app.js").read_text(encoding="utf-8")
    html = (root / "mission_web" / "index.html").read_text(encoding="utf-8")

    assert "PHASE 2 · GUARDED HUMAN INTERACTION" in html
    assert "const PHASE2_COMMANDS = ['START', 'PAUSE', 'RESUME', 'REPLAN', 'BEGIN_CLEANUP', 'ABORT'];" in js
    assert "/lifecycle/commands" in js
    assert "/version-vector" in js
    assert "/lifecycle-command-contract" in js
    assert "/governance-visibility" in js
    assert "No command is automatically retried" in js
    assert "approval_decision_enabled" not in js  # no approval mutation surface in browser code


def test_phase2_pause_uses_canonical_guarded_command_and_stale_vector_is_rejected(tmp_path):
    service = _service_with_copy(tmp_path)
    running = service.list_missions(state="RUNNING", limit=1)["missions"]
    assert running, "fixture database must contain at least one RUNNING mission"
    mission_id = running[0]["mission_id"]

    before_state = service.get_mission_state(mission_id)["mission_state"]
    before_vector = service.get_mission_version_vector(mission_id)
    contract = service.get_mission_lifecycle_command_contract(mission_id)
    assert "PAUSE" in contract["guard_eligible_commands"]
    assert before_vector["version_vector_complete"] is True

    token = uuid.uuid4().hex
    result = service.execute_mission_lifecycle_command(
        mission_id,
        {
            "command_id": f"ui-pause-{token}",
            "idempotency_key": f"ui-pause-{token}",
            "command": "PAUSE",
            "expected_version_sha256": before_vector["version_sha256"],
            "expected_state_version": before_state["state_version"],
            "actor": "phase2-test-operator",
            "reason_code": "UI_PAUSE",
            "reason": "Focused Phase-2 test of guarded human interaction.",
            "evidence_refs": [],
            "metadata": {"source": "MISSION_WEB_PHASE2"},
        },
    )
    assert result["mission_state"]["state"] == "PAUSED"
    assert result["transition"]["from_state"] == "RUNNING"
    assert result["transition"]["to_state"] == "PAUSED"
    assert result["target_action_dispatch_enabled"] is False
    assert result["target_actuation"] is False

    stale = uuid.uuid4().hex
    with pytest.raises(MissionConcurrencyConflict):
        service.execute_mission_lifecycle_command(
            mission_id,
            {
                "command_id": f"ui-abort-{stale}",
                "idempotency_key": f"ui-abort-{stale}",
                "command": "ABORT",
                "expected_version_sha256": before_vector["version_sha256"],
                "expected_state_version": before_state["state_version"],
                "actor": "phase2-test-operator",
                "reason_code": "UI_ABORT",
                "reason": "This stale request must not be applied.",
                "evidence_refs": [],
                "metadata": {"source": "MISSION_WEB_PHASE2"},
            },
        )


def test_phase2_governance_visibility_is_read_only_and_surfaces_pending_approval(tmp_path):
    service = _service_with_copy(tmp_path, governance_client=GovernanceVisibilityClient())
    mission_id = service.list_missions(limit=1)["missions"][0]["mission_id"]

    result = service.get_mission_governance_visibility(mission_id)

    assert result["read_only"] is True
    assert result["authority_semantics"] == "VISIBILITY_ONLY_NO_AUTHORIZATION_NO_APPROVAL_DECISION"
    assert result["external_authority"]["status"] == "AVAILABLE"
    assert result["external_authority"]["pending_approval_count"] == 1
    assert result["external_authority"]["approval_requests"][0]["status"] == "PENDING"
    assert result["operator_controls"] == {
        "approval_decision_enabled": False,
        "authorization_decision_enabled": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }
