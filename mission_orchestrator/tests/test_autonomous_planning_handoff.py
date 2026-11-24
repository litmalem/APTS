from copy import deepcopy

from mission_orchestrator.canonical import sha256_hex
from mission_orchestrator.automatic_pip import sweep as automatic_sweep
from pentest_subsystem.agentic_pentest_acceptance_service import AgenticPentestAcceptanceService
from pentest_subsystem.web_ui import list_orchestration_options
from test_gss_scope_sync import Gss
from test_stage3_2_3_mission_pip_activation import mission_payload
from test_two_phase_pip_initialization import ready
from mission_orchestrator.pip_initialization import GATES


def test_pip_bound_autonomously_plans_and_registers_scope_target_without_run(ready, tmp_path, monkeypatch):
    service, _, cti, _, _ = ready
    body = mission_payload("autonomous-plan", with_pip=False)
    body["required_subsystems"] = ["CTI", "PENTEST"]
    mission_id = service.create_mission(body)["canonical_identity"]["mission_id"]
    service.governance_client = gss = Gss(mission_id)

    def build_pip(payload):
        artifact = {
            "pip_id": "pip-auto-plan", "revision": 1,
            "mission_binding": deepcopy(payload["mission_binding"]),
            "semantics": {"execution_authorized": False, "execution_command": False},
            "intelligence": {}, "quality": {"validator_version": "pip-validator-1.0"},
        }
        artifact["mission_binding"]["mission_id"] = mission_id
        digest = sha256_hex(artifact)
        artifact["integrity"] = {"sha256": digest}
        cti.pip = {"pip_id": "pip-auto-plan", "revision": 1, "mission_id": mission_id,
                   "immutable": True, "artifact": artifact, "canonical_sha256": digest,
                   "readiness": "PARTIAL", "validation_results": [
                       {"gate_id": gate, "passed": True} for gate in sorted(GATES)]}
        return {"status": "completed", "pip": deepcopy(cti.pip)}

    cti.build_pip = build_pip
    monkeypatch.setenv("APTS_PENTEST_DB", str(tmp_path / "pentest.db"))
    automatic_sweep(service)
    automatic_sweep(service)
    first = service.get_generated_plan(mission_id)
    second = service.get_generated_plan(mission_id)
    validation = service.get_plan_validation(mission_id)
    pentest = AgenticPentestAcceptanceService()
    options = list_orchestration_options(pentest)

    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "PLANNING"
    assert validation["validation_status"] == "VALIDATED_FEASIBLE"
    assert first["generated_plan_id"] == second["generated_plan_id"]
    decomposition = service.get_task_decomposition(mission_id)
    assert decomposition["task_count"] == 13
    planned = service.list_planned_tasks(mission_id)
    tasks = [
        {
            **row["planned_task"]["specification"],
            "metadata": row["planned_task"]["provenance"]["task_metadata"],
            "task_key": row["task_key"],
        }
        for row in planned["planned_tasks"]
    ]
    assert [row["task_key"] for row in planned["planned_tasks"]] == [
        "t1-pentest-orchestration", "t1-recon", "t1-wpt-intake", "t1-wpt-fingerprint",
        "t1-recon-wpt-result", "t1-vulndesk-cti", "t1-enumeration",
        "t1-vulnerability-hypothesis", "t1-attack-path", "t1-validation-proposal",
        "t1-stage6-validation", "t1-impact", "t1-cleanup",
    ]
    by_key = {task["task_key"]: task for task in tasks}
    assert by_key["t1-vulnerability-hypothesis"]["metadata"]["input_artifacts"] == [
        "enumeration_evidence_bundle", "vulndesk_cti_knowledge_reference"]
    assert by_key["t1-wpt-intake"]["metadata"]["wpt_intake_profile"] == "fingerprinting"
    assert by_key["t1-wpt-fingerprint"]["metadata"]["stage6_profile"] == "web_technology_fingerprinting"
    assert by_key["t1-wpt-fingerprint"]["metadata"]["stage6_authorization_required"] is True
    assert by_key["t1-stage6-validation"]["metadata"]["execution_authorized"] is False
    assert by_key["t1-cleanup"]["metadata"]["planning_only"] is True
    assert all(task["metadata"]["target_io_performed"] is False for task in tasks)
    assert first["generated_plan"]["semantics"]["target_action_dispatch_enabled"] is False
    assert first["generated_plan"]["semantics"]["target_actuation"] is False
    mission_targets = [item for item in options["mission_scope_targets"] if item["mission_id"] == mission_id]
    assert len(mission_targets) == 1
    target = mission_targets[0]
    assert target["target"] == {
        "target_type": "URL", "target_value": "http://localhost:3000/", "environment": "LAB"}
    assert target["semantics"] == {
        "target_is_observed": False, "execution_authorized": False,
        "recon_run_created": False, "external_network_io_performed": False}
    assert pentest.list_recon_runs() == []
    assert gss.mission_correlation_snapshot(mission_id)["mission_id"] == mission_id
