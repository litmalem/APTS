from __future__ import annotations

from copy import deepcopy

import pytest

from pentest_subsystem.learning_dataset import (
    LabelDatasetError,
    build_records,
    coverage_report,
    export_dataset,
    leave_one_mission_out,
    verify_record,
)


def _hyp(hid, conf=0.7):
    return {"hypothesis_id": hid, "asset_id": "a1", "integrity": {"canonical_sha256": "h" * 8 + hid},
            "knowledge": {"source": {"source_id": "vulndesk"}},
            "correlation": {"matched_dimensions": ["technology", "version"], "supporting_evidence_refs": ["e1", "e2"]},
            "confidence": {"overall": conf, "knowledge": conf, "evidence": conf}}


def _pr(pid, outcome, hids):
    return {"attack_path_id": pid, "outcome": outcome, "technique": "T", "cost": 3, "length": 2, "model_confidence": 0.6,
            "validates": "h", "targets": ["http://127.0.0.1"], "integrity": {"canonical_sha256": "p" + pid},
            "expected_evidence_evaluation": [{"hypothesis_id": h} for h in hids],
            "finding": {"finding_id": "f" + pid, "hypothesis_ids": hids, "outcome": outcome,
                        "integrity": {"canonical_sha256": "f" + pid}}}


def _run(rid, mission, results):
    return {"execution_run_id": rid, "mission_id": mission, "orchestration_id": "paorch-1",
            "integrity": {"canonical_sha256": "r" + rid}, "attack_path_snapshot_sha256": "s", "attack_path_plan_sha256": "pl",
            "path_results": results}


def test_labels_grades_and_censoring():
    run = _run("x1", "m1", [_pr("p1", "CONFIRMED", ["h1"]), _pr("p2", "REFUTED", ["h2"]), _pr("p3", "PARTIALLY_CONFIRMED", ["h3"]),
                            _pr("p4", "INCONCLUSIVE", ["h4"]), _pr("p5", "BLOCKED", ["h5"])])
    recs, st = build_records(run, [_hyp(f"h{i}") for i in range(1, 6)], {"a1": {}})
    assert st["censored"] == 2
    by = {(r["entity_kind"], r["entity_id"]): r for r in recs}
    assert len(recs) == 6  # 3 hypotheses + 3 paths; censored outcomes emit nothing
    assert (by["HYPOTHESIS", "h1"]["label"], by["HYPOTHESIS", "h1"]["relevance_grade"]) == (1, 2)
    assert (by["ATTACK_PATH", "p2"]["label"], by["ATTACK_PATH", "p2"]["relevance_grade"]) == (0, 0)
    assert (by["HYPOTHESIS", "h3"]["label"], by["HYPOTHESIS", "h3"]["relevance_grade"]) == (None, 1)


def test_provenance_and_features_present_and_deterministic():
    run = _run("x1", "m1", [_pr("p1", "CONFIRMED", ["h1"])])
    a, _ = build_records(run, [_hyp("h1")])
    b, _ = build_records(deepcopy(run), [_hyp("h1")])
    assert a == b and all(verify_record(r) for r in a)
    h = next(r for r in a if r["entity_kind"] == "HYPOTHESIS")
    p = next(r for r in a if r["entity_kind"] == "ATTACK_PATH")
    assert h["mission_id"] == "m1" and h["provenance"]["execution_run_sha256"] == "rx1"
    assert h["provenance"]["hypothesis_sha256"] == "h" * 8 + "h1" and h["provenance"]["finding_sha256"] == "fp1"
    assert p["features"]["hypothesis_count"] == 1 and p["features"]["evidence_ref_count"] == 2
    assert "dims_count" in h["features"] and h["descriptors"]["matched_dimensions"] == ["technology", "version"]


def test_run_without_mission_is_rejected_and_unknown_hypothesis_counted():
    with pytest.raises(LabelDatasetError):
        build_records({"execution_run_id": "x", "path_results": []}, [])
    _, st = build_records(_run("x1", "m1", [_pr("p1", "CONFIRMED", ["ghost"])]), [])
    assert st["unknown_hypothesis"] == 1


def test_export_is_hash_pinned_and_tamper_evident():
    recs, _ = build_records(_run("x1", "m1", [_pr("p1", "CONFIRMED", ["h1"]), _pr("p2", "PARTIALLY_CONFIRMED", ["h2"])]),
                            [_hyp("h1"), _hyp("h2")])
    e1, e2 = export_dataset(recs), export_dataset(list(reversed(recs)))
    assert e1["dataset_sha256"] == e2["dataset_sha256"] and e1["record_count"] == 4
    assert export_dataset(recs, binary_only=True)["record_count"] == 2
    assert export_dataset(recs, kind="ATTACK_PATH")["dataset_sha256"] != e1["dataset_sha256"]
    bad = deepcopy(recs); bad[0]["label"] = 1 - (bad[0]["label"] or 0)
    with pytest.raises(LabelDatasetError):
        export_dataset(bad)


def test_leave_one_mission_out_and_coverage():
    r1, _ = build_records(_run("x1", "m1", [_pr("p1", "CONFIRMED", ["h1"])]), [_hyp("h1")])
    with pytest.raises(LabelDatasetError):
        list(leave_one_mission_out(r1))
    r2, _ = build_records(_run("x2", "m2", [_pr("p2", "REFUTED", ["h2"])]), [_hyp("h2")])
    allr = r1 + r2
    splits = list(leave_one_mission_out(allr))
    assert [s[0] for s in splits] == ["m1", "m2"]
    assert all({r["mission_id"] for r in tr}.isdisjoint({r["mission_id"] for r in te}) for _, tr, te in splits)
    cov = coverage_report(allr)
    assert cov["HYPOTHESIS"]["lomo_ready"] and cov["ATTACK_PATH"]["positives"] == 1 and cov["ATTACK_PATH"]["negatives"] == 1
    assert not coverage_report(r1)["HYPOTHESIS"]["lomo_ready"]


def test_ingest_persists_label_dataset_idempotently_with_provenance(tmp_path, monkeypatch):
    from pentest_subsystem.orchestration.runtime_label_dataset import LabelDatasetRuntime
    from tests.test_phase4_learning_memory import _runtime
    repo, oid, lr, hyps = _runtime(tmp_path, "f0ing", monkeypatch)
    first = lr.ingest(oid)
    assert first["label_dataset"]["dataset_records_added"] > 0
    assert lr.ingest(oid)["label_dataset"]["dataset_records_added"] == 0
    rt = LabelDatasetRuntime(lr.service)
    exp = rt.export()
    assert exp["record_count"] == first["label_dataset"]["dataset_records_added"] and exp["read_only"] is True
    assert all(r["mission_id"] and r["provenance"]["execution_run_id"] for r in exp["records"])
    assert rt.export()["dataset_sha256"] == exp["dataset_sha256"]
    assert set(rt.coverage()["coverage"]) == {"HYPOTHESIS", "ATTACK_PATH"}
