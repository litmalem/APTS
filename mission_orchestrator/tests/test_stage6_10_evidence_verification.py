from copy import deepcopy
import json
from pathlib import Path
import hashlib
import os
import shutil
import sys
import xml.etree.ElementTree as ET

import pytest

from execution_subsystem.apts_acceptance_contract import canonical_apts_acceptance_contract
from execution_subsystem.cti_feedback_contract import FEEDBACK_DOMAIN, KNOWLEDGE_DOMAIN
from execution_subsystem.execution_contract import with_integrity, sha256_hex, canonical_json
from mission_orchestrator.global_mission_acceptance_gate import canonical_global_mission_acceptance_gate_contract
from mission_orchestrator.replan_candidate import REPLAN_CANDIDATE_HASH_DOMAIN, REPLAN_CANDIDATE_PAYLOAD_HASH_DOMAIN, verify_replan_candidate_contract
from mission_orchestrator.replan_validation import evaluate_replan_candidate_feasibility
from pentest_subsystem.agentic_pentest_acceptance_gate import canonical_agentic_pentest_acceptance_gate_contract
from run.stage6_10_acceptance import validate_preflight
from run.stage6_10_audit import audit_connected, audit_files
from run.stage6_10_regression import verify_batch, verify_report, source_snapshot, digest, write_json, SCHEMA, REQUIRED_GATES, test_key as node_key, strict_json, safe_artifact, groups_for

FIXTURES = Path(__file__).resolve().parents[1] / "acceptance" / "fixtures"


@pytest.fixture
def exports():
    return strict_json(FIXTURES / "stage6_10_knowledge.json"), strict_json(FIXTURES / "stage6_10_mission_bundle.json")


def test_connected_offline_audit_reconstructs_exact_successor_without_authorizing(exports):
    result = audit_connected(*exports)
    assert result["status"] == "VERIFIED_CONNECTED_INTERNAL_LINEAGE"
    assert result["successor_plan_version"] == 2 and result["hypothesis_outcome"] == "INCONCLUSIVE"
    assert not result["execution_authorized"] and not result["mission_success_declared"]


@pytest.mark.parametrize("area", ["retained_bytes", "knowledge_revision", "assessment", "mission_events", "scope", "planned_task", "snapshot"])
def test_tampered_export_does_not_pass_connected_audit(exports, area):
    knowledge, bundle = exports
    revision = knowledge["revisions"][-1]
    if area == "retained_bytes":
        revision["feedback_export"]["post_action_export"]["vep_export"]["artifacts"][0]["payload_base64"] = "e30="
    elif area == "knowledge_revision": revision["record"]["previous_revision_sha256"] = "0"*64
    elif area == "assessment": revision["record"]["assessment"]["hypothesis_outcome"] = "CONFIRMED"
    elif area == "mission_events": bundle["records"]["mission_events"].pop()
    elif area == "scope": bundle["records"]["scope_versions"] = []
    elif area == "planned_task": bundle["records"]["planned_tasks"][0]["planned_task_id"] = "ptask-forged"
    else: bundle["records"]["replan_snapshots"][0]["replan_snapshot_contract"]["cti_feedback_context"] = None
    with pytest.raises(ValueError): audit_connected(knowledge, bundle)


@pytest.mark.parametrize("change", ["remove", "hash", "review", "add_to_unbound_snapshot"])
def test_resigned_cti_requirements_are_checked_against_trusted_snapshot(exports, change):
    _, bundle = exports
    records = bundle["records"]
    candidate = deepcopy(records["replan_candidates"][0]["replan_candidate_contract"])
    snapshot = deepcopy(records["replan_snapshots"][0]["replan_snapshot_contract"])
    payload = candidate["candidate_successor_plan"]
    if change == "remove": payload.pop("cti_feedback_requirements")
    elif change == "hash": payload["cti_feedback_requirements"]["knowledge_sha256"] = "0"*64
    elif change == "review": payload["cti_feedback_requirements"]["review_required"] = not payload["cti_feedback_requirements"]["review_required"]
    else:
        # A structurally valid candidate must still derive its entire payload
        # from the trusted CTI snapshot. Removing snapshot context is rejected.
        snapshot.pop("cti_feedback_context")
    payload_core = {k: v for k, v in payload.items() if k not in {"candidate_status", "candidate_only", "source_plan_version",
        "candidate_plan_version", "source_plan_generation", "candidate_plan_generation", "candidate_payload_sha256"}}
    payload["candidate_payload_sha256"] = sha256_hex({"hash_domain": REPLAN_CANDIDATE_PAYLOAD_HASH_DOMAIN, "payload": payload_core})
    core = {k: v for k, v in candidate.items() if k != "canonical_sha256"}
    candidate["canonical_sha256"] = sha256_hex({"hash_domain": REPLAN_CANDIDATE_HASH_DOMAIN, "contract": core})
    result = evaluate_replan_candidate_feasibility(candidate, snapshot)
    assert not result["feasible"]
    if change == "review":
        assert verify_replan_candidate_contract(candidate)
        assert "DETERMINISTIC_REPRODUCTION" in result["rejection_codes"]


def make_junit(path, nodes, kind=None, *, headers=None):
    suite = ET.Element("testsuite", {"tests": str(len(nodes)), "failures": "0", "errors": "0", "skipped": "0"})
    for node in nodes:
        classname, name = node_key(node)
        ET.SubElement(suite, "testcase", {"classname": classname, "name": name})
    if kind:
        ET.SubElement(suite.find("testcase"), kind)
        suite.set({"failure": "failures", "error": "errors", "skipped": "skipped"}[kind], "1")
    if headers: suite.attrib.update(headers)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def test_junit_exact_coverage_accepts_nested_classes_and_ipv6_ids(tmp_path):
    nodes = ["tests/test_x.py::TestGroup::test_ipv6[http://[::1]:8080]", "tests/test_x.py::test_other"]
    path = tmp_path / "junit.xml"; make_junit(path, nodes)
    assert verify_batch(path, nodes, 0)


@pytest.mark.parametrize("failure", ["failure", "error", "skipped", "duplicate", "missing", "foreign", "false_totals", "nonzero_exit", "invalid_xml", "entity"])
def test_junit_and_exit_status_fail_closed(tmp_path, failure):
    nodes = ["tests/test_a.py::test_one", "tests/test_a.py::test_two"]
    rows = list(nodes)
    if failure == "duplicate": rows = [nodes[0], nodes[0]]
    elif failure == "missing": rows.pop()
    elif failure == "foreign": rows[1] = "tests/test_b.py::test_two"
    path = tmp_path / "junit.xml"
    make_junit(path, rows, failure if failure in {"failure", "error", "skipped"} else None,
        headers={"tests": "0"} if failure == "false_totals" else None)
    if failure == "invalid_xml": path.write_text("<testsuite")
    if failure == "entity": path.write_text('<!DOCTYPE testsuite [<!ENTITY x SYSTEM "file:///etc/passwd">]><testsuite/>')
    assert not verify_batch(path, nodes, 1 if failure == "nonzero_exit" else 0)


@pytest.mark.parametrize("path", ["../outside.xml", "/absolute.xml", "a/../../outside.xml", "..\\outside.xml"])
def test_evidence_artifact_traversal_rejected(tmp_path, path):
    with pytest.raises(ValueError): safe_artifact(tmp_path, path)


def test_missing_or_duplicate_json_evidence_returns_invalid(tmp_path):
    missing = audit_files(tmp_path / "missing.json", tmp_path / "also-missing.json")
    assert missing["status"] == "INVALID"
    file = tmp_path / "duplicate.json"; file.write_text('{"status":"PASS","status":"PASS"}')
    with pytest.raises(ValueError): strict_json(file)


def test_batch_partition_does_not_drop_or_duplicate_test_ids():
    nodes = [f"tests/test_{file}.py::test_case_{i}" for file, count in (("a", 31), ("b", 21), ("c", 70)) for i in range(count)]
    assert [n for g in groups_for(nodes) for n in g["nodes"]] == nodes


def test_native_cti_pip_projection_retains_exact_intelligence_and_lineage(exports):
    cti = strict_json(FIXTURES / "stage6_10_cti_pip.json")
    pip = strict_json(FIXTURES / "stage6_10_pentest_pip.json")
    result = audit_connected(*exports, cti, pip)
    assert result["native_cti_pip_verified"] and not result["execution_authorized"]


@pytest.mark.parametrize("failure", ["native_bytes", "source_hash", "quality", "identity", "authority", "missing_projection"])
def test_cti_pip_lineage_cannot_be_replaced_by_declared_metadata(exports, failure):
    cti = strict_json(FIXTURES / "stage6_10_cti_pip.json")
    pip = strict_json(FIXTURES / "stage6_10_pentest_pip.json")
    if failure == "native_bytes": cti["artifact"]["intelligence"]["asset_profiles"] = []
    elif failure == "source_hash": pip["source_cti"]["artifact_sha256"] = "0" * 64
    elif failure == "quality": cti["artifact"]["quality"]["validation_results"][0]["passed"] = False
    elif failure == "identity": cti["pip_id"] = "pip-foreign"
    elif failure == "authority": cti["execution_authorized"] = True
    else: pip = None
    with pytest.raises(ValueError): audit_connected(*exports, cti, pip)


@pytest.fixture
def report_tree(tmp_path):
    roots = {k: tmp_path / k for k in ("mission", "gss", "vulndesk")}
    output = tmp_path / "evidence"; output.mkdir()
    inventory, groups = {}, []
    for index, (component, root) in enumerate(roots.items(), 1):
        (root / "tests").mkdir(parents=True)
        (root / "tests" / "test_one.py").write_text("def test_one():\n    assert True\n")
        node = "tests/test_one.py::test_one"
        inventory[component] = [node]
        group = {"component": component, "index": index, "files": ["tests/test_one.py"], "nodes": [node],
            "xml": f"batch_{index:03d}.xml", "log": f"batch_{index:03d}.log", "exit_code": 0, "verified": True}
        make_junit(output / group["xml"], [node]); (output / group["log"]).write_text("1 passed\n")
        groups.append(group)
    lock = {"components": inventory, "gate_nodes": {gate: [{"component": c, "node": inventory[c][0]} for c in roots] for gate in REQUIRED_GATES}}
    snapshots = {c: source_snapshot(root) for c, root in roots.items()}
    write_json(output / "inventory.json", inventory); write_json(output / "source_snapshot.json", snapshots)
    (output / "trajectory").mkdir()
    for fixture, name in (("knowledge", "knowledge_export"), ("mission_bundle", "mission_forensic_bundle"), ("cti_pip", "cti_pip"), ("pentest_pip", "pentest_pip")):
        shutil.copyfile(FIXTURES / ("stage6_10_"+fixture+".json"), output / "trajectory" / (name+".json"))
    trajectory = audit_files(*(output / "trajectory" / (name+".json") for name in
        ("knowledge_export", "mission_forensic_bundle", "cti_pip", "pentest_pip")))
    write_json(output / "trajectory_audit.json", trajectory)
    report = {"schema_version": SCHEMA, "status": "PASS", "live_user_mission_execution_proven": False, "independent_signature": False,
        "contract_sha256": canonical_apts_acceptance_contract()["integrity"]["canonical_sha256"],
        "inventory_lock_sha256": hashlib.sha256(canonical_json(lock).encode()).hexdigest(), "groups": groups,
        "component_counts": {c: 1 for c in roots}, "total_tests": 3, "compile_counts": {c: 1 for c in roots},
        "required_gates": {gate: True for gate in REQUIRED_GATES}, "source_snapshot_unchanged": True,
        "connected_trajectory_status": trajectory["status"],
        "artifacts": {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}}
    write_json(output / "regression_report.json", report)
    return output, roots, lock, report


def test_report_verifier_reconstructs_internal_evidence_without_trusting_status(report_tree):
    output, roots, lock, _ = report_tree
    assert verify_report(output, roots, lock)


@pytest.mark.parametrize("failure", ["source_drift", "forged_total", "missing_batch", "duplicate_batch", "forged_exit", "skip_resigned",
    "tampered_log", "extra_artifact", "missing_trajectory", "malformed_manifest"])
def test_complete_report_rejects_forged_pass_or_incomplete_coverage(report_tree, failure):
    output, roots, lock, report = report_tree
    if failure == "source_drift": (roots["mission"] / "tests" / "test_one.py").write_text("def test_one():\n    assert False\n")
    elif failure == "forged_total": report["total_tests"] = 9999
    elif failure == "missing_batch": report["groups"].pop()
    elif failure == "duplicate_batch": report["groups"].append(deepcopy(report["groups"][0]))
    elif failure == "forged_exit": report["groups"][0]["exit_code"] = 1
    elif failure == "skip_resigned":
        group = report["groups"][0]; make_junit(output / group["xml"], group["nodes"], "skipped")
        report["artifacts"][group["xml"]] = digest(output / group["xml"])
    elif failure == "tampered_log": (output / report["groups"][0]["log"]).write_text("forged PASS")
    elif failure == "extra_artifact": (output / "unlisted.json").write_text('{"status":"PASS"}')
    elif failure == "missing_trajectory": (output / "trajectory" / "cti_pip.json").unlink()
    else: report["artifacts"] = []
    write_json(output / "regression_report.json", report)
    assert not verify_report(output, roots, lock)


def test_existing_evidence_directory_is_rejected_without_overwriting_receipt(tmp_path, monkeypatch):
    from run import stage6_10_acceptance as acceptance
    output = tmp_path / "completed"; output.mkdir()
    receipt = output / "acceptance_result.json"; receipt.write_bytes(b'{"status":"PASS","original":true}')
    monkeypatch.setattr(sys, "argv", ["acceptance", "--gss-root", str(tmp_path / "gss"), "--vulndesk-root", str(tmp_path / "cti"),
        "--output", str(output), "--build-only"])
    monkeypatch.setattr(acceptance, "sandbox_probe", lambda: pytest.fail("an existing evidence run must not be reused"))
    assert acceptance.main() == 1 and receipt.read_bytes() == b'{"status":"PASS","original":true}'


def test_evidence_symlink_cannot_substitute_another_manifest_file(tmp_path, monkeypatch):
    (tmp_path / "real.xml").write_text("fixture")
    if os.name == "nt":
        # Windows symlink creation requires an OS privilege; simulate the
        # filesystem metadata without introducing a skipped acceptance test.
        (tmp_path / "link.xml").write_text("fixture")
        monkeypatch.setattr(Path, "is_symlink", lambda path: path.name == "link.xml")
    else: (tmp_path / "link.xml").symlink_to(tmp_path / "real.xml")
    with pytest.raises(ValueError): safe_artifact(tmp_path, "link.xml")


@pytest.fixture
def preflight_data():
    from execution_subsystem.apts_acceptance_contract import CONTROL_VERSION
    from execution_subsystem.cti_feedback_contract import canonical_feedback_contract
    from execution_subsystem.execution_contract import REQUIRED_AUTHORIZATION_CHECKS
    from run.stage6_10_acceptance import MISSION_CONTROL, PENTEST_CONTROL
    mission = {"status": "ok", "control_version": MISSION_CONTROL, "mission_repository_migration_level": 53,
        "storage_driver": "sqlite",
        "apts_source_locations": {"mission": "a"*64, "cti_feedback": "c"*64},
        "cti_pentest_feedback_ingestion_enabled": True, "cti_pentest_feedback_source_read_only": True}
    pentest = {"status": "ok", "control_version": PENTEST_CONTROL, "pentest_repository_migration_level": 16,
        "apts_source_locations": {"pentest": "b"*64}}
    execution = {"status": "ok", "control_version": CONTROL_VERSION, "execution_repository_migration_level": 9,
        "cti_knowledge_repository_migration_level": 1, "runtime_owner_exclusive": True, "runtime_persistence_failures": 0,
        "runtime_completion_fence_enabled": True, "runtime_authorization_quiescence_seconds": 2.0,
        "registered_adapter_count": 6, "full_apts_acceptance_status": "DECLARED_ONLY",
        "apts_source_locations": {"mission": "a"*64, "pentest": "b"*64, "cti_feedback": "c"*64}}
    for field in ("specialist_raw_target_access", "authorization_minted_locally", "worker_raw_target_access", "arbitrary_code_supported",
        "automatic_retry_enabled", "caller_heartbeat_supported", "legacy_adapter_synchronous_dispatch_enabled", "runtime_self_certification",
        "cti_feedback_external_vulndesk_writes", "cti_feedback_automatic_confirmation"): execution[field] = False
    for field in ("mission_source_read_only", "pentest_source_read_only", "cti_knowledge_source_read_only", "cti_feedback_mission_handoff_enabled"): execution[field] = True
    return {"mission": {"health": mission, "contract": {"contract": canonical_global_mission_acceptance_gate_contract()}},
        "pentest": {"health": pentest, "contract": {"contract": canonical_agentic_pentest_acceptance_gate_contract()}},
        "execution": {"health": execution, "headers": {"Server": "APTSExecutionSubsystem/6.10"},
            "contract": {"contract": canonical_apts_acceptance_contract()}, "feedback_contract": {"contract": canonical_feedback_contract()}},
        "gss": {"health": {"status": "ok", "component_id": "GOV-PLANE",
            "execution_revalidation_schema_version": "apts-gss-execution-revalidation-v1", "execution_revalidation_checks": list(REQUIRED_AUTHORIZATION_CHECKS)}},
        "cti": {"health": {"status": "ok", "component_id": "CTI-INF01", "event_dispatcher_running": True}}}


def test_preflight_requires_exact_all_component_declarations(preflight_data):
    assert validate_preflight(preflight_data)


@pytest.mark.parametrize("failure", ["old_runtime", "source_copy", "cti_copy", "mission_mysql", "broken_fence", "local_authority", "incomplete_gss", "cti_unavailable", "caller_pass", "contract_tamper"])
def test_preflight_does_not_promote_missing_or_unbound_runtime_evidence(preflight_data, failure):
    data = preflight_data
    execution = data["execution"]["health"]
    if failure == "old_runtime": execution["control_version"] = "stage6.9-closed-loop-cti-pentest-integration"
    elif failure == "source_copy": data["mission"]["health"]["apts_source_locations"]["mission"] = "d"*64
    elif failure == "cti_copy": data["mission"]["health"]["apts_source_locations"]["cti_feedback"] = "d"*64
    elif failure == "mission_mysql": data["mission"]["health"]["storage_driver"] = "mysql"
    elif failure == "broken_fence": execution["runtime_completion_fence_enabled"] = False
    elif failure == "local_authority": execution["authorization_minted_locally"] = True
    elif failure == "incomplete_gss": data["gss"]["health"]["execution_revalidation_checks"] = ["SCOPE"]
    elif failure == "cti_unavailable": data["cti"]["health"]["status"] = "degraded"
    elif failure == "caller_pass": execution["full_apts_acceptance_status"] = "PASS"
    else: data["execution"]["contract"]["contract"]["authority_boundary"]["execution_authorized"] = True
    with pytest.raises(ValueError): validate_preflight(data)
