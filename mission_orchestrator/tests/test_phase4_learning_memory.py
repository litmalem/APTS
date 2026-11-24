from __future__ import annotations

from copy import deepcopy
import sqlite3

import pytest

from pentest_subsystem.cross_agent_feedback import CrossAgentFeedbackService
from pentest_subsystem.learning import (
    MAX_YIELD_FACTOR,
    MIN_EFFECTIVE_N,
    LearningError,
    adjusted_confidence,
    derive_seed,
    extract_validation_observations,
    fold_policy,
    probing_observation,
    reliability,
    technique_reliability,
    thompson_select,
    verify_policy,
    verify_selection,
    yield_factor,
)
from pentest_subsystem.orchestration.perception_action import decide, new_state
from pentest_subsystem.orchestration.runtime_learning import LearningRuntime
from tests.test_phase2_runtime_autonomy import _get, _post, _server
from tests.test_stage5_8_cross_agent_feedback_shared_state_replanning import _pipeline


def _obs(i, arm, outcome="CONFIRMED"):
    a, b = {"CONFIRMED": (1.0, 0.0), "REFUTED": (0.0, 1.0), "PARTIALLY_CONFIRMED": (0.5, 0.5)}[outcome]
    return {"observation_id": f"pobs-{i:04d}", "arm": arm, "outcome": outcome, "alpha_inc": a, "beta_inc": b}


# ---- P6: posterior fold ----------------------------------------------------------------------

def test_policy_is_a_deterministic_order_independent_duplicate_safe_fold_with_tamper_evidence():
    obs = [_obs(i, "validation_technique:T", "CONFIRMED" if i % 3 else "REFUTED") for i in range(12)]
    a, b = fold_policy(obs), fold_policy(list(reversed(obs)) + obs[:3])
    assert a == b and verify_policy(a) and a["observation_count"] == 12
    arm = a["arms"]["validation_technique:T"]
    assert arm["alpha"] == 1 + 8 and arm["beta"] == 1 + 4 and arm["mean"] == pytest.approx(9 / 14, abs=1e-6)
    t = deepcopy(a); t["arms"]["validation_technique:T"]["alpha"] = 99
    assert not verify_policy(t)
    assert fold_policy(obs[:-1])["policy_sha256"] != a["policy_sha256"]  # forgetting changes the version


def test_partial_confirmation_is_half_evidence_and_inconclusive_is_ignored():
    assert fold_policy([_obs(1, "match_dims:technology", "PARTIALLY_CONFIRMED")])["arms"]["match_dims:technology"]["mean"] == 0.5
    run = {"execution_run_id": "x1", "path_results": [
        {"outcome": "INCONCLUSIVE", "technique": "T", "finding": {"hypothesis_ids": ["h1"]}},
        {"outcome": "BLOCKED", "technique": "T", "finding": {"hypothesis_ids": ["h1"]}}]}
    obs, skipped = extract_validation_observations(run, [{"hypothesis_id": "h1"}])
    assert obs == [] and skipped["uninformative"] == 2
    with pytest.raises(LearningError):
        extract_validation_observations({"execution_run_id": "x", "path_results": [{"outcome": "WEIRD"}]}, [])


def _hyp(hid, source="vulndesk", dims=("technology",)):
    return {"hypothesis_id": hid, "asset_id": "a1", "knowledge": {"source": {"source_id": source}},
            "correlation": {"matched_dimensions": list(dims)}}


def test_extraction_maps_each_confirmed_hypothesis_to_three_arms():
    run = {"execution_run_id": "x1", "path_results": [
        {"outcome": "CONFIRMED", "technique": "SAFE_VERSION_CONFIGURATION_CONFIRMATION", "targets": ["http://x"],
         "finding": {"hypothesis_ids": ["h1"]}}]}
    obs, _ = extract_validation_observations(run, [_hyp("h1")], {"a1": {"technologies": [{"technology": "Angular"}]}})
    assert sorted(o["arm"] for o in obs) == ["knowledge_source:vulndesk", "match_dims:technology",
                                              "validation_technique:SAFE_VERSION_CONFIGURATION_CONFIRMATION"]
    assert all(o["technologies"] == ["Angular"] and "http://x" not in str(o) for o in obs)  # no raw target stored


def test_episode_technologies_come_from_technologies_versions_and_services():
    run = {"execution_run_id": "x2", "path_results": [{"outcome": "CONFIRMED", "technique": "T", "targets": ["t"],
                                                       "finding": {"hypothesis_ids": ["h1"]}}]}
    asset = {"technologies": [{"technology": "Angular"}], "versions": [{"product": "Apache HTTP Server"}],
             "services": [{"service": "http"}]}
    obs, _ = extract_validation_observations(run, [_hyp("h1")], {"a1": asset})
    assert obs[0]["technologies"] == ["Angular", "Apache HTTP Server", "http"]


def test_neutral_below_min_evidence_and_bounded_above():
    few = fold_policy([_obs(i, "probing_technique:A") for i in range(int(MIN_EFFECTIVE_N) - 1)])
    assert reliability(few, "probing_technique:A") is None and technique_reliability(few) == {}
    assert yield_factor(None) == 1.0 and yield_factor(0.99) == MAX_YIELD_FACTOR and yield_factor(0.0) == 0.0
    assert adjusted_confidence(0.8, None) == 0.8 and adjusted_confidence(0.8, 0.5) == 0.8
    assert adjusted_confidence(0.8, 0.1) < 0.2 and adjusted_confidence(0.9, 1.0) == 1.0


def test_learning_test_negative_results_lower_reliability_and_technique_is_chosen_less():
    surface = {d: {"total": 10, "remaining": 8} for d in ("unprofiled_services", "unversioned_services",
                                                         "unprobed_endpoints", "unobserved_config")}
    state = new_state("enumeration", surface, budget=10)
    allowed = ["VERSION_DISCOVERY", "CONFIGURATION_OBSERVATION"]
    before = decide(state, allowed_techniques=allowed)
    assert before["proposal"]["technique"] in allowed
    losers = [probing_observation("o", "enumeration", {"event_id": f"e{i}", "technique": "VERSION_DISCOVERY", "new_items": 0})
              for i in range(12)]
    policy = fold_policy(losers)
    rel = technique_reliability(policy)
    assert rel["VERSION_DISCOVERY"] < 0.2
    after = decide(state, allowed_techniques=allowed, technique_reliability=rel)
    assert after["proposal"]["technique"] == "CONFIGURATION_OBSERVATION"
    scores = {c["technique"]: c for c in after["candidates"]}
    assert scores["VERSION_DISCOVERY"]["yield_factor"] < 0.4 and scores["CONFIGURATION_OBSERVATION"]["yield_factor"] == 1.0
    # reliability can never push a technique outside the RoE-allowed set
    assert decide(state, allowed_techniques=["CONFIGURATION_OBSERVATION"], technique_reliability=rel)["proposal"]["technique"] \
        == "CONFIGURATION_OBSERVATION"


def test_thompson_sampling_is_replayable_records_seed_and_favours_the_better_arm():
    winners = [probing_observation("o", "reconnaissance", {"event_id": f"w{i}", "technique": "PASSIVE_DISCOVERY", "new_items": 3})
               for i in range(15)]
    losers = [probing_observation("o", "reconnaissance", {"event_id": f"l{i}", "technique": "TCP_CONNECT_SCAN", "new_items": 0})
              for i in range(15)]
    policy = fold_policy(winners + losers)
    cands = ["PASSIVE_DISCOVERY", "TCP_CONNECT_SCAN"]
    one = thompson_select(policy, cands, family="probing_technique", seed=7)
    assert one == thompson_select(policy, cands, family="probing_technique", seed=7) and verify_selection(one)
    assert one["seed"] == 7 and one["semantics"]["executes"] is False
    picks = [thompson_select(policy, cands, family="probing_technique",
                             seed=derive_seed(policy["policy_sha256"], "o", "reconnaissance", n))["chosen"] for n in range(40)]
    assert picks.count("PASSIVE_DISCOVERY") > 30
    with pytest.raises(LearningError):
        thompson_select(policy, [], family="probing_technique", seed=1)


# ---- runtime: ingest / beliefs / memory / retention -------------------------------------------

def _runtime(tmp_path, suffix, monkeypatch):
    repo, _, _, oid, _ = _pipeline(tmp_path, suffix)
    hyps = repo.get_orchestration_vulnerability_hypothesis_run(oid)["output"]["vulnerability_hypotheses"]
    def run(run_id, outcome, hid, finding_id):
        return {"execution_run_id": run_id, "path_results": [
            {"outcome": outcome, "technique": "SAFE_VERSION_CONFIGURATION_CONFIRMATION", "targets": ["http://127.0.0.1:1"],
             "model_confidence": 0.5, "finding": {"hypothesis_ids": [hid], "finding_id": finding_id}}]}
    # two executions (e.g. two snapshots) over the pipeline's hypotheses; one hypothesis cannot yield two outcomes in one run
    runs = [run("xplexec-test-1", "CONFIRMED", hyps[0]["hypothesis_id"], "xplfind-1"),
            run("xplexec-test-2", "REFUTED", hyps[-1]["hypothesis_id"], "xplfind-2")]
    monkeypatch.setattr(LearningRuntime, "_verified_execution_runs", lambda self, o: deepcopy(runs))
    return repo, oid, LearningRuntime(CrossAgentFeedbackService(repo)), hyps


def test_ingest_is_idempotent_versions_policy_and_populates_beliefs(tmp_path, monkeypatch):
    repo, oid, lr, hyps = _runtime(tmp_path, "p4ing", monkeypatch)
    first = lr.ingest(oid)
    assert first["observations_added"] >= 6 and first["policy_created"] is True
    assert first["beliefs"]["facts_added"] > 0
    second = lr.ingest(oid)
    assert second["observations_added"] == 0 and second["policy_created"] is False
    assert second["policy_sha256"] == first["policy_sha256"] and second["beliefs"]["facts_added"] == 0
    view = lr.learning_view(oid)
    assert view["advisory_only"] is True and all(0 <= h["advisory_adjusted_confidence"] <= 1 for h in view["hypotheses"])
    facts = lr.beliefs(oid)["facts"]
    keys = {f["fact_key"].split(":")[0] for f in facts}
    assert {"asset", "hypothesis", "validation"} <= keys
    assert next(f for f in facts if f["fact_key"] == "hypothesis:" + hyps[0]["hypothesis_id"])["value"]["status"] == "HYPOTHESIS_NOT_FINDING"
    assert lr.beliefs(oid, prefix="validation:")["count"] >= 1


def test_belief_facts_are_versioned_not_overwritten(tmp_path, monkeypatch):
    repo, oid, lr, hyps = _runtime(tmp_path, "p4ver", monkeypatch)
    lr.sync_beliefs(oid)
    with sqlite3.connect(tmp_path / "pentest.db") as conn:
        key = "hypothesis:" + hyps[0]["hypothesis_id"]
        n1 = conn.execute("SELECT COUNT(*) FROM pentest_belief_facts WHERE fact_key=?", (key,)).fetchone()[0]
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE pentest_belief_facts SET confidence=1.0")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM pentest_belief_facts")
    assert n1 == 1 and lr.sync_beliefs(oid)["facts_added"] == 0


def test_episodic_recall_is_cross_mission_and_stores_no_raw_target(tmp_path, monkeypatch):
    repo, oid, lr, hyps = _runtime(tmp_path, "p4rec", monkeypatch)
    lr.ingest(oid)
    tech = next(t for f in lr.beliefs(oid, prefix="asset:")["facts"] for t in f["value"]["technologies"])
    rec = lr.recall(tech)
    assert {e["outcome"] for e in rec["episodes"]} == {"CONFIRMED", "REFUTED"} and rec["stores_raw_target_values"] is False
    assert lr.recall("Technology-That-Never-Occurred")["episodes"] == []
    with sqlite3.connect(tmp_path / "pentest.db") as conn:
        dump = " ".join(str(r) for r in conn.execute("SELECT * FROM pentest_learning_observations"))
    assert "127.0.0.1" not in dump
    with pytest.raises(LearningError):
        lr.recall("")


def test_retention_deletes_only_expired_observations_and_policy_forgets_them(tmp_path, monkeypatch):
    repo, oid, lr, _ = _runtime(tmp_path, "p4ret", monkeypatch)
    lr.ingest(oid)
    before = lr.current_policy()
    with sqlite3.connect(tmp_path / "pentest.db") as conn:
        with pytest.raises(sqlite3.DatabaseError, match="retention"):
            conn.execute("DELETE FROM pentest_learning_observations")  # unexpired rows are protected
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE pentest_learning_observations SET outcome='CONFIRMED'")
        conn.execute("INSERT INTO pentest_learning_observations VALUES ('pobs-old', ?, 'probing_technique:Z', 'CONFIRMED', 1, 0,"
                     " 'e', NULL, '[]', 'f', '2020-01-01T00:00:00Z', '2020-06-01T00:00:00Z')", (oid,))
    assert lr.current_policy()["observation_count"] == before["observation_count"] + 1
    out = lr.ingest(oid)
    assert out["expired_observations_purged"] == 1
    assert lr.current_policy()["policy_sha256"] == before["policy_sha256"]


def test_thompson_endpoint_logic_is_roe_bound_server_seeded_and_persisted(tmp_path, monkeypatch):
    repo, oid, lr, _ = _runtime(tmp_path, "p4ts", monkeypatch)
    lr.ingest(oid)
    one = lr.thompson(oid, "reconnaissance")
    two = lr.thompson(oid, "reconnaissance")
    assert one["selection"]["seed"] != two["selection"]["seed"]  # counter advances; both recorded
    assert one["selection"]["chosen"] in one["selection"]["candidates"] and one["execution_started"] is False
    with pytest.raises(LearningError):
        lr.thompson(oid, "validation")
    with sqlite3.connect(tmp_path / "pentest.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM pentest_learning_selections").fetchone()[0] == 2
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM pentest_learning_selections")


def test_http_routes(tmp_path, monkeypatch):
    repo, oid, lr, _ = _runtime(tmp_path, "p4http", monkeypatch)
    server, base = _server(repo)
    try:
        root = base + "/api/pentest/agentic-orchestrations/" + oid + "/autonomy"
        assert _post(root + "/learning/ingest", {"outcomes": "fake"})[0] == 400  # outcomes are never caller-supplied
        status, body = _post(root + "/learning/ingest", {})
        assert status == 200 and body["observations_added"] > 0 and body["authorization_minted"] is False
        status, _, body = _get(root + "/learning")
        assert status == 200 and body["advisory_only"] is True and body["policy"]["policy_version"].startswith("policy-")
        status, _, body = _get(root + "/beliefs?prefix=asset:")
        assert status == 200 and body["count"] >= 1 and all(f["fact_key"].startswith("asset:") for f in body["facts"])
        status, body = _post(root + "/learning/thompson", {"capability_id": "reconnaissance"})
        assert status == 200 and body["selection"]["seed"] >= 0
        assert _post(root + "/learning/thompson", {"capability_id": "reconnaissance", "seed": 1})[0] == 400
        status, _, body = _get(base + "/api/pentest/autonomy/episodes?technology=Nothing")
        assert status == 200 and body["episodes"] == []
        assert _get(base + "/api/pentest/autonomy/episodes")[0] == 400
    finally:
        server.shutdown()
