from __future__ import annotations

from copy import deepcopy
import sqlite3

import pytest

from pentest_subsystem.reconnaissance import (
    RECON_BOOTSTRAP_REQUEST_SCHEMA_VERSION,
    ReconnaissanceAgentConflict,
    ReconnaissanceAgentValidationError,
    ReconnaissanceAgentRepository,
    ReconnaissanceAgentService,
    canonical_reconnaissance_bootstrap_contract,
    normalize_reconnaissance_bootstrap_request,
    verify_reconnaissance_agent_contract,
    canonical_reconnaissance_agent_contract,
)
from tests.test_stage5_2_reconnaissance_agent import (
    _post,
    _get,
    _start_repo,
    _start_server,
    materialize,
    start_payload,
)


def bootstrap_request(suffix="bootstrap"):
    return {
        "schema_version": RECON_BOOTSTRAP_REQUEST_SCHEMA_VERSION,
        "request_id": f"reconbootreq-{suffix}",
        "idempotency_key": f"idem-reconboot-{suffix}",
        "actor": "mission-bootstrap-service",
    }


def test_bootstrap_contract_is_hash_bound_and_explicitly_non_executing():
    contract = canonical_reconnaissance_bootstrap_contract()
    assert contract["caller_supplied_target_or_scope"] is False
    assert contract["creates_recon_run"] is False
    assert contract["creates_observations"] is False
    assert contract["creates_evidence"] is False
    assert contract["execution_started"] is False
    assert contract["external_network_io_performed"] is False
    assert verify_reconnaissance_agent_contract(canonical_reconnaissance_agent_contract())


def test_bootstrap_request_rejects_caller_target_scope_and_unknown_fields():
    valid = normalize_reconnaissance_bootstrap_request(bootstrap_request())
    assert valid["schema_version"] == RECON_BOOTSTRAP_REQUEST_SCHEMA_VERSION
    for field, value in (("target", {"target_type": "URL", "target_value": "https://example.test"}),
                         ("scope", {"targets": []}), ("observations", [])):
        invalid = bootstrap_request("invalid-" + field)
        invalid[field] = value
        with pytest.raises(ReconnaissanceAgentValidationError):
            normalize_reconnaissance_bootstrap_request(invalid)


def test_bootstrap_uses_immutable_task_target_without_creating_run_or_progress(tmp_path):
    repo, _, task, orchestration, _, _ = _start_repo(tmp_path, "bootstrap-record")
    before = repo.get_orchestration(orchestration["orchestration_id"])
    bootstrap, created = repo.create_recon_bootstrap(orchestration["orchestration_id"], bootstrap_request())

    assert created is True
    assert bootstrap["bootstrap_status"] == "READY_FOR_COLLECTION"
    assert bootstrap["target"] == task["target"]
    assert bootstrap["task_scope"] == task["scope"]
    assert bootstrap["source"] == "IMMUTABLE_PENTEST_TASK_DECLARATION"
    assert bootstrap["semantics"]["target_is_observed"] is False
    assert bootstrap["semantics"]["observation_created"] is False
    assert bootstrap["semantics"]["evidence_created"] is False
    assert bootstrap["semantics"]["execution_started"] is False
    assert bootstrap["semantics"]["authorization_minted"] is False
    assert repo.get_orchestration_recon_run(orchestration["orchestration_id"]) is None

    after = repo.get_orchestration(orchestration["orchestration_id"])
    assert after["task_graph"] == before["task_graph"]
    with sqlite3.connect(repo.sqlite_path) as conn:
        assert conn.execute("SELECT count(*) FROM pentest_recon_bootstraps").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM pentest_recon_runs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM pentest_lineage_objects").fetchone()[0] == 0


def test_bootstrap_is_idempotent_and_conflicting_replay_fails(tmp_path):
    repo, _, _, orchestration, _, _ = _start_repo(tmp_path, "bootstrap-idempotency")
    oid = orchestration["orchestration_id"]
    first, created = repo.create_recon_bootstrap(oid, bootstrap_request("stable"))
    replay, replay_created = repo.create_recon_bootstrap(oid, bootstrap_request("stable"))
    assert created is True and replay_created is False
    assert replay["bootstrap_id"] == first["bootstrap_id"]

    with pytest.raises(ReconnaissanceAgentConflict):
        repo.create_recon_bootstrap(oid, bootstrap_request("changed"))


def test_bootstrap_contract_and_http_create_get_round_trip(tmp_path):
    server, thread, service, base = _start_server(tmp_path)
    try:
        repo = service.repository
        _, _, task, _, _ = materialize(repo)
        orchestration, _, _, _ = repo.start_orchestration(
            task["pentest_task_id"], start_payload("bootstrap-http")
        )
        oid = orchestration["orchestration_id"]
        status, _, contract_reply = _get(base + "/api/contracts/reconnaissance-bootstrap")
        assert status == 200
        assert contract_reply["contract"]["integrity"]["canonical_sha256"] == canonical_reconnaissance_bootstrap_contract()["integrity"]["canonical_sha256"]

        status, created = _post(base + f"/api/pentest/agentic-orchestrations/{oid}/reconnaissance/bootstrap", bootstrap_request("http"))
        assert status == 201 and created["status"] == "ready_for_collection"
        assert created["recon_run_created"] is False and created["execution_started"] is False
        bootstrap_id = created["bootstrap"]["bootstrap_id"]
        status, _, fetched = _get(base + f"/api/pentest/reconnaissance-bootstraps/{bootstrap_id}")
        assert status == 200
        assert fetched["bootstrap"]["target"] == task["target"]

        status, replay = _post(base + f"/api/pentest/agentic-orchestrations/{oid}/reconnaissance/bootstrap", bootstrap_request("http"))
        assert status == 200 and replay["replayed"] is True
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
