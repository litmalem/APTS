"""Cross-module acceptance for Mission WPT intake -> sealed result -> Recon run.

The Stage 6 evidence ledger is a deterministic test double: the checked-in WPT
profiles are still REGISTERED_NOT_EXECUTABLE, so this test must never send
network traffic. Mission intake, durable stores, HTTP routes, and the Recon
receiver/repository are real implementations.
"""
from __future__ import annotations

from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from execution_subsystem.wpt_intake_repository import WPTIntakeRepository
from execution_subsystem.wpt_intake_service import WPTIntakeService
from mission_orchestrator.api_service import MissionOrchestratorHandler
from pentest_subsystem.reconnaissance import ReconnaissanceAgentService
from tests.test_stage5_2_reconnaissance_agent import _start_repo, recon_request


TOKEN = "acceptance-secret-" + "x" * 40


class AuthorizedTaskSnapshot:
    """Test authority seam returning a current, explicitly executable binding."""
    def __init__(self, task, orchestration):
        self.task = task
        self.orchestration = orchestration
        self.calls = []

    def resolve(self, intake):
        self.calls.append(deepcopy(intake))
        if intake["target"] != self.task["target"]:
            from execution_subsystem.execution_contract import ExecutionSourceRejected
            raise ExecutionSourceRejected("target is outside the acceptance task scope")
        profile = intake["profile"]
        if profile == "fingerprinting":
            action = {"action_class": "TARGET_RECON", "capability_id": "web_technology_fingerprinting",
                      "technique": "WEB_TECHNOLOGY_FINGERPRINT"}
            profile_id = "wpt.fingerprinting.v1"
        else:
            action = {"action_class": "TARGET_RECON", "capability_id": "web_surface_enumeration",
                      "technique": "BOUNDED_WEB_SURFACE_ENUMERATION"}
            profile_id = "wpt.bounded-enumeration.v1"
        return {
            "mission_id": self.task["mission_id"], "task_id": self.task["upstream_task_id"],
            "pentest_task_id": self.task["pentest_task_id"], "pentest_id": self.task["pentest_id"],
            "target": deepcopy(self.task["target"]), "profile_id": profile_id, "action": action,
            "limits": {"max_requests": 6, "max_response_bytes": 327680, "max_concurrency": 1,
                       "timeout_seconds": 30, "redirects": "DENY"},
            "mission_network_request_budget": 10, "mission_scope_sha256": "a" * 64,
            "task_artifact_sha256": "b" * 64, "task_binding_sha256": "c" * 64,
            "task_lifecycle_state": "RUNNING", "orchestration_id": self.orchestration["orchestration_id"],
            "orchestration_status": "ACTIVE", "governance_binding_sha256": "d" * 64,
            "execution_status": "EXECUTABLE",
        }


class SealedStage6Ledger:
    """Provides a verified terminal Stage 6 ledger entry without target I/O."""
    def __init__(self, task):
        self.task = task
        self.reads = []

    def get_wpt_result_snapshot(self, execution_id, attempt_id):
        self.reads.append((execution_id, attempt_id))
        mission_id, task_id = self.task["mission_id"], self.task["upstream_task_id"]
        return {
            "execution_id": execution_id, "attempt_id": attempt_id,
            "mission_id": mission_id, "task_id": task_id, "runtime_state": "SUCCEEDED",
            "action": {"action_class": "TARGET_RECON", "capability_id": "web_technology_fingerprinting",
                       "technique": "WEB_TECHNOLOGY_FINGERPRINT"},
            "target": deepcopy(self.task["target"]),
            "runtime_result": {"status": "SUCCEEDED", "reason_codes": [],
                "observation": {"technology_findings": [{"name": "Example Server", "version": "1.2"}]},
                "integrity": {"canonical_sha256": "e" * 64}},
            "evidence": {"sealed": True, "evidence_id": "xevidence-acceptance", "manifest_sha256": "f" * 64,
                "manifest": {"attempt_id": attempt_id, "mission_id": mission_id, "task_id": task_id,
                    "capture_status": "CAPTURED", "adapter_result_sha256": "e" * 64,
                    "integrity": {"canonical_sha256": "f" * 64}}},
        }


def _post(url, payload, token=TOKEN):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_acceptance_wpt_intake_sealed_stage6_result_and_durable_recon_handoff(tmp_path):
    recon_repo, boundary, task, orchestration, *_ = _start_repo(tmp_path, "wpt-cross-module")
    parent, _ = recon_repo.run_reconnaissance(
        orchestration["orchestration_id"], recon_request(boundary, task, "wpt-cross-module")
    )
    action = parent["output"]["action_requests"][0]

    authority = AuthorizedTaskSnapshot(task, orchestration)
    ledger = SealedStage6Ledger(task)
    recon_receiver = ReconnaissanceAgentService(recon_repo)
    receiver_attempts = []
    receiver_deliveries = []

    def recovered_receiver(event):
        receiver_deliveries.append(event["handoff_id"])
        return recon_receiver.run_wpt_reconnaissance_iteration(event)

    def flaky_receiver(event):
        receiver_attempts.append(event["handoff_id"])
        if len(receiver_attempts) == 1:
            raise ConnectionError("simulated lost Recon acknowledgement")
        return recon_receiver.run_wpt_reconnaissance_iteration(event)

    intake_db = tmp_path / "mission-wpt-intake.db"
    intake_service = WPTIntakeService(
        WPTIntakeRepository(intake_db), authority, ledger,
        token=TOKEN, recon_handoff_provider=flaky_receiver,
    )
    handler = type("WPTToReconAcceptanceHandler", (MissionOrchestratorHandler,),
                   {"wpt_intake_service": intake_service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    intake_id = "wptreq-cross-module"
    execution_id, attempt_id = "exec-cross-module", "xattempt-cross-module"
    intake_body = {
        "schema_version": "apts-wpt-governed-intake-v1", "intake_id": intake_id,
        "idempotency_key": "idem-cross-module", "mission_id": task["mission_id"],
        "task_id": task["upstream_task_id"], "target": deepcopy(task["target"]),
        "profile": "fingerprinting",
    }
    try:
        # Authentication is enforced at the actual Mission HTTP endpoint.
        status, denied = _post(base + "/api/wpt/intakes", intake_body, token=None)
        assert status == 401

        status, submitted = _post(base + "/api/wpt/intakes", intake_body)
        assert status == 201
        assert submitted["record"]["status"] == "ACCEPTED_PENDING_STAGE6"
        assert submitted["record"]["semantics"]["execution_authorized"] is False
        assert submitted["record"]["semantics"]["target_io_performed"] is False

        # Idempotent re-submit yields the same Mission intake record.
        status, replay = _post(base + "/api/wpt/intakes", intake_body)
        assert status == 200 and replay["created"] is False
        assert len(authority.calls) == 1

        # A target outside the authoritative task target is rejected before
        # Stage 6 lookup or durable intake creation.
        outside_scope = deepcopy(intake_body)
        outside_scope.update(intake_id="wptreq-out-of-scope", idempotency_key="idem-out-of-scope")
        outside_scope["target"]["target_value"] = "https://outside.example/"
        status, rejection = _post(base + "/api/wpt/intakes", outside_scope)
        assert status == 409 and rejection["status"] == "rejected"
        assert intake_service.get("wptreq-out-of-scope") is None
        assert ledger.reads == []

        result_ref = {"schema_version": "apts-wpt-stage6-result-reference-v1", "intake_id": intake_id,
                      "execution_id": execution_id, "attempt_id": attempt_id}
        status, result_response = _post(base + f"/api/wpt/intakes/{intake_id}/stage6-results", result_ref)
        assert status == 201
        stored_result = result_response["record"]
        assert stored_result["status"] == "VALIDATED_AND_STORED"
        assert stored_result["evidence"]["capture_status"] == "SEALED"
        assert stored_result["semantics"]["sealed_evidence_verified"] is True
        assert stored_result["result"]["result_sha256"] == "e" * 64
        assert ledger.reads == [(execution_id, attempt_id)]

        handoff_body = {"schema_version": "apts-wpt-recon-handoff-request-v1",
                        "parent_recon_run_id": parent["recon_run_id"], "action_id": action["action_id"]}
        status, pending = _post(base + f"/api/wpt/intakes/{intake_id}/recon-handoff", handoff_body)
        assert status == 202 and pending["delivery_status"] == "PENDING"
        assert recon_repo.list_recon_runs() == [parent]

        # Simulate Mission process restart with the same durable intake/outbox DB.
        restarted = WPTIntakeService(
            WPTIntakeRepository(intake_db), authority, ledger, token=TOKEN,
            recon_handoff_provider=recovered_receiver,
        )
        handler.wpt_intake_service = restarted
        status, delivered = _post(base + f"/api/wpt/intakes/{intake_id}/recon-handoff", handoff_body)
        assert status == 200 and delivered["delivery_status"] == "DELIVERED"
        assert delivered["attempts"] == 2
        assert delivered["acknowledgement"]["accepted"] is True

        child_id = delivered["acknowledgement"]["recon_run_id"]
        child = recon_repo.get_recon_run(child_id)
        assert child["parent_recon_run_id"] == parent["recon_run_id"]
        assert child["source_action_id"] == action["action_id"]
        assert child["source_result_sha256"] == delivered["acknowledgement"]["source_result_sha256"]
        imported = child["request"]["observations"][-1]
        assert imported["source"]["source_kind"] == "WPT_STAGE6_RESULT"
        assert imported["raw_evidence_sha256"] == "f" * 64
        assert imported["attributes"]["observation"]["technology_findings"][0]["name"] == "Example Server"
        assert recon_repo.get_recon_run(parent["recon_run_id"]) == parent

        # Restart the intake repository and replay: persisted ACK prevents a
        # second receiver invocation/run creation.
        handler.wpt_intake_service = WPTIntakeService(
            WPTIntakeRepository(intake_db), authority, ledger, token=TOKEN,
            recon_handoff_provider=lambda _: pytest.fail("delivered handoff was re-invoked"),
        )
        status, replayed = _post(base + f"/api/wpt/intakes/{intake_id}/recon-handoff", handoff_body)
        assert status == 200 and replayed["delivery_status"] == "DELIVERED"
        assert replayed["created"] is False
        assert replayed["acknowledgement"]["recon_run_id"] == child_id
        assert len(receiver_attempts) == 1 and len(receiver_deliveries) == 1
        assert len(recon_repo.list_recon_runs()) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
