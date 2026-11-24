from __future__ import annotations

from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from pentest_subsystem.api_service import PentestSubsystemStage48Handler, PentestSubsystemStage49Handler
from pentest_subsystem.governance_repository import PentestGovernanceRepository
from pentest_subsystem.governance_service import PentestGovernanceService
from pentest_subsystem.lineage_contract import (
    PENTEST_LINEAGE_CONTROL_VERSION,
    PENTEST_LINEAGE_OBJECT_TYPES,
    PENTEST_LINEAGE_REPOSITORY_MIGRATION_LEVEL,
    PentestLineageValidationError,
    build_pentest_lineage_projection,
    canonical_pentest_lineage_contract,
    canonical_pentest_lineage_definition,
    verify_pentest_lineage_contract,
    verify_pentest_lineage_object,
    verify_pentest_lineage_projection,
)
from pentest_subsystem.lineage_repository import (
    PENTEST_LINEAGE_REPOSITORY_SCHEMA_VERSION,
    PentestLineageConflictError,
    PentestLineageIntegrityError,
    PentestLineageNotFoundError,
    PentestLineageRepository,
)
from pentest_subsystem.lineage_service import PentestLineageService
from pentest_subsystem.task_contract import build_pentest_task_binding
from tests.test_stage4_4_pentest_lifecycle_state import FIXED_NOW, sample_boundary, sample_pip, sample_task

CONTROL = "stage4.9-evidence-finding-lineage-foundation"
TS = "2026-09-30T18:30:00Z"


def _materialize(repo: PentestLineageRepository, *, suffix: str = ""):
    # sample_boundary/sample_pip/sample_task already generate distinct canonical UUID identities.
    boundary = sample_boundary()
    pip = sample_pip(boundary)
    task = sample_task(boundary, pip)
    binding = build_pentest_task_binding(
        boundary_payload=boundary,
        pip_payload=pip,
        task_payload=task,
        now=FIXED_NOW,
    )
    record, created = repo.create_task(task, binding)
    assert created
    return boundary, task, record


def _base(record_type: str, task_id: str, record_id: str, parent_type: str, parent_id: str, data: dict, **overrides):
    payload = {
        "record_id": record_id,
        "idempotency_key": f"idem-{record_id}",
        "record_type": record_type,
        "pentest_task_id": task_id,
        "timestamp": TS,
        "parent_reference": {"reference_type": parent_type, "reference_id": parent_id},
        "provenance": {
            "source_system": "pentest-subsystem",
            "source_kind": "TEST_FIXTURE",
            "source_id": f"src-{record_id}",
            "actor_id": "stage49-test",
            "collection_method": "SYNTHETIC",
            "metadata": {"stage": "4.9"},
        },
        "data": data,
    }
    payload.update(overrides)
    return payload


def _observation(task_id: str, record_id: str = "obs-stage49-001", parent_type="PENTEST_TASK", parent_id=None):
    return _base(
        "OBSERVATION", task_id, record_id, parent_type, parent_id or task_id,
        {"summary": "Synthetic observation for Stage 4.9 lineage validation", "observation_type": "SERVICE_BANNER", "target_ref": "host.internal", "confidence": 0.8},
    )


def _artifact(task_id: str, parent_id: str, record_id: str = "art-stage49-001"):
    return _base(
        "ARTIFACT", task_id, record_id, "OBSERVATION", parent_id,
        {"artifact_type": "TEXT_CAPTURE", "uri": "artifact://stage49/banner.txt", "content_sha256": "a" * 64, "media_type": "text/plain", "size_bytes": 128},
    )


def _evidence(task_id: str, parent_id: str, artifact_id: str, record_id: str = "evi-stage49-001"):
    return _base(
        "EVIDENCE", task_id, record_id, "ARTIFACT", parent_id,
        {"summary": "Observed service banner supports the hypothesis", "evidence_type": "SERVICE_FINGERPRINT", "target_ref": "host.internal", "artifact_refs": [artifact_id], "content_sha256": "b" * 64, "confidence": 0.9, "quality": {"authenticity": "synthetic-test"}},
    )


def _hypothesis(task_id: str, evidence_id: str, record_id: str = "hyp-stage49-001"):
    return _base(
        "HYPOTHESIS", task_id, record_id, "EVIDENCE", evidence_id,
        {"statement": "The target exposes the identified service", "status": "SUPPORTED", "confidence": 0.85, "supporting_evidence_refs": [evidence_id], "target_ref": "host.internal"},
    )


def _proposal(task_id: str, hypothesis_id: str, record_id: str = "actp-stage49-001", decision_ref: str | None = None):
    data = {
        "action_class": "TARGET_RECON",
        "capability_id": "reconnaissance",
        "target": {"target_type": "HOST", "target_value": "host.internal"},
        "summary": "Propose a bounded reconnaissance action",
    }
    if decision_ref:
        data["governance_decision_ref"] = decision_ref
    return _base("ACTION_PROPOSAL", task_id, record_id, "HYPOTHESIS", hypothesis_id, data)


def _result(task_id: str, proposal_id: str, evidence_id: str, artifact_id: str, record_id: str = "actr-stage49-001"):
    return _base(
        "ACTION_RESULT", task_id, record_id, "ACTION_PROPOSAL", proposal_id,
        {"proposal_ref": proposal_id, "outcome": "NOT_EXECUTED", "summary": "Synthetic result record only; no target action was executed", "result_origin": "TEST_FIXTURE", "evidence_refs": [evidence_id], "artifact_refs": [artifact_id]},
    )


def _finding(task_id: str, result_id: str, evidence_id: str, hypothesis_id: str, record_id: str = "fnd-stage49-001"):
    return _base(
        "FINDING", task_id, record_id, "ACTION_RESULT", result_id,
        {"title": "Exposed synthetic service", "status": "CONFIRMED", "severity": "LOW", "target_ref": "host.internal", "hypothesis_ref": hypothesis_id, "supporting_evidence_refs": [evidence_id], "contradicting_evidence_refs": [], "impact_assessment": "Low-impact synthetic finding for lineage testing", "confidence": 0.9},
    )


def _governance_request(boundary, task):
    return {
        "evaluation_id": f"eval-{task['pentest_task_id']}",
        "idempotency_key": f"idem-eval-{task['pentest_task_id']}",
        "pentest_task_id": task["pentest_task_id"],
        "boundary": boundary,
        "capability_id": "reconnaissance",
        "action_class": "TARGET_RECON",
        "target": deepcopy(boundary["scope"]["targets"][0]),
        "requested_at": "2026-09-02T12:00:00Z",
        "estimated_impact": "LOW",
        "rate_cost": 1,
        "active_concurrency": 1,
        "stop_signals": [],
        "metadata": {"test": True},
    }


def _full_chain(service: PentestLineageService, task_id: str):
    obs = service.record_lineage_object(_observation(task_id))["record"]
    art = service.record_lineage_object(_artifact(task_id, obs["identity"]["record_id"]))["record"]
    evi = service.record_lineage_object(_evidence(task_id, art["identity"]["record_id"], art["identity"]["record_id"]))["record"]
    hyp = service.record_lineage_object(_hypothesis(task_id, evi["identity"]["record_id"]))["record"]
    prop = service.record_lineage_object(_proposal(task_id, hyp["identity"]["record_id"]))["record"]
    res = service.record_lineage_object(_result(task_id, prop["identity"]["record_id"], evi["identity"]["record_id"], art["identity"]["record_id"]))["record"]
    finding = service.record_lineage_object(_finding(task_id, res["identity"]["record_id"], evi["identity"]["record_id"], hyp["identity"]["record_id"]))["record"]
    return obs, art, evi, hyp, prop, res, finding


def _start_server(tmp_path: Path):
    service = PentestLineageService(PentestLineageRepository(tmp_path / "pentest.db"))
    handler = type("IsolatedStage49Handler", (PentestSubsystemStage49Handler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, service, f"http://127.0.0.1:{server.server_address[1]}"


def _post(url: str, payload: dict):
    req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=5) as response:
        return response.status, json.loads(response.read().decode())


def test_01_control_binds_exact_stage48_predecessor_migration_and_next_stage():
    c = canonical_pentest_lineage_contract()
    assert c["control_version"] == CONTROL == PENTEST_LINEAGE_CONTROL_VERSION
    assert c["predecessor"]["control"] == "stage4.8-governance-scope-roe-enforcement"
    assert c["repository"]["migration_level"] == 7 == PENTEST_LINEAGE_REPOSITORY_MIGRATION_LEVEL
    assert c["next_stage"] == "4.10"


def test_02_control_is_hash_bound_and_tamper_fails_closed():
    c = canonical_pentest_lineage_contract()
    assert verify_pentest_lineage_contract(c)
    bad = deepcopy(c)
    bad["runtime"]["execution_intake_enabled"] = True
    assert not verify_pentest_lineage_contract(bad)


def test_03_contract_contains_exact_roadmap_object_types_and_deliverables():
    c = canonical_pentest_lineage_contract()
    assert c["object_model"]["object_types"] == list(PENTEST_LINEAGE_OBJECT_TYPES)
    assert c["deliverables"] == {"evidence_model": True, "finding_model": True, "pentest_lineage_model": True}


def test_04_definition_requires_all_five_roadmap_metadata_categories():
    d = canonical_pentest_lineage_definition()
    assert d["required_metadata"] == ["identity", "provenance", "timestamp", "parent_reference", "integrity"]


def test_05_repository_migrates_to_level_seven_and_adds_append_only_lineage_store(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    assert repo.migration_level() == 7
    assert repo.metadata()["schema_version"] == PENTEST_LINEAGE_REPOSITORY_SCHEMA_VERSION
    with sqlite3.connect(repo.sqlite_path) as conn:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
        triggers = {r[0] for r in conn.execute("select name from sqlite_master where type='trigger'")}
    assert "pentest_lineage_objects" in tables
    assert "trg_pentest_lineage_objects_no_update" in triggers
    assert "trg_pentest_lineage_objects_no_delete" in triggers


def test_06_observation_materializes_identity_provenance_timestamp_parent_and_integrity(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, task_record = _materialize(repo)
    result = PentestLineageService(repo).record_lineage_object(_observation(task["pentest_task_id"]))
    record = result["record"]
    assert verify_pentest_lineage_object(record)
    assert record["identity"]["mission_id"] == task_record["mission_id"]
    assert record["identity"]["pentest_id"] == task_record["pentest_id"]
    assert record["parent_reference"]["reference_type"] == "PENTEST_TASK"
    assert record["parent_reference"]["reference_sha256"] == task_record["task_contract_sha256"]
    assert record["provenance"]["source_system"] == "pentest-subsystem"
    assert record["timestamp"].endswith("Z")


def test_07_artifact_forbids_inline_content_and_requires_content_hash(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    obs = svc.record_lineage_object(_observation(task["pentest_task_id"]))["record"]
    bad = _artifact(task["pentest_task_id"], obs["identity"]["record_id"])
    bad["data"]["base64"] = "AA=="
    with pytest.raises(PentestLineageValidationError, match="inline payload"):
        svc.record_lineage_object(bad)


def test_08_evidence_requires_artifact_refs_to_canonical_same_task_artifacts(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    obs = svc.record_lineage_object(_observation(task["pentest_task_id"]))["record"]
    art = svc.record_lineage_object(_artifact(task["pentest_task_id"], obs["identity"]["record_id"]))["record"]
    evi = svc.record_lineage_object(_evidence(task["pentest_task_id"], art["identity"]["record_id"], art["identity"]["record_id"]))["record"]
    assert evi["identity"]["record_type"] == "EVIDENCE"
    assert evi["data"]["artifact_refs"] == [art["identity"]["record_id"]]


def test_09_evidence_reference_to_non_artifact_fails_closed(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    obs = svc.record_lineage_object(_observation(task["pentest_task_id"]))["record"]
    payload = _base("EVIDENCE", task["pentest_task_id"], "evi-stage49-badtype", "OBSERVATION", obs["identity"]["record_id"], {"summary": "bad", "evidence_type": "TEST", "artifact_refs": [obs["identity"]["record_id"]]})
    with pytest.raises(PentestLineageValidationError, match="ARTIFACT"):
        svc.record_lineage_object(payload)


def test_10_hypothesis_supporting_refs_must_be_same_task_evidence(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    obs = svc.record_lineage_object(_observation(task["pentest_task_id"]))["record"]
    bad = _base("HYPOTHESIS", task["pentest_task_id"], "hyp-stage49-bad", "OBSERVATION", obs["identity"]["record_id"], {"statement": "x", "status": "OPEN", "confidence": 0.2, "supporting_evidence_refs": [obs["identity"]["record_id"]]})
    with pytest.raises(PentestLineageValidationError, match="EVIDENCE"):
        svc.record_lineage_object(bad)


def test_11_action_proposal_can_bind_existing_scope_roe_decision_without_turning_it_into_authorization(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    boundary, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    obs, art, evi, hyp, *_ = _full_chain_until_hypothesis(svc, task["pentest_task_id"])
    decision = svc.evaluate_scope_roe(_governance_request(boundary, task))["decision"]
    proposal = svc.record_lineage_object(_proposal(task["pentest_task_id"], hyp["identity"]["record_id"], decision_ref=decision["decision_id"]))
    assert proposal["record"]["data"]["governance_decision_ref"] == decision["decision_id"]
    assert proposal["authorization_minted"] is False
    assert proposal["execution_started"] is False


def _full_chain_until_hypothesis(service: PentestLineageService, task_id: str):
    obs = service.record_lineage_object(_observation(task_id))["record"]
    art = service.record_lineage_object(_artifact(task_id, obs["identity"]["record_id"]))["record"]
    evi = service.record_lineage_object(_evidence(task_id, art["identity"]["record_id"], art["identity"]["record_id"]))["record"]
    hyp = service.record_lineage_object(_hypothesis(task_id, evi["identity"]["record_id"]))["record"]
    return obs, art, evi, hyp


def test_12_action_proposal_cross_task_governance_decision_is_rejected(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    b1, t1, _ = _materialize(repo, suffix="a")
    b2, t2, _ = _materialize(repo, suffix="b")
    svc = PentestLineageService(repo)
    _, _, _, hyp2 = _full_chain_until_hypothesis(svc, t2["pentest_task_id"])
    decision1 = svc.evaluate_scope_roe(_governance_request(b1, t1))["decision"]
    with pytest.raises(PentestLineageValidationError, match="another pentest task"):
        svc.record_lineage_object(_proposal(t2["pentest_task_id"], hyp2["identity"]["record_id"], decision_ref=decision1["decision_id"]))


def test_13_action_result_parent_must_match_proposal_ref(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    obs, art, evi, hyp = _full_chain_until_hypothesis(svc, task["pentest_task_id"])
    p1 = svc.record_lineage_object(_proposal(task["pentest_task_id"], hyp["identity"]["record_id"], record_id="actp-stage49-a"))["record"]
    p2 = svc.record_lineage_object(_proposal(task["pentest_task_id"], hyp["identity"]["record_id"], record_id="actp-stage49-b"))["record"]
    bad = _result(task["pentest_task_id"], p1["identity"]["record_id"], evi["identity"]["record_id"], art["identity"]["record_id"])
    bad["parent_reference"] = {"reference_type": "ACTION_PROPOSAL", "reference_id": p2["identity"]["record_id"]}
    with pytest.raises(PentestLineageValidationError, match="parent must be the same"):
        svc.record_lineage_object(bad)


def test_14_finding_requires_nonempty_supporting_evidence(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    obs, art, evi, hyp, prop, res, _ = _full_chain(svc, task["pentest_task_id"])
    bad = _finding(task["pentest_task_id"], res["identity"]["record_id"], evi["identity"]["record_id"], hyp["identity"]["record_id"], record_id="fnd-stage49-empty")
    bad["data"]["supporting_evidence_refs"] = []
    with pytest.raises(PentestLineageValidationError, match="at least one"):
        svc.record_lineage_object(bad)


def test_15_full_canonical_chain_reconstructs_single_head_and_all_type_counts(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, task_record = _materialize(repo)
    svc = PentestLineageService(repo)
    *_, finding = _full_chain(svc, task["pentest_task_id"])
    result = svc.get_task_lineage(task["pentest_task_id"])
    projection = result["projection"]
    assert verify_pentest_lineage_projection(projection)
    assert projection["root"]["reference_sha256"] == task_record["task_contract_sha256"]
    assert projection["root"]["pip_id"] == task_record["pip_id"]
    assert projection["node_count"] == 7
    assert all(projection["type_counts"][kind] == 1 for kind in PENTEST_LINEAGE_OBJECT_TYPES)
    assert projection["heads"] == [finding["identity"]["record_id"]]


def test_16_projection_integrity_detects_tamper():
    fake_task = {
        "pentest_task_id": "ptask-x", "mission_id": "mission-x", "pentest_id": "pentest-x", "upstream_task_id": "task-x", "pip_id": "pip-x",
        "task_contract_sha256": "1"*64, "task_binding_sha256": "2"*64,
        "task": {"pip_reference": {"pip_artifact_sha256": "3"*64, "pip_binding_sha256": "4"*64}},
    }
    p = build_pentest_lineage_projection(task_record=fake_task, records=[])
    assert verify_pentest_lineage_projection(p)
    bad = deepcopy(p); bad["node_count"] = 1
    assert not verify_pentest_lineage_projection(bad)


def test_17_exact_replay_is_idempotent_and_preserves_sequence(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    payload = _observation(task["pentest_task_id"])
    a = svc.record_lineage_object(payload)
    b = svc.record_lineage_object(payload)
    assert a["created"] is True and b["replayed"] is True
    assert a["sequence_no"] == b["sequence_no"] == 1
    assert len(repo.list_lineage_objects(task["pentest_task_id"])) == 1


def test_18_idempotency_aliasing_different_immutable_content_conflicts(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    first = _observation(task["pentest_task_id"])
    svc.record_lineage_object(first)
    changed = _observation(task["pentest_task_id"], record_id="obs-stage49-002")
    changed["idempotency_key"] = first["idempotency_key"]
    with pytest.raises(PentestLineageConflictError):
        svc.record_lineage_object(changed)


def test_19_missing_parent_fails_closed(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    payload = _base("EVIDENCE", task["pentest_task_id"], "evi-stage49-missing", "OBSERVATION", "obs-missing", {"summary": "x", "evidence_type": "TEST"})
    with pytest.raises(PentestLineageNotFoundError):
        svc.record_lineage_object(payload)


def test_20_cross_task_parent_is_forbidden(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, t1, _ = _materialize(repo, suffix="a")
    _, t2, _ = _materialize(repo, suffix="b")
    svc = PentestLineageService(repo)
    obs1 = svc.record_lineage_object(_observation(t1["pentest_task_id"], record_id="obs-stage49-cross-a"))["record"]
    payload = _base("EVIDENCE", t2["pentest_task_id"], "evi-stage49-cross", "OBSERVATION", obs1["identity"]["record_id"], {"summary": "x", "evidence_type": "TEST"})
    with pytest.raises(PentestLineageValidationError, match="cross-task"):
        svc.record_lineage_object(payload)


def test_21_caller_supplied_parent_hash_must_match_authoritative_parent(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    obs = svc.record_lineage_object(_observation(task["pentest_task_id"]))["record"]
    payload = _base("ARTIFACT", task["pentest_task_id"], "art-stage49-badhash", "OBSERVATION", obs["identity"]["record_id"], {"artifact_type": "TEXT_CAPTURE", "uri": "artifact://x", "content_sha256": "a"*64})
    payload["parent_reference"]["reference_sha256"] = "0" * 64
    with pytest.raises(PentestLineageValidationError, match="hash does not match"):
        svc.record_lineage_object(payload)


def test_22_restart_preserves_records_and_projection(tmp_path):
    db = tmp_path / "pentest.db"
    repo = PentestLineageRepository(db)
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    _full_chain(svc, task["pentest_task_id"])
    first = svc.get_task_lineage(task["pentest_task_id"])["projection"]
    restarted = PentestLineageService(PentestLineageRepository(db))
    second = restarted.get_task_lineage(task["pentest_task_id"])["projection"]
    assert first == second
    assert restarted.repository.migration_level() == 7


def test_23_persisted_canonical_hash_tamper_is_detected_on_read(tmp_path):
    db = tmp_path / "pentest.db"
    repo = PentestLineageRepository(db)
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    obs = svc.record_lineage_object(_observation(task["pentest_task_id"]))["record"]
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TRIGGER trg_pentest_lineage_objects_no_update")
        conn.execute("UPDATE pentest_lineage_objects SET canonical_sha256=? WHERE record_id=?", ("0"*64, obs["identity"]["record_id"]))
        conn.commit()
    with pytest.raises(PentestLineageIntegrityError):
        PentestLineageRepository(db).get_lineage_object(obs["identity"]["record_id"])


def test_24_append_only_store_rejects_update_and_delete(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    obs = PentestLineageService(repo).record_lineage_object(_observation(task["pentest_task_id"]))["record"]
    with sqlite3.connect(repo.sqlite_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE pentest_lineage_objects SET occurred_at=? WHERE record_id=?", ("x", obs["identity"]["record_id"]))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM pentest_lineage_objects WHERE record_id=?", (obs["identity"]["record_id"],))


def test_25_health_activates_stage49_and_keeps_execution_disabled(tmp_path):
    h = PentestLineageService(PentestLineageRepository(tmp_path / "pentest.db")).health()
    assert h["control_version"] == CONTROL
    assert h["pentest_repository_migration_level"] == 7
    assert h["stage4_9_evidence_model_enabled"] is True
    assert h["stage4_9_finding_model_enabled"] is True
    assert h["stage4_9_lineage_projection_enabled"] is True
    assert h["stage4_9_execution_intake_enabled"] is False
    assert h["stage4_9_tool_invocation_enabled"] is False
    assert h["stage4_9_target_actuation"] is False
    assert h["stage4_9_next_stage"] == "4.10"


def test_26_http_contract_record_query_projection_and_execution_boundary(tmp_path):
    server, thread, svc, base = _start_server(tmp_path)
    try:
        _, task, _ = _materialize(svc.repository)
        with urlopen(base + "/api/pentest/lineage-contract", timeout=5) as resp:
            assert json.loads(resp.read())["control_version"] == CONTROL
        status, body = _post(base + "/api/pentest/lineage/records", _observation(task["pentest_task_id"]))
        assert status == 201 and body["record"]["identity"]["record_type"] == "OBSERVATION"
        rid = body["record"]["identity"]["record_id"]
        with urlopen(base + "/api/pentest/lineage/records/" + rid, timeout=5) as resp:
            assert json.loads(resp.read())["record_id"] == rid
        with urlopen(base + f"/api/pentest/tasks/{task['pentest_task_id']}/lineage", timeout=5) as resp:
            assert json.loads(resp.read())["record_count"] == 1
        req = Request(base + "/api/execution/dispatches", data=b"{}", headers={"Content-Type":"application/json"}, method="POST")
        with pytest.raises(HTTPError) as exc:
            urlopen(req, timeout=5)
        assert exc.value.code == 409
        assert json.loads(exc.value.read())["error_code"] == "STAGE4_9_EXECUTION_INTAKE_NOT_ENABLED"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_27_historical_stage48_handler_is_preserved():
    assert PentestSubsystemStage48Handler.server_version == "APTSPentestSubsystem/4.8"
    assert PentestSubsystemStage49Handler.server_version == "APTSPentestSubsystem/4.9"


def test_28_upgrade_from_stage48_database_preserves_governance_decision(tmp_path):
    db = tmp_path / "upgrade.db"
    old = PentestGovernanceRepository(db)
    assert old.migration_level() == 6
    boundary, task, _ = _materialize(old)
    decision = PentestGovernanceService(old).evaluate_scope_roe(_governance_request(boundary, task))["decision"]
    new = PentestLineageRepository(db)
    assert new.migration_level() == 7
    assert new.get_scope_roe_decision(decision["decision_id"])["decision"] == decision


def test_29_typed_evidence_and_finding_queries_and_lists(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    _, _, evi, _, _, _, finding = _full_chain(svc, task["pentest_task_id"])
    assert svc.get_evidence(evi["identity"]["record_id"])["record_type"] == "EVIDENCE"
    assert svc.get_finding(finding["identity"]["record_id"])["record_type"] == "FINDING"
    assert svc.list_task_evidence(task["pentest_task_id"])["count"] == 1
    assert svc.list_task_findings(task["pentest_task_id"])["count"] == 1


def test_30_typed_query_rejects_wrong_object_kind(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    obs = svc.record_lineage_object(_observation(task["pentest_task_id"]))["record"]
    with pytest.raises(PentestLineageNotFoundError):
        svc.get_evidence(obs["identity"]["record_id"])


def test_31_action_result_recording_never_executes_tools_or_targets(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    obs, art, evi, hyp = _full_chain_until_hypothesis(svc, task["pentest_task_id"])
    prop = svc.record_lineage_object(_proposal(task["pentest_task_id"], hyp["identity"]["record_id"]))["record"]
    result = svc.record_lineage_object(_result(task["pentest_task_id"], prop["identity"]["record_id"], evi["identity"]["record_id"], art["identity"]["record_id"]))
    assert result["record"]["data"]["outcome"] == "NOT_EXECUTED"
    assert result["execution_started"] is False
    assert result["tool_invocation_performed"] is False
    assert result["external_network_io_performed"] is False
    assert result["target_actuation"] is False


def test_32_invalid_parent_type_is_rejected_before_persistence(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    payload = _observation(task["pentest_task_id"])
    payload["parent_reference"] = {"reference_type": "EVIDENCE", "reference_id": "evi-x"}
    with pytest.raises(PentestLineageValidationError, match="not an allowed parent"):
        PentestLineageService(repo).record_lineage_object(payload)


def test_33_timestamp_must_be_timezone_aware(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    payload = _observation(task["pentest_task_id"])
    payload["timestamp"] = "2026-09-30T18:30:00"
    with pytest.raises(PentestLineageValidationError, match="timezone"):
        PentestLineageService(repo).record_lineage_object(payload)


def test_34_record_id_prefix_is_type_bound(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    payload = _observation(task["pentest_task_id"], record_id="evi-wrong-prefix")
    with pytest.raises(PentestLineageValidationError, match="must start"):
        PentestLineageService(repo).record_lineage_object(payload)


def test_35_duplicate_reference_lists_are_rejected(tmp_path):
    repo = PentestLineageRepository(tmp_path / "pentest.db")
    _, task, _ = _materialize(repo)
    svc = PentestLineageService(repo)
    obs = svc.record_lineage_object(_observation(task["pentest_task_id"]))["record"]
    art = svc.record_lineage_object(_artifact(task["pentest_task_id"], obs["identity"]["record_id"]))["record"]
    payload = _evidence(task["pentest_task_id"], art["identity"]["record_id"], art["identity"]["record_id"])
    payload["data"]["artifact_refs"] = [art["identity"]["record_id"], art["identity"]["record_id"]]
    with pytest.raises(PentestLineageValidationError, match="duplicate"):
        svc.record_lineage_object(payload)


def test_36_contract_explicitly_preserves_stage6_controlled_execution_authority():
    c = canonical_pentest_lineage_contract()
    assert c["runtime"]["authorization_minting_enabled"] is False
    assert c["runtime"]["execution_intake_enabled"] is False
    assert c["runtime"]["tool_invocation_enabled"] is False
    assert c["runtime"]["external_network_io_performed"] is False
    assert c["runtime"]["target_actuation"] is False
    assert "STAGE6_REMAINS_AUTHORITY_FOR_CONTROLLED_EXECUTION" in c["invariants"]
