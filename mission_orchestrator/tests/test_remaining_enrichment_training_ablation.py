from __future__ import annotations

from copy import deepcopy
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

from pentest_subsystem.cross_agent_feedback import CrossAgentFeedbackService
from pentest_subsystem.enrichment import (
    EnrichmentError,
    annotate_explanation,
    attack_request,
    cpe_request,
    fetch,
    kill_chain_view,
    parse_attack,
    parse_cpe,
    request_sha,
)
from pentest_subsystem.attack_path_workspace import ensure_plan
from pentest_subsystem.hypothesis_scoring import extract_features, verify_scoring
from pentest_subsystem.orchestration.runtime_autonomy import AutonomyRuntime
from pentest_subsystem.orchestration.runtime_enrichment import (
    MAX_ATTACK_LOOKUPS_PER_CALL,
    EnrichmentRuntime,
)
from pentest_subsystem.orchestration.runtime_learning import LearningRuntime
from pentest_subsystem.runtime_autonomy_api import start_background_ticker
from tests.test_phase2_runtime_autonomy import _get, _post, _recon_only, _server, _service_with_result
from tests.test_stage5_8_cross_agent_feedback_shared_state_replanning import _pipeline

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ablation_study  # noqa: E402


# ---- fake loopback CTI opener -----------------------------------------------------------------

class _Resp:
    def __init__(self, body):
        self._b = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self._b


def _opener(attack=None, cpe=None, calls=None, fail=False):
    def open_(request, timeout=0):
        if calls is not None:
            calls.append((request.full_url, json.loads(request.data)))
        if fail:
            raise OSError("cti down")
        if request.full_url.endswith("/map-attack"):
            return _Resp({"status": "completed", "attack_context": attack or []})
        return _Resp({"status": "completed", "results": cpe or []})
    return open_


ATTACK = [{"attack_id": "T1189", "attack_name": "Drive-by Compromise", "tactic_name": "Initial Access",
           "mapping_level": "cwe_to_attack", "mapping_source": "seed", "confidence": 0.45},
          {"attack_id": "T1059", "attack_name": "Command and Scripting Interpreter", "tactic_name": "Execution",
           "mapping_level": "keyword", "mapping_source": "seed", "confidence": 0.3}]


# ---- enrichment clients -----------------------------------------------------------------------

def test_attack_request_uses_only_fields_already_in_the_hypothesis():
    h = {"vulnerability_id": "CVE-2025-1", "knowledge": {"title": "Angular XSS", "summary": "stored XSS"}}
    assert attack_request(h) == {"candidate": {"cve_id": "CVE-2025-1", "title": "Angular XSS", "description": "stored XSS"}}
    assert attack_request({}) == {"candidate": {}}


def test_cpe_request_never_allows_external_fetch():
    req = cpe_request(["Angular", " angular", "Apache HTTP Server"])
    assert req["auto_fetch"] is False
    assert [t["technology"] for t in req["technologies"]] == ["Angular", "Apache HTTP Server", "angular"]  # sorted, de-duplicated by exact text
    with pytest.raises(EnrichmentError, match="auto_fetch"):
        fetch("cpe", {"technologies": [], "auto_fetch": True}, opener=_opener())


def test_parse_and_status_semantics_service_down_is_unavailable_not_empty():
    assert [m["attack_id"] for m in parse_attack({"attack_context": ATTACK})] == ["T1189", "T1059"]
    assert parse_cpe({"results": [{"cpe23_uri": "cpe:2.3:a:apache:http_server:2.4.58:*:*:*:*:*:*:*"}]}) == ["apache http server"]
    assert fetch("attack", {"candidate": {}}, opener=_opener(attack=ATTACK))["status"] == "OK"
    assert fetch("attack", {"candidate": {}}, opener=_opener(attack=[]))["status"] == "EMPTY"
    assert fetch("attack", {"candidate": {}}, opener=_opener(fail=True))["status"] == "UNAVAILABLE"
    assert fetch("cpe", cpe_request(["x"]), opener=_opener(cpe=[]))["status"] == "EMPTY"  # honest empty dictionary


def test_kill_chain_view_is_descriptive_and_never_causal():
    view = kill_chain_view({"h1": parse_attack({"attack_context": ATTACK}), "h2": parse_attack({"attack_context": ATTACK[:1]})})
    assert [t["tactic"] for t in view["tactics_in_matrix_order"]] == ["Initial Access", "Execution"]
    assert view["tactics_in_matrix_order"][0]["hypotheses"] == 2 and view["is_causal_dependency"] is False


# ---- runtime: cache, annotation, scoring with CPE names ---------------------------------------

def test_enrich_caches_answers_is_idempotent_and_annotates_without_changing_the_plan(tmp_path):
    repo, _, _, oid, _ = _pipeline(tmp_path, "rem1")
    service = CrossAgentFeedbackService(repo)
    ensure_plan(service, oid)
    calls: list = []
    er = EnrichmentRuntime(service, opener=_opener(attack=ATTACK, calls=calls))
    first = er.enrich(oid)
    assert first["kinds"]["attack"]["fetched"] >= 1 and first["external_network_io_performed"] is False
    assert all(url.startswith("http://127.0.0.1") for url, _ in calls)
    n_calls = len(calls)
    again = er.enrich(oid)
    assert again["kinds"]["attack"]["fetched"] == 0 and again["kinds"]["attack"]["cached"] >= 1
    assert not any(url.endswith("/map-attack") for url, _ in calls[n_calls:])  # second pass makes no attack lookups
    plain = AutonomyRuntime(service).explain_plan(oid)["explanation"]
    ann = er.annotated_explanation(plain, oid)
    assert ann["semantics"]["attack_context_is_descriptive"] is True and ann["semantics"]["planner_inputs_changed"] is False
    assert [p["path_id"] for p in ann["paths"]] == [p["path_id"] for p in plain["paths"]]
    assert [p["total_cost"] for p in ann["paths"]] == [p["total_cost"] for p in plain["paths"]]
    assert ann["paths"][0]["attack_context"][0]["attack_id"] == "T1189"
    assert ann["attack_view"]["is_causal_dependency"] is False


def test_unavailable_cti_is_reported_not_cached_and_not_fabricated(tmp_path):
    repo, _, _, oid, _ = _pipeline(tmp_path, "rem2")
    er = EnrichmentRuntime(CrossAgentFeedbackService(repo), opener=_opener(fail=True))
    rep = er.enrich(oid, ["attack"])
    assert rep["kinds"]["attack"]["unavailable"] >= 1 and rep["kinds"]["attack"]["fetched"] == 0
    assert er.attack_context(oid) == {}
    with sqlite3.connect(tmp_path / "pentest.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM pentest_enrichment_cache").fetchone()[0] == 0
    with pytest.raises(EnrichmentError):
        er.enrich(oid, ["shell"])


def test_attack_lookups_are_bounded_per_call():
    assert MAX_ATTACK_LOOKUPS_PER_CALL == 50


def test_cpe_names_feed_name_similarity_offline_and_are_recorded_in_the_score(tmp_path):
    repo, _, _, oid, _ = _pipeline(tmp_path, "rem3")
    service = CrossAgentFeedbackService(repo)
    er = EnrichmentRuntime(service, opener=_opener(cpe=[{"cpe23_uri": "cpe:2.3:a:vendor:fancy_product:1.0:*:*:*:*:*:*:*"}]))
    assert er.enrich(oid, ["cpe"])["kinds"]["cpe"]["status"] in {"OK", "SKIPPED_NO_TECHNOLOGIES"}
    rt = AutonomyRuntime(service)
    rec = rt.score_hypotheses(oid)["scoring"]
    assert verify_scoring(rec) and rec["catalog_names"] == er.cpe_names(oid)
    h = {"vulnerability_id": "CVE-2025-1", "knowledge": {"title": "Fancy Product flaw", "summary": ""}, "correlation": {},
         "confidence": {}}
    assert extract_features(h, None, extra_names=["vendor fancy product"])["name_similarity"] > \
        extract_features(h, None)["name_similarity"]


# ---- guarded classifier training --------------------------------------------------------------

def _runs_for(hid, n_pos, n_neg):
    def run(i, outcome):
        return {"execution_run_id": f"xplexec-t{i}", "path_results": [{"outcome": outcome, "technique": "T", "targets": ["t"],
                                                                         "finding": {"hypothesis_ids": [hid]}}]}
    return [run(i, "CONFIRMED") for i in range(n_pos)] + [run(100 + i, "REFUTED") for i in range(n_neg)]


def test_training_refuses_one_class_or_too_little_data_and_prior_stays_active(tmp_path, monkeypatch):
    repo, _, _, oid, _ = _pipeline(tmp_path, "rem4")
    service = CrossAgentFeedbackService(repo)
    hid = repo.get_orchestration_vulnerability_hypothesis_run(oid)["output"]["vulnerability_hypotheses"][0]["hypothesis_id"]
    er = EnrichmentRuntime(service)
    monkeypatch.setattr(LearningRuntime, "_verified_execution_runs", lambda self, o: _runs_for(hid, 40, 0))
    LearningRuntime(service).ingest(oid)
    stats = er.sample_stats()
    assert stats["positives"] == 40 and stats["negatives"] == 0
    res = er.train()
    assert res["status"] == "INSUFFICIENT_DATA" and "single class" in res["reason"]
    assert er.latest_model()["status"] == "PRIOR_UNTRAINED"
    rec = AutonomyRuntime(service).score_hypotheses(oid)["scoring"]
    assert rec["label_justification"] == "NEURO_SYMBOLIC_NOT_JUSTIFIED_PRIOR_MODEL"


def test_training_succeeds_only_with_both_classes_and_then_scoring_uses_the_trained_model(tmp_path, monkeypatch):
    repo, _, _, oid, _ = _pipeline(tmp_path, "rem5")
    service = CrossAgentFeedbackService(repo)
    hid = repo.get_orchestration_vulnerability_hypothesis_run(oid)["output"]["vulnerability_hypotheses"][0]["hypothesis_id"]
    monkeypatch.setattr(LearningRuntime, "_verified_execution_runs", lambda self, o: _runs_for(hid, 20, 20))
    LearningRuntime(service).ingest(oid)
    er = EnrichmentRuntime(service)
    res = er.train()
    assert res["status"] == "TRAINED" and res["created"] is True
    assert er.train()["created"] is False  # deterministic: same data -> same model hash, no duplicate row
    assert er.latest_model()["status"] == "TRAINED"
    scored = AutonomyRuntime(service).score_hypotheses(oid)["scoring"]
    assert scored["model"]["status"] == "TRAINED" and scored["label_justification"].startswith("STATISTICAL_LAYER_TRAINED")
    with sqlite3.connect(tmp_path / "pentest.db") as conn:
        conn.execute("INSERT INTO pentest_enrichment_cache VALUES ('penr-x','attack','k','r','OK','[]','s','2026-01-01T00:00:00Z')")
        for sql in ("UPDATE pentest_hypothesis_models SET status='X'", "DELETE FROM pentest_hypothesis_models",
                    "UPDATE pentest_learning_samples SET label=1", "DELETE FROM pentest_learning_samples",
                    "UPDATE pentest_enrichment_cache SET status='X'", "DELETE FROM pentest_enrichment_cache"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)


def test_partial_and_inconclusive_outcomes_are_not_classifier_labels(tmp_path, monkeypatch):
    repo, _, _, oid, _ = _pipeline(tmp_path, "rem6")
    service = CrossAgentFeedbackService(repo)
    hid = repo.get_orchestration_vulnerability_hypothesis_run(oid)["output"]["vulnerability_hypotheses"][0]["hypothesis_id"]
    runs = [{"execution_run_id": "xplexec-p", "path_results": [{"outcome": "PARTIALLY_CONFIRMED", "technique": "T", "targets": ["t"],
                                                                 "finding": {"hypothesis_ids": [hid]}}]}]
    monkeypatch.setattr(LearningRuntime, "_verified_execution_runs", lambda self, o: deepcopy(runs))
    out = LearningRuntime(service).ingest(oid)
    assert out["samples"]["samples_added"] == 0 and out["observations_added"] >= 1  # learns arms, but not a label


# ---- HTTP + ticker ----------------------------------------------------------------------------

def test_http_routes_for_enrichment_attack_context_and_training(tmp_path, monkeypatch):
    repo, _, _, oid, _ = _pipeline(tmp_path, "rem7")
    monkeypatch.setattr(EnrichmentRuntime, "__init__", (lambda orig: lambda self, service, *, opener=None: orig(
        self, service, opener=opener or _opener(attack=ATTACK)))(EnrichmentRuntime.__init__))
    server, base = _server(repo)
    try:
        root = base + "/api/pentest/agentic-orchestrations/" + oid + "/autonomy"
        status, body = _post(root + "/enrichment", {"kinds": ["attack"]})
        assert status == 200 and body["kinds"]["attack"]["fetched"] >= 1 and body["execution_started"] is False
        status, _, body = _get(root + "/attack-context")
        assert status == 200 and body["attack_view"]["is_causal_dependency"] is False and body["hypotheses"]
        assert _post(root + "/enrichment", {"kinds": ["shell"]})[0] == 400
        assert _post(root + "/enrichment", {"url": "http://evil"})[0] == 400
        status, _, body = _get(base + "/api/pentest/autonomy/learning/samples")
        assert status == 200 and body["total"] == 0 and body["requires_both_classes"] is True
        status, body = _post(base + "/api/pentest/autonomy/learning/train", {})
        assert status == 200 and body["status"] == "INSUFFICIENT_DATA"
        assert _post(base + "/api/pentest/autonomy/learning/train", {"label": 1})[0] == 400
    finally:
        server.shutdown()


def test_background_ticker_also_ingests_learning_when_enabled(tmp_path):
    repo, task, orch, oid, run = _recon_only(tmp_path, "rem8")
    service, *_ = _service_with_result(repo, run, task, orch)
    stop = threading.Event()
    thread = start_background_ticker(service, 0.05, stop=stop, learn=True)
    deadline = time.time() + 5
    seen = False
    while time.time() < deadline and not seen:
        try:
            with sqlite3.connect(tmp_path / "pentest.db") as conn:
                seen = conn.execute("SELECT COUNT(*) FROM pentest_learning_policies").fetchone()[0] >= 1
        except sqlite3.OperationalError:
            pass
        time.sleep(0.05)
    stop.set(); thread.join(timeout=15)
    assert seen and not thread.is_alive()


# ---- ablation (simulation) --------------------------------------------------------------------

def test_ablation_is_deterministic_and_labelled_as_simulation():
    a, b = ablation_study.main(), ablation_study.main()
    assert a == b and "not empirical" in a["disclaimer"]


def test_ablation_structural_claims_hold_without_overstating():
    r = ablation_study.main()["scenarios"]
    assert r["clean_target"]["agentic"]["capabilities_run"] < r["clean_target"]["fixed"]["capabilities_run"]
    for name, pair in r.items():
        assert pair["agentic"]["final_coverage"] >= pair["fixed"]["final_coverage"], name
    rl = r["rate_limited"]
    assert rl["agentic"]["adverse_noisy_actions"] < rl["fixed"]["adverse_noisy_actions"]
    assert rl["agentic"]["noise_units"] < rl["fixed"]["noise_units"]
    for name in ("clean_target", "vulnerable_target", "large_surface"):
        assert r[name]["agentic"]["final_coverage"] >= ablation_study.STOPPING_RULE["coverage_threshold"]
    # honesty guard: agentic is allowed to probe MORE than the baseline to reach coverage; the claim is not "fewer probes"
    assert any(p["agentic"]["probing_actions"] > p["fixed"]["probing_actions"] for p in r.values())
