from __future__ import annotations

from copy import deepcopy
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json

import pytest

from execution_subsystem.execution_contract import ExecutionRequestConflict, ExecutionRequestValidationError
from execution_subsystem.wpt_intake_contract import normalize_wpt_intake
from execution_subsystem.wpt_intake_repository import WPTIntakeRepository
from execution_subsystem.wpt_intake_service import WPTIntakeService


def request(suffix="one", **changes):
    value = {
        "schema_version": "apts-wpt-governed-intake-v1",
        "intake_id": f"wptreq-{suffix}", "idempotency_key": f"idem-{suffix}",
        "mission_id": "mission-gmo-intake", "task_id": "ptask-intake",
        "target": {"target_type": "URL", "target_value": "https://example.test/"},
        "profile": "fingerprinting",
    }
    value.update(changes)
    return value


class Authority:
    def __init__(self):
        self.calls = []

    def resolve(self, normalized):
        self.calls.append(deepcopy(normalized))
        return {
            "mission_id": normalized["mission_id"], "task_id": normalized["task_id"],
            "pentest_task_id": "pentest-task-intake", "pentest_id": "pentest-intake",
            "target": deepcopy(normalized["target"]), "profile_id": "wpt.fingerprinting.v1",
            "action": {"action_class": "TARGET_RECON", "capability_id": "web_technology_fingerprinting",
                       "technique": "WEB_TECHNOLOGY_FINGERPRINT"},
            "limits": {"max_requests": 6, "max_response_bytes": 327680,
                       "max_concurrency": 1, "timeout_seconds": 30, "redirects": "DENY"},
            "mission_network_request_budget": 10,
            "mission_scope_sha256": "a" * 64, "task_artifact_sha256": "b" * 64,
            "task_binding_sha256": "c" * 64, "task_lifecycle_state": "RUNNING",
            "orchestration_id": "orchestrator-intake", "orchestration_status": "ACTIVE",
            "governance_binding_sha256": "d" * 64,
            "execution_status": "REGISTERED_NOT_EXECUTABLE",
        }


def test_wpt_intake_schema_is_strict_and_does_not_accept_scope_claims():
    normalized = normalize_wpt_intake(request())
    assert normalized["profile"] == "fingerprinting"
    with pytest.raises(ExecutionRequestValidationError):
        normalize_wpt_intake({**request(), "scope": ["https://attacker.test/"]})
    with pytest.raises(ExecutionRequestValidationError):
        normalize_wpt_intake({**request(), "profile": "unbounded"})


def test_wpt_v2_intake_binds_to_unobserved_recon_declaration():
    value = request("recon-v2", schema_version="apts-wpt-governed-intake-v2",
                    recon_target_key="reconscope-target-one", recon_target_sha256="a" * 64,
                    recon_target_status="READY_FOR_COLLECTION", target_is_observed=False)
    normalized = normalize_wpt_intake(value)
    assert normalized["recon_target_key"] == "reconscope-target-one"
    assert normalized["target_is_observed"] is False
    with pytest.raises(ExecutionRequestValidationError):
        normalize_wpt_intake({**value, "target_is_observed": True})
    with pytest.raises(ExecutionRequestValidationError):
        normalize_wpt_intake({**value, "recon_target_sha256": "not-a-sha"})


def test_governed_intake_is_durable_idempotent_and_never_authorizes_io(tmp_path):
    repo = WPTIntakeRepository(tmp_path / "wpt-intake.db")
    authority = Authority()
    service = WPTIntakeService(repo, authority, token="t" * 40)
    first = service.submit(request())
    assert first["created"] is True
    record = first["record"]
    assert record["status"] == "ACCEPTED_PENDING_STAGE6"
    assert record["semantics"]["execution_authorized"] is False
    assert record["semantics"]["target_io_performed"] is False
    replay = service.submit(request())
    assert replay["created"] is False
    assert len(authority.calls) == 1
    restarted = WPTIntakeRepository(tmp_path / "wpt-intake.db")
    assert restarted.get("wptreq-one")["record"] == record
    with pytest.raises(ExecutionRequestConflict):
        service.submit(request("different", idempotency_key="idem-one"))


def test_wpt_intake_creates_immutable_request_before_runtime_admission(tmp_path,monkeypatch):
    monkeypatch.setenv("APTS_STAGE6_RUNTIME_URL","http://127.0.0.1:8792")
    class AdmittingGateway:
        def __init__(self):
            self.created_request = None
            self.submission = None

        def create_request(self, payload):
            self.created_request = deepcopy(payload)
            return {"envelope": {"execution_request": {"execution_id": "exec-wpt-governed"},
                                  "integrity": {"canonical_sha256": "a" * 64}}}

        def submit_execution(self, payload):
            self.submission = deepcopy(payload)
            return {"governance_query_performed": True,
                    "record": {"status": "ADMITTED_AWAITING_ADAPTER",
                               "authorization_id": "eauth-wpt-governed",
                               "gateway_id": "egw-wpt-governed"}}

    authority = Authority()
    authority.resolve = lambda normalized: {
        **Authority().resolve(normalized), "execution_status": "EXECUTABLE",
        "task_lifecycle_state": "RUNNING", "orchestration_status": "ACTIVE"}
    gateway = AdmittingGateway()
    service = WPTIntakeService(WPTIntakeRepository(tmp_path / "wpt-stage6.db"), authority,
                               token="t" * 40, stage6_gateway=gateway)

    result = service.submit(request())
    admission = result["stage6_admission"]
    assert gateway.created_request["source_type"] == "WPT_GOVERNED_INTAKE"
    assert gateway.created_request["wpt_intake_id"] == "wptreq-one"
    assert gateway.submission is None
    assert admission["status"] == "REQUEST_CREATED"
    assert admission["envelope_sha256"] == "a" * 64
    assert admission["authorization_recorded"] is False
    assert admission["governance_query_performed"] is False
    assert admission["gateway_admitted"] is False
    assert admission["execution_authorized"] is False
    assert admission["dispatch_performed"] is False
    assert admission["target_io_performed"] is False


def test_idempotent_intakes_reserve_budget_atomically_and_clamp_next_job(tmp_path):
    repo = WPTIntakeRepository(tmp_path / "wpt-intake.db")
    authority = Authority()
    service = WPTIntakeService(repo, authority, token="t" * 40)
    one = service.submit(request("one"))["record"]
    two = service.submit(request("two"))["record"]
    assert one["authority_snapshot"]["limits"]["max_requests"] == 6
    assert two["authority_snapshot"]["limits"]["max_requests"] == 4


def test_wpt_bearer_auth_fails_closed_when_missing_or_wrong():
    service = WPTIntakeService(token="s" * 40)
    assert service.authenticate("Bearer " + "s" * 40)
    assert not service.authenticate("Bearer " + "x" * 40)
    assert not WPTIntakeService(token="").authenticate("Bearer " + "s" * 40)


class Stage6Results:
    def __init__(self, **changes):
        self.snapshot = {
            "attempt_id": "xattempt-wpt-one", "execution_id": "exec-wpt-one",
            "mission_id": "mission-gmo-intake", "task_id": "ptask-intake",
            "runtime_state": "SUCCEEDED",
            "action": {"action_class": "TARGET_RECON", "capability_id": "web_technology_fingerprinting",
                       "technique": "WEB_TECHNOLOGY_FINGERPRINT"},
            "target": {"target_type": "URL", "target_value": "https://example.test/"},
            "runtime_result": {"status": "SUCCEEDED", "reason_codes": [],
                "observation": {"technology_findings": [{"name": "Example"}]},
                "integrity": {"canonical_sha256": "e" * 64}},
            "evidence": {"sealed": True, "evidence_id": "xevidence-wpt-one", "manifest_sha256": "f" * 64,
                "manifest": {"attempt_id": "xattempt-wpt-one", "mission_id": "mission-gmo-intake",
                    "task_id": "ptask-intake", "capture_status": "CAPTURED",
                    "adapter_result_sha256": "e" * 64, "integrity": {"canonical_sha256": "f" * 64}}},
        }
        self.snapshot.update(changes)

    def get_wpt_result_snapshot(self, execution_id, attempt_id):
        assert execution_id == "exec-wpt-one"
        assert attempt_id == "xattempt-wpt-one"
        return deepcopy(self.snapshot)


def test_stage6_result_requires_executable_profile_and_verified_terminal_evidence(tmp_path):
    repo = WPTIntakeRepository(tmp_path / "wpt-results.db")
    authority = Authority()
    service = WPTIntakeService(repo, authority, Stage6Results(), token="t" * 40)
    service.submit(request())
    ref = {"schema_version": "apts-wpt-stage6-result-reference-v1", "intake_id": "wptreq-one",
           "execution_id": "exec-wpt-one", "attempt_id": "xattempt-wpt-one"}
    with pytest.raises(Exception, match="capability is not executable"):
        service.submit_stage6_result(ref)

    authority.resolve = lambda normalized: {
        "mission_id": normalized["mission_id"], "task_id": normalized["task_id"],
        "pentest_task_id": "pentest-task-intake", "pentest_id": "pentest-intake",
        "target": deepcopy(normalized["target"]), "profile_id": "wpt.fingerprinting.v1",
        "action": Stage6Results().snapshot["action"],
        "limits": {"max_requests": 6}, "mission_network_request_budget": 10,
        "mission_scope_sha256": "a" * 64, "task_artifact_sha256": "b" * 64,
        "task_binding_sha256": "c" * 64, "task_lifecycle_state": "RUNNING",
        "orchestration_id": "orchestrator-intake", "orchestration_status": "ACTIVE",
        "governance_binding_sha256": "d" * 64, "execution_status": "EXECUTABLE"}
    executable_service = WPTIntakeService(repo, authority, Stage6Results(), token="t" * 40)
    # A fresh authorized intake snapshots the executable capability state.
    executable_service.submit(request("enabled"))
    ref["intake_id"] = "wptreq-enabled"
    created = executable_service.submit_stage6_result(ref)
    assert created["created"] is True
    assert created["record"]["status"] == "VALIDATED_AND_STORED"
    assert created["record"]["evidence"]["capture_status"] == "SEALED"
    assert created["record"]["result"]["result_sha256"] == "e" * 64
    assert executable_service.submit_stage6_result(ref)["created"] is False
    resumed = WPTIntakeRepository(tmp_path / "wpt-results.db")
    assert resumed.get_result("wptreq-enabled")["record"] == created["record"]


@pytest.mark.parametrize("changes, message", [
    ({"runtime_state": "FAILED"}, "successful terminal"),
    ({"mission_id": "mission-gmo-other"}, "binding mismatch"),
    ({"evidence": {"sealed": False}}, "sealed evidence"),
])
def test_stage6_result_rejects_untrusted_or_unbound_attempt(tmp_path, changes, message):
    repo = WPTIntakeRepository(tmp_path / "wpt-invalid.db")
    authority = Authority()
    authority.resolve = lambda normalized: {**Authority().resolve(normalized), "execution_status": "EXECUTABLE"}
    service = WPTIntakeService(repo, authority, Stage6Results(**changes), token="t" * 40)
    service.submit(request())
    ref = {"schema_version": "apts-wpt-stage6-result-reference-v1", "intake_id": "wptreq-one",
           "execution_id": "exec-wpt-one", "attempt_id": "xattempt-wpt-one"}
    with pytest.raises(Exception, match=message):
        service.submit_stage6_result(ref)


def test_wpt_recon_handoff_is_durable_idempotent_and_ack_bound(tmp_path):
    repo = WPTIntakeRepository(tmp_path / "wpt-handoff.db")
    authority = Authority()
    authority.resolve = lambda normalized: {**Authority().resolve(normalized), "execution_status": "EXECUTABLE"}
    deliveries = []

    def receiver(event):
        deliveries.append(deepcopy(event))
        return {"accepted": True, "intake_id": event["intake_id"],
                "source_result_sha256": event["source_result_sha256"], "recon_run_id": "reconrun-child"}

    service = WPTIntakeService(repo, authority, Stage6Results(), token="t" * 40,
                               recon_handoff_provider=receiver)
    service.submit(request())
    service.submit_stage6_result({"schema_version": "apts-wpt-stage6-result-reference-v1",
        "intake_id": "wptreq-one", "execution_id": "exec-wpt-one", "attempt_id": "xattempt-wpt-one"})
    body = {"schema_version": "apts-wpt-recon-handoff-request-v1",
            "parent_recon_run_id": "reconrun-parent", "action_id": "rareq-action"}
    first = service.handoff_to_recon("wptreq-one", body)
    assert first["status"] == "delivered"
    assert first["delivery_status"] == "DELIVERED"
    assert first["attempts"] == 1
    assert first["acknowledgement"]["recon_run_id"] == "reconrun-child"
    replay = service.handoff_to_recon("wptreq-one", body)
    assert replay["status"] == "delivered" and replay["created"] is False
    assert len(deliveries) == 1
    resumed = WPTIntakeRepository(tmp_path / "wpt-handoff.db")
    assert resumed.get_handoff("wptreq-one")["record"] == first["record"]


def test_wpt_recon_handoff_failure_stays_pending_for_restart_retry(tmp_path):
    repo = WPTIntakeRepository(tmp_path / "wpt-handoff-pending.db")
    authority = Authority()
    authority.resolve = lambda normalized: {**Authority().resolve(normalized), "execution_status": "EXECUTABLE"}
    calls = []

    def receiver(event):
        calls.append(event["handoff_id"])
        if len(calls) == 1:
            raise ConnectionError("offline")
        return {"accepted": True, "intake_id": event["intake_id"],
                "source_result_sha256": event["source_result_sha256"], "recon_run_id": "reconrun-child"}

    service = WPTIntakeService(repo, authority, Stage6Results(), token="t" * 40,
                               recon_handoff_provider=receiver)
    service.submit(request())
    service.submit_stage6_result({"schema_version": "apts-wpt-stage6-result-reference-v1",
        "intake_id": "wptreq-one", "execution_id": "exec-wpt-one", "attempt_id": "xattempt-wpt-one"})
    body = {"schema_version": "apts-wpt-recon-handoff-request-v1",
            "parent_recon_run_id": "reconrun-parent", "action_id": "rareq-action"}
    pending = service.handoff_to_recon("wptreq-one", body)
    assert pending["delivery_status"] == "PENDING" and pending["attempts"] == 1
    assert pending["last_error_code"] == "ConnectionError"
    restarted = WPTIntakeService(WPTIntakeRepository(tmp_path / "wpt-handoff-pending.db"), authority,
                                 Stage6Results(), token="t" * 40, recon_handoff_provider=receiver)
    delivered = restarted.handoff_to_recon("wptreq-one", body)
    assert delivered["delivery_status"] == "DELIVERED" and delivered["attempts"] == 2
    assert calls[0] == calls[1]


def test_wpt_recon_handoff_http_route_requires_token_and_returns_ack_status():
    from mission_orchestrator.api_service import MissionOrchestratorHandler

    class FakeIntakeService:
        configured = True
        def authenticate(self, header): return header == "Bearer " + "s" * 40
        def handoff_to_recon(self, intake_id, body):
            return {"status": "delivered", "created": True, "record": {"intake_id": intake_id},
                    "delivery_status": "DELIVERED", "attempts": 1,
                    "acknowledgement": {"accepted": True, "recon_run_id": "reconrun-child"}}
        def get_handoff(self, intake_id):
            return {"record": {"intake_id": intake_id}, "delivery_status": "DELIVERED", "attempts": 1}

    handler = type("WPTReconHandoffTestHandler", (MissionOrchestratorHandler,),
                   {"wpt_intake_service": FakeIntakeService()})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    path = f"http://127.0.0.1:{server.server_address[1]}/api/wpt/intakes/wptreq-one/recon-handoff"
    body = {"schema_version": "apts-wpt-recon-handoff-request-v1",
            "parent_recon_run_id": "reconrun-parent", "action_id": "rareq-action"}
    try:
        request = Request(path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(HTTPError) as unauthorized:
            urlopen(request, timeout=3)
        assert unauthorized.value.code == 401
        request = Request(path, data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + "s" * 40}, method="POST")
        with urlopen(request, timeout=3) as response:
            result = json.loads(response.read())
            assert response.status == 200 and result["status"] == "delivered"
        request = Request(path, headers={"Authorization": "Bearer " + "s" * 40})
        with urlopen(request, timeout=3) as response:
            assert json.loads(response.read())["delivery_status"] == "DELIVERED"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def _partial_snapshot(*, byte_limit=True, coverage=None, incomplete=("TARGET_RESPONSE",), uncertain=False):
    base = Stage6Results().snapshot
    cov = {"ACTION_PARAMETERS": "PRESENT", "AFTER_STATE": "PRESENT", "BEFORE_STATE": "PRESENT",
           "NETWORK_OBSERVATION": "PRESENT", "RESULT": "PRESENT", "SCREENSHOTS": "NOT_SUPPORTED_BY_CURRENT_FIXED_ADAPTERS",
           "STDERR": "PRESENT", "STDOUT": "PRESENT", "TARGET_AFTER_STATE": "NOT_MEASURED",
           "TARGET_BEFORE_STATE": "NOT_MEASURED", "TARGET_RESPONSE": "PARTIAL", "TOOL_IDENTITY": "PRESENT"}
    cov.update(coverage or {})
    base["runtime_result"]["observation"] = {"schema_version": "x", "network_binding": {"byte_limit_reached": byte_limit}}
    manifest = base["evidence"]["manifest"]
    manifest.update({"capture_status": "PARTIAL", "target_io_uncertain": uncertain, "coverage": cov,
                     "artifacts": [{"kind": k, "capture_complete": k not in incomplete} for k in cov if k in
                                   ("ACTION_PARAMETERS", "NETWORK_OBSERVATION", "TARGET_RESPONSE", "RESULT")]})
    return base


def _run_partial(tmp_path, snapshot):
    authority = Authority()
    authority.resolve = lambda normalized: {**Authority().resolve(normalized), "execution_status": "EXECUTABLE"}
    service = WPTIntakeService(WPTIntakeRepository(tmp_path / "wpt-partial.db"), authority,
                               Stage6Results(**snapshot), token="t" * 40)
    service.submit(request())
    return service.submit_stage6_result({"schema_version": "apts-wpt-stage6-result-reference-v1",
        "intake_id": "wptreq-one", "execution_id": "exec-wpt-one", "attempt_id": "xattempt-wpt-one"})


def test_partial_evidence_from_byte_limit_truncation_is_accepted_and_marked(tmp_path):
    created = _run_partial(tmp_path, _partial_snapshot())
    assert created["record"]["evidence"]["capture_status"] == "SEALED"
    assert created["record"]["evidence"]["response_truncated"] is True


def test_captured_evidence_is_not_marked_truncated(tmp_path):
    created = _run_partial(tmp_path, Stage6Results().snapshot)
    assert "response_truncated" not in created["record"]["evidence"]


@pytest.mark.parametrize("snapshot", [
    _partial_snapshot(byte_limit=False),
    _partial_snapshot(incomplete=("TARGET_RESPONSE", "RESULT")),
    _partial_snapshot(coverage={"STDOUT": "NOT_OBSERVED"}),
    _partial_snapshot(coverage={"NETWORK_OBSERVATION": "PARTIAL"}),
    _partial_snapshot(uncertain=True),
])
def test_partial_evidence_beyond_response_truncation_is_rejected(tmp_path, snapshot):
    with pytest.raises(Exception, match="partial beyond response truncation"):
        _run_partial(tmp_path, snapshot)


def test_recovered_partial_capture_is_still_rejected(tmp_path):
    snap = _partial_snapshot()
    snap["evidence"]["manifest"]["capture_status"] = "RECOVERED_PARTIAL"
    with pytest.raises(Exception, match="binding mismatch"):
        _run_partial(tmp_path, snap)


class _RejectingWPT:
    def __init__(self, exc):
        self.exc, self.calls = exc, 0

    def submit_stage6_result(self, payload):
        self.calls += 1
        raise self.exc


def test_permanent_rejection_is_classified_and_not_retried():
    from mission_orchestrator import mission_wpt_preparation as prep
    from execution_subsystem.execution_contract import ExecutionRequestIntegrityError
    prep._PERMANENT_RESULT_CACHE.clear()
    wpt = _RejectingWPT(ExecutionRequestIntegrityError("sealed evidence binding mismatch"))
    intake = {"intake_id": "wptreq-x"}
    runtime = {"status": "SUCCEEDED", "execution_id": "exec-x", "attempt_id": "xattempt-x"}
    first = prep._reconcile_stage6_result(wpt, intake, runtime)
    second = prep._reconcile_stage6_result(wpt, intake, runtime)
    assert first == {"status": "PENDING", "reason_code": "ExecutionRequestIntegrityError"}
    assert second == first and wpt.calls == 1
    prep._PERMANENT_RESULT_CACHE.clear()


def test_transient_failure_stays_pending_and_is_retried():
    from mission_orchestrator import mission_wpt_preparation as prep
    from execution_subsystem.execution_contract import ExecutionSourceUnavailable
    prep._PERMANENT_RESULT_CACHE.clear()
    wpt = _RejectingWPT(ExecutionSourceUnavailable("store down"))
    intake = {"intake_id": "wptreq-y"}
    runtime = {"status": "SUCCEEDED", "execution_id": "exec-y", "attempt_id": "xattempt-y"}
    assert prep._reconcile_stage6_result(wpt, intake, runtime)["status"] == "PENDING"
    prep._reconcile_stage6_result(wpt, intake, runtime)
    assert wpt.calls == 2
