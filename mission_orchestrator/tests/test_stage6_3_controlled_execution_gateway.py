from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
from pathlib import Path
import sqlite3
from threading import Thread
from uuid import uuid4

import pytest

from execution_subsystem.authorization_contract import (
    AUTHORIZATION_INTAKE_SCHEMA, ExecutionGovernanceProtocolError, ExecutionGovernanceUnavailable,
    canonical_execution_authorization_contract, utc_timestamp,
)
from execution_subsystem.authorization_repository import ExecutionAuthorizationRepository
from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.execution_contract import (
    ExecutionRequestConflict, ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    ExecutionSourceNotFound, ExecutionSourceRejected, canonical_json, with_integrity,
)
from execution_subsystem.gateway_api import ExecutionSubsystemStage63Handler, serve
from execution_subsystem.gateway_contract import (
    ADMITTED, EXECUTION_GATEWAY_CONTROL_VERSION, GATEWAY_INTAKE_SCHEMA, GATEWAY_RECORD_DOMAIN,
    canonical_execution_gateway_contract, gateway_intake_json_schema, normalize_gateway_intake,
    verify_execution_gateway_contract, verify_gateway_record,
)
from execution_subsystem.gateway_repository import ExecutionGatewayRepository
from execution_subsystem.gateway_service import ExecutionGatewayService
from execution_subsystem.governance_client import ExecutionGovernanceClient
from execution_subsystem.request_repository import ExecutionRepositoryError, ExecutionRequestRepository
from tests.test_stage6_1_canonical_execution_request_contract import http as baseline_http
from tests.test_stage6_2_authoritative_execution_authorization import (
    NOW, FakeAuthority, ctx as predecessor_ctx, seed,
)


def http(*args, **kwargs):
    code, payload, headers = baseline_http(*args, **kwargs)
    return code, headers, payload


@contextmanager
def authority_server(authority):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/api/governance/authorization/evaluate"
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            raw = canonical_json({"status": "completed", "policy_decision": authority.evaluate_authorization(payload)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class UniqueAuthority(FakeAuthority):
    def evaluate_authorization(self, payload):
        result = super().evaluate_authorization(payload)
        result["decision_id"] = "gdec-gateway-" + uuid4().hex
        result["request_id"] = "greq-gateway-" + uuid4().hex
        return result


@pytest.fixture
def ctx(predecessor_ctx):
    old, _, _, request = predecessor_ctx
    authority = UniqueAuthority()
    service = ExecutionGatewayService(ExecutionGatewayRepository(old.repository.sqlite_path),
        old.proposal_source, old.mission_source, authority, clock=lambda: NOW)
    intake = {"schema_version": GATEWAY_INTAKE_SCHEMA, "submission_id": "gwreq-stage63",
              "idempotency_key": "idem-gateway-stage63", "execution_id": request["execution_id"],
              "envelope_sha256": request["envelope"]["integrity"]["canonical_sha256"], "requested_by": "stage63-test"}
    return service, intake, authority, request


def new_submission(intake, suffix):
    return {**intake, "submission_id": "gwreq-" + suffix, "idempotency_key": "idem-gateway-" + suffix}


def new_execution(service, request, intake, suffix):
    source = {**request["envelope"]["intake"], "request_id": "ereq-" + suffix, "idempotency_key": "idem-" + suffix}
    stored = service.create_request(source)
    return {**new_submission(intake, suffix), "execution_id": stored["execution_id"],
            "envelope_sha256": stored["envelope"]["integrity"]["canonical_sha256"]}


def cloned_service(service, authority=None):
    return ExecutionGatewayService(ExecutionGatewayRepository(service.repository.sqlite_path),
        ExecutionAuthorizationProposalSource(service.proposal_source.sqlite_path),
        MissionAuthorizationSource(service.mission_source.sqlite_path), authority or UniqueAuthority(), clock=lambda: NOW)


@contextmanager
def server_for(service):
    handler = type("IsolatedStage63Handler", (ExecutionSubsystemStage63Handler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_contract_binds_exact_predecessor_and_central_gateway():
    contract = canonical_execution_gateway_contract()
    assert verify_execution_gateway_contract(contract)
    assert contract["predecessor"]["contract_sha256"] == canonical_execution_authorization_contract()["integrity"]["canonical_sha256"]
    assert contract["deliverables"] == {"execution_gateway": True, "central_execution_policy_enforcement": True}
    assert contract["repository"]["migration_level"] == 3 and contract["next_stage"] == "6.4"
    contract["adapter_boundary"]["target_dispatch_enabled"] = True
    assert not verify_execution_gateway_contract(contract)


def test_runtime_health_and_http_header_are_stage63(ctx):
    service, _, _, _ = ctx
    with server_for(service) as url:
        code, headers, health = http(url + "/health")
        assert code == 200 and "APTSExecutionSubsystem/6.3" in headers["Server"]
        assert health["control_version"] == EXECUTION_GATEWAY_CONTROL_VERSION
        assert health["execution_repository_migration_level"] == 3
        assert health["mission_repository_migration_level"] == 53 and health["pentest_repository_migration_level"] == 16
        assert health["controlled_execution_gateway_enabled"] and health["central_execution_policy_enforcement_enabled"]
        assert not health["specialist_raw_target_access"] and not health["target_dispatch_enabled"]
        assert health["registered_adapter_count"] == 0 and health["next_stage"] == "6.4"
        for route in ("/api/execution/execution-gateway-contract", "/api/contracts/controlled-execution-gateway"):
            assert verify_execution_gateway_contract(http(url + route)[2]["contract"])


def test_published_intake_schema_matches_runtime():
    schema = json.loads((Path(__file__).resolve().parents[1] / "execution_subsystem/schemas/execution_gateway_intake_v1.schema.json").read_text())
    assert schema == gateway_intake_json_schema()


def test_allow_admits_once_without_target_io_or_source_mutation(ctx):
    service, intake, authority, request = ctx
    before = [p.read_bytes() for p in (service.proposal_source.sqlite_path, service.mission_source.sqlite_path)]
    result = service.submit_execution(intake)
    record = result["record"]
    assert result["created"] and result["gateway_admitted"] and result["governance_query_performed"]
    assert record["status"] == ADMITTED and verify_gateway_record(record)
    assert record["authorization_consumed_at_admission"]
    assert not result["execution_authorized"] and not result["usable_for_dispatch"]
    assert record["semantics"]["dispatch_performed"] is False and record["semantics"]["target_actuation"] is False
    assert record["budget_before"] == {"mission": 0, "pentest": 0, "task": 0}
    assert service.repository.get(intake["execution_id"])["envelope"] == request["envelope"]
    assert before == [p.read_bytes() for p in (service.proposal_source.sqlite_path, service.mission_source.sqlite_path)]
    assert len(authority.calls) == 1


@pytest.mark.parametrize("decision,status", [("DENY", "DENIED"), ("REVIEW", "REVIEW_REQUIRED")])
def test_deny_and_review_never_reserve_budget(ctx, decision, status):
    service, intake, authority, _ = ctx
    authority.decision = decision
    rejected = service.submit_execution(intake)
    assert rejected["record"]["status"] == status and not rejected["gateway_admitted"]
    authority.decision = "ALLOW"
    allowed = service.submit_execution(new_submission(intake, "after-rejection"))
    assert allowed["gateway_admitted"] and allowed["record"]["budget_before"]["mission"] == 0


@pytest.mark.parametrize("flag", ["revoked", "emergency_stop"])
def test_fresh_stop_and_revocation_defeat_old_allow(ctx, flag):
    service, intake, authority, _ = ctx
    historical = service.authorize_execution({"schema_version": AUTHORIZATION_INTAKE_SCHEMA,
        "revalidation_id": "eauthreq-old", "idempotency_key": "idem-old", **{key: intake[key] for key in ("execution_id", "envelope_sha256", "requested_by")}})
    assert historical["execution_authorized"]
    authority.mutate = lambda decision: decision["execution_revalidation"].update({flag: True})
    result = service.submit_execution(intake)
    assert len(authority.calls) == 2 and result["record"]["status"] == "DENIED" and not result["gateway_admitted"]
    assert result["record"]["authorization_id"] != historical["authorization_id"]


@pytest.mark.parametrize("field", ["decision", "policy_decision", "authorization_id", "authorization_current", "target",
    "parameters", "command", "adapter_id", "governance_url", "constraints", "budget_before", "proposing_agent"])
def test_caller_cannot_select_authority_adapter_action_or_budgets(ctx, field):
    service, intake, authority, _ = ctx
    with pytest.raises(ExecutionRequestValidationError):
        service.submit_execution({**intake, field: "ALLOW"})
    assert not authority.calls


@pytest.mark.parametrize("field,value", [("submission_id", "gwreq-"), ("submission_id", "bad space"),
    ("execution_id", "exec-"), ("envelope_sha256", "F" * 64), ("schema_version", "old"),
    ("requested_by", " operator "), ("idempotency_key", ""), ("submission_id", None)])
def test_invalid_gateway_intake_rejected_before_revalidation(ctx, field, value):
    service, intake, authority, _ = ctx
    with pytest.raises(ExecutionRequestValidationError):
        service.submit_execution({**intake, field: value})
    assert not authority.calls


@pytest.mark.parametrize("extra", ["rate_limit", "timeout", "max_duration", "sandbox", "credentials_lease", "resource_budget", "unknown"])
def test_unsupported_gss_runtime_constraints_block_admission(ctx, extra):
    service, intake, authority, _ = ctx
    authority.mutate = lambda decision: decision["constraints"].update({extra: 1})
    result = service.submit_execution(intake)
    assert result["record"]["status"] == "BLOCKED_CONSTRAINTS" and not result["gateway_admitted"]
    assert extra in result["record"]["admission_policy"]["unsupported_constraints"]
    assert result["record"]["authorization_record"]["policy_decision"]["constraints"] == {extra: 1}


@pytest.mark.parametrize("constraint,value", [
    ("allowed_action_classes", []), ("allowed_action_classes", ["OTHER"]),
    ("allowed_techniques", []), ("allowed_techniques", ["other-technique"]),
    ("allowed_targets", []), ("allowed_targets", [{"target_type": "HOST", "target_value": "outside.internal"}]),
    ("impact_limit", "NONE"), ("risk_threshold", "NONE"),
    ("allowed_time_window", {"start_at": utc_timestamp(NOW - timedelta(minutes=5)), "end_at": utc_timestamp(NOW)}),
])
def test_authoritative_allow_cannot_override_policy_restrictions(ctx, constraint, value):
    service, intake, authority, _ = ctx
    authority.mutate = lambda decision: decision["constraints"].update({constraint: value})
    result = service.submit_execution(intake)
    assert result["record"]["authorization_record"]["decision"] == "ALLOW"
    assert result["record"]["status"] == "BLOCKED_CONSTRAINTS" and not result["gateway_admitted"]


@pytest.mark.parametrize("constraint,value", [
    ("max_actions", True), ("max_actions", -1), ("max_actions", "1"),
    ("allowed_action_classes", "ALL"), ("allowed_techniques", ["duplicate", "duplicate"]),
    ("allowed_targets", ["lab-target.internal"]), ("risk_threshold", "UNKNOWN"),
    ("requires_human_approval", 0), ("credential_usage_allowed", "true"),
    ("persistence_allowed", 1), ("destructive_actions_allowed", None),
    ("allowed_time_window", {"start_at": "bad", "end_at": "bad"}),
])
def test_malformed_gss_constraints_never_admit(ctx, constraint, value):
    service, intake, authority, _ = ctx
    authority.mutate = lambda decision: decision["constraints"].update({constraint: value})
    result = service.submit_execution(intake)
    assert result["record"]["status"] == "BLOCKED_CONSTRAINTS" and not result["gateway_admitted"]


@pytest.mark.parametrize("constraint", ["prohibited_action_classes", "prohibited_techniques", "excluded_targets"])
def test_gss_exclusions_take_precedence(ctx, constraint):
    service, intake, authority, request = ctx
    req = request["envelope"]["execution_request"]
    current = req["target"] if constraint == "excluded_targets" else req["action"]["technique" if "techniques" in constraint else "action_class"]
    authority.mutate = lambda decision: decision["constraints"].update({constraint: [current]})
    assert service.submit_execution(intake)["record"]["status"] == "BLOCKED_CONSTRAINTS"


@pytest.mark.parametrize("verified", [False, True])
def test_policy_required_human_approval_is_not_caller_authority(ctx, verified):
    service, intake, authority, _ = ctx
    def mutate(decision):
        decision["constraints"]["requires_human_approval"] = True
        decision["execution_revalidation"]["human_approval_verified"] = verified
    authority.mutate = mutate
    result = service.submit_execution(intake)
    assert result["gateway_admitted"] is verified
    assert result["record"]["status"] == (ADMITTED if verified else "REVIEW_REQUIRED")


def test_compatible_policy_constraints_are_enforced_and_preserved(ctx):
    service, intake, authority, request = ctx
    req = request["envelope"]["execution_request"]
    constraints = {"max_actions": 1, "allowed_action_classes": [req["action"]["action_class"]],
        "allowed_techniques": [req["action"]["technique"]], "allowed_targets": [req["target"]],
        "prohibited_action_classes": [], "prohibited_techniques": [], "excluded_targets": [],
        "risk_threshold": "CRITICAL", "impact_limit": "CRITICAL", "requires_human_approval": False,
        "credential_usage_allowed": False, "persistence_allowed": False, "destructive_actions_allowed": False,
        "allowed_time_window": {"start_at": utc_timestamp(NOW - timedelta(seconds=1)), "end_at": utc_timestamp(NOW + timedelta(seconds=1))}}
    authority.mutate = lambda decision: decision["constraints"].update(constraints)
    result = service.submit_execution(intake)
    assert result["gateway_admitted"]
    assert result["record"]["admission_policy"]["policy_constraints"] == constraints
    assert result["record"]["admission_policy"]["action_limits"]["mission"] == 1


@pytest.mark.parametrize("maximum", [0, 1])
def test_action_budget_is_reserved_atomically_for_distinct_executions(ctx, maximum):
    service, intake, authority, request = ctx
    authority.mutate = lambda decision: decision["constraints"].update({"max_actions": maximum})
    first = service.submit_execution(intake)
    second = service.submit_execution(new_execution(service, request, intake, "second-budget"))
    assert first["gateway_admitted"] is bool(maximum)
    assert second["record"]["status"] == "BLOCKED_BUDGET"
    assert second["record"]["budget_before"]["mission"] == maximum


def test_second_submission_for_same_execution_revalidates_then_blocks(ctx):
    service, intake, authority, _ = ctx
    first = service.submit_execution(intake)
    second = service.submit_execution(new_submission(intake, "duplicate-execution"))
    assert len(authority.calls) == 2 and second["record"]["status"] == "BLOCKED_DUPLICATE"
    assert first["record"]["authorization_id"] != second["record"]["authorization_id"]
    assert not second["gateway_admitted"]


def test_replay_and_restart_never_reauthorize_or_reserve_twice(ctx):
    service, intake, authority, _ = ctx
    first = service.submit_execution(intake)
    replay = service.submit_execution(intake)
    fresh_service = cloned_service(service)
    restart = fresh_service.submit_execution(intake)
    assert first["record"] == replay["record"] == restart["record"]
    assert len(authority.calls) == 1 and not fresh_service.governance_client.calls
    for result in (replay, restart):
        assert not result["created"] and result["historical_record"]
        assert not result["gateway_admitted"] and not result["governance_query_performed"]
        assert not result["execution_authorized"] and not result["usable_for_dispatch"]


@pytest.mark.parametrize("field", ["requested_by", "envelope_sha256", "submission_id", "idempotency_key"])
def test_idempotency_collision_cannot_change_content(ctx, field):
    service, intake, authority, _ = ctx
    service.submit_execution(intake)
    changed = {**intake, field: ("0" * 64 if field == "envelope_sha256" else "gwreq-changed" if field == "submission_id" else "changed")}
    with pytest.raises(ExecutionRequestConflict):
        service.submit_execution(changed)
    assert len(authority.calls) == 1


def test_concurrent_identical_intakes_evaluate_once_in_one_service(ctx):
    service, intake, authority, _ = ctx
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.submit_execution(deepcopy(intake)), range(8)))
    assert sum(item["created"] for item in results) == 1
    assert sum(item["gateway_admitted"] for item in results) == 1 and len(authority.calls) == 1


def _process_submit(args):
    execution, pentest, mission, intake, max_actions = args
    authority = UniqueAuthority()
    if max_actions is not None:
        authority.mutate = lambda decision: decision["constraints"].update({"max_actions": max_actions})
    service = ExecutionGatewayService(ExecutionGatewayRepository(execution), ExecutionAuthorizationProposalSource(pentest),
        MissionAuthorizationSource(mission), authority, clock=lambda: NOW)
    return service.submit_execution(intake)["record"]["status"]


def test_competing_processes_cannot_admit_same_execution_twice(ctx):
    service, intake, _, _ = ctx
    service.repository.initialize()
    paths = (str(service.repository.sqlite_path), str(service.proposal_source.sqlite_path), str(service.mission_source.sqlite_path))
    args = [(*paths, new_submission(intake, "process-" + str(i)), None) for i in range(2)]
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(_process_submit, args))
    assert sorted(results) == sorted([ADMITTED, "BLOCKED_DUPLICATE"])


def test_competing_processes_cannot_exceed_mission_action_budget(ctx):
    service, intake, _, request = ctx
    other = new_execution(service, request, intake, "process-budget-other")
    paths = (str(service.repository.sqlite_path), str(service.proposal_source.sqlite_path), str(service.mission_source.sqlite_path))
    args = [(*paths, item, 1) for item in (intake, other)]
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(_process_submit, args))
    assert sorted(results) == sorted([ADMITTED, "BLOCKED_BUDGET"])


def test_crash_after_authorization_retry_queries_fresh_authority(ctx, monkeypatch):
    service, intake, authority, _ = ctx
    append = service.repository.append_gateway
    def fail(*args, **kwargs):
        raise ExecutionRepositoryError("injected storage failure")
    monkeypatch.setattr(service.repository, "append_gateway", fail)
    with pytest.raises(ExecutionRepositoryError):
        service.submit_execution(intake)
    assert len(authority.calls) == 1 and not service.repository.list_gateway_submissions(intake["execution_id"])
    monkeypatch.setattr(service.repository, "append_gateway", append)
    result = service.submit_execution(intake)
    assert result["gateway_admitted"] and len(authority.calls) == 2
    assert len(service.repository.list_authorizations(intake["execution_id"])) == 2
    assert authority.calls[0]["context"]["execution_authorization_evaluation"]["nonce"] != authority.calls[1]["context"]["execution_authorization_evaluation"]["nonce"]


def test_expiry_after_authorization_before_admission_fails_closed(ctx, monkeypatch):
    service, intake, _, _ = ctx
    append = service.repository.append_gateway
    def delayed(*args, **kwargs):
        service.clock = lambda: NOW + timedelta(seconds=120)
        return append(*args, **kwargs)
    monkeypatch.setattr(service.repository, "append_gateway", delayed)
    with pytest.raises(ExecutionSourceRejected):
        service.submit_execution(intake)
    assert not service.repository.list_gateway_submissions(intake["execution_id"])


def test_mission_stops_after_authorization_before_commit_fails_closed(ctx, monkeypatch):
    service, intake, _, _ = ctx
    append = service.repository.append_gateway
    def stopped(*args, **kwargs):
        with sqlite3.connect(service.mission_source.sqlite_path) as conn:
            conn.execute("UPDATE mission_states SET state='ABORTED',terminal=1")
        return append(*args, **kwargs)
    monkeypatch.setattr(service.repository, "append_gateway", stopped)
    with pytest.raises(ExecutionSourceRejected):
        service.submit_execution(intake)
    assert not service.repository.list_gateway_submissions(intake["execution_id"])


def test_changed_source_context_after_authorization_is_rejected(ctx, monkeypatch):
    service, intake, _, _ = ctx
    append = service.repository.append_gateway
    def revised(*args, **kwargs):
        with sqlite3.connect(service.mission_source.sqlite_path) as conn:
            conn.execute("UPDATE mission_states SET state_version=state_version+1")
        return append(*args, **kwargs)
    monkeypatch.setattr(service.repository, "append_gateway", revised)
    with pytest.raises(ExecutionSourceRejected, match="changed"):
        service.submit_execution(intake)


@pytest.mark.parametrize("failure", [ExecutionGovernanceUnavailable, ExecutionGovernanceProtocolError])
def test_gss_failure_has_no_gateway_fallback(ctx, failure):
    service, intake, authority, _ = ctx
    def failed(_):
        raise failure("injected authority failure")
    authority.evaluate_authorization = failed
    with pytest.raises(failure):
        service.submit_execution(intake)
    assert not service.repository.list_gateway_submissions(intake["execution_id"])


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_gateway_audit_is_append_only(ctx, operation):
    service, intake, _, _ = ctx
    service.submit_execution(intake)
    with sqlite3.connect(service.repository.sqlite_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE execution_gateway_submissions SET status='DENIED'" if operation == "UPDATE" else "DELETE FROM execution_gateway_submissions")


@pytest.mark.parametrize("tamper", ["hash", "resealed-status", "index", "authorization", "budget"])
def test_tampered_gateway_storage_is_not_replayed(ctx, tamper):
    service, intake, _, _ = ctx
    result = service.submit_execution(intake)
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER execution_gateway_submissions_no_update")
        record = deepcopy(result["record"])
        if tamper == "index":
            conn.execute("UPDATE execution_gateway_submissions SET mission_id='mission-gmo-tampered'")
        elif tamper == "authorization":
            conn.execute("UPDATE execution_gateway_submissions SET authorization_id='eauth-absent'")
        else:
            if tamper in {"hash", "resealed-status"}:
                record["status"] = "DENIED"
            else:
                record["budget_before"]["mission"] = 1
            if tamper != "hash":
                record = with_integrity({k:v for k,v in record.items() if k != "integrity"}, GATEWAY_RECORD_DOMAIN)
            conn.execute("UPDATE execution_gateway_submissions SET record_json=?,record_sha256=?", (canonical_json(record), record["integrity"]["canonical_sha256"]))
    with pytest.raises(ExecutionRequestIntegrityError):
        service.submit_execution(intake)


def test_migration2_upgrade_preserves_request_and_authorization(ctx):
    service, intake, _, request = ctx
    old = ExecutionAuthorizationRepository(service.repository.sqlite_path)
    assert old.migration_level() == 2
    # Populate a real Stage 6.2 record before upgrading this same DB.
    from execution_subsystem.authorization_service import ExecutionAuthorizationService
    old_service = ExecutionAuthorizationService(old, service.proposal_source, service.mission_source, UniqueAuthority(), clock=lambda: NOW)
    auth = old_service.authorize_execution({"schema_version": AUTHORIZATION_INTAKE_SCHEMA,
        "revalidation_id": "eauthreq-upgrade", "idempotency_key": "idem-upgrade", **{k:intake[k] for k in ("execution_id", "envelope_sha256", "requested_by")}})
    assert service.repository.migration_level() == 3
    assert service.repository.get(intake["execution_id"])["envelope"] == request["envelope"]
    assert service.repository.get_authorization(auth["authorization_id"])["record"] == auth["record"]
    with pytest.raises(ExecutionRepositoryError):
        ExecutionAuthorizationRepository(service.repository.sqlite_path).initialize()


def test_gateway_cannot_report_enabled_with_a_stage62_repository(ctx):
    service = ctx[0]
    with pytest.raises(ExecutionRequestValidationError, match="gateway repository"):
        ExecutionGatewayService(ExecutionAuthorizationRepository(service.repository.sqlite_path),
            service.proposal_source, service.mission_source, UniqueAuthority(), clock=lambda: NOW)


@pytest.mark.parametrize("initial", [0, 1])
def test_empty_and_v1_upgrade_are_atomic_and_supported(tmp_path, initial):
    path = tmp_path / "upgrade.db"
    if initial:
        ExecutionRequestRepository(path).initialize()
    assert ExecutionGatewayRepository(path).migration_level() == 3


@pytest.mark.parametrize("corruption", ["foreign", "future", "incomplete", "wrong-schema"])
def test_incompatible_repository_rejected_without_downgrade(tmp_path, corruption):
    path = tmp_path / "foreign.db"
    if corruption == "foreign":
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE unrelated (value TEXT)")
    else:
        ExecutionGatewayRepository(path).initialize()
        with sqlite3.connect(path) as conn:
            if corruption == "future":
                conn.execute("UPDATE execution_repository_meta SET migration_level=4")
            elif corruption == "incomplete":
                conn.execute("DROP TABLE execution_gateway_submissions")
            else:
                conn.execute("UPDATE execution_repository_meta SET schema_version='foreign'")
    before = path.read_bytes()
    with pytest.raises(ExecutionRepositoryError):
        ExecutionGatewayRepository(path).initialize()
    assert path.read_bytes() == before


def test_same_authorization_cannot_be_consumed_by_two_submissions(ctx):
    service, intake, _, _ = ctx
    first = service.submit_execution(intake)
    with pytest.raises(ExecutionRequestConflict):
        service.repository.append_gateway(new_submission(intake, "reuse-authorization"), first["record"]["authorization_id"], final_check=lambda _: utc_timestamp(NOW))


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.1", "external.example"])
def test_gateway_control_api_cannot_bind_remote_interface(host):
    with pytest.raises(ExecutionRequestValidationError, match="loopback"):
        serve(host, 0)


def test_http_submit_replay_and_reads_are_audit_only(ctx):
    service, intake, authority, _ = ctx
    with server_for(service) as url:
        endpoint = url + "/api/execution/gateway/submissions"
        code, _, first = http(endpoint, intake)
        assert code == 201 and first["gateway_admitted"]
        code, _, replay = http(endpoint, intake)
        assert code == 200 and not replay["gateway_admitted"]
        code, _, audit = http(endpoint + "/" + first["gateway_id"])
        assert code == 200 and audit["historical_record"] and not audit["execution_authorized"]
        code, _, listing = http(endpoint + "?execution_id=" + intake["execution_id"])
        assert code == 200 and listing["count"] == 1 and not listing["usable_for_dispatch"]
    assert len(authority.calls) == 1


@pytest.mark.parametrize("query", ["?decision=ALLOW", "?limit=0", "?execution_id=exec-x&limit=501",
    "?execution_id=exec-x&execution_id=exec-y", "?execution_id=exec-x&unknown=true"])
def test_http_gateway_list_rejects_invalid_overrides(ctx, query):
    with server_for(ctx[0]) as url:
        assert http(url + "/api/execution/gateway/submissions" + query)[0] == 400


@pytest.mark.parametrize("route", ["dispatches", "results", "tool-invocations"])
def test_legacy_actuation_paths_stay_closed(ctx, route):
    with server_for(ctx[0]) as url:
        code, _, result = http(url + "/api/execution/" + route, {})
        assert code == 409 and result["error_code"] == "STAGE6_3_AUTHORIZED_ADAPTER_REQUIRED"
        assert not result["execution_authorized"]


def test_real_loopback_gss_protocol_is_used_by_gateway(ctx):
    service, intake, authority, _ = ctx
    with authority_server(authority) as base:
        service.governance_client = ExecutionGovernanceClient(base, timeout_seconds=2)
        with server_for(service) as url:
            code, _, result = http(url + "/api/execution/gateway/submissions", intake)
    assert code == 201 and result["gateway_admitted"]
    assert len(authority.calls) == 1 and verify_gateway_record(result["record"])


def test_http_gss_error_is503_without_gateway_record(ctx):
    service, intake, authority, _ = ctx
    authority.mutate = lambda decision: decision.pop("execution_revalidation")
    with server_for(service) as url:
        code, _, result = http(url + "/api/execution/gateway/submissions", intake)
        assert code == 503 and not result["execution_authorized"]
    assert not service.repository.list_gateway_submissions(intake["execution_id"])


def test_http_query_override_and_missing_request_rejected(ctx):
    service, intake, authority, _ = ctx
    with server_for(service) as url:
        endpoint = url + "/api/execution/gateway/submissions"
        assert http(endpoint + "?decision=ALLOW", intake)[0] == 400
        assert http(endpoint, {**intake, "execution_id": "exec-missing"})[0] == 404
        assert http(endpoint, {**intake, "envelope_sha256": "0" * 64})[0] == 409
    assert not authority.calls
