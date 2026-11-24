"""Stage 7.9 acceptance — CAE learning loop closes the REFUTED-label gap.

Proves: CAE outcomes produce BOTH classes (CONFIRMED from EXPLOITED, REFUTED from
ACTUATED/FAILED); governance/precondition outcomes are never labelled; with both
classes present the classifier trains (NEURO_SYMBOLIC_JUSTIFIED_TRAINED) where the
old single-class data could not; a single-class set stays PRIOR_UNTRAINED; Beta
reliability posteriors are computed; the model is integrity-sealed and advisory.
Run: python3 tests/test_stage7_9_cae_learning.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pentest_subsystem import cae_learning as cl


def _run(run_id, steps):
    return {"run_id": run_id, "steps": [{"primitive_id": p, "outcome": o, "challenge_key": None} for p, o in steps]}


def test_refuted_labels_now_exist():
    obs = cl.observations_from_run(_run("r1", [
        ("idor-read-basket", "EXPLOITED"),
        ("idor-write-basket", "ACTUATED"),
        ("param-tamper-feedback", "FAILED"),
    ]))
    labels = {o["label"] for o in obs}
    assert cl.LABEL_CONFIRMED in labels and cl.LABEL_REFUTED in labels


def test_governance_outcomes_not_labelled():
    obs = cl.observations_from_run(_run("r2", [
        ("auth-lab-user", "SESSION_ESTABLISHED"),
        ("idor-write-basket", "BLOCKED"),
        ("ssrf-profile-image", "REVIEW_REQUIRED"),
        ("forced-browse-web3-sandbox", "REQUIRES_BROWSER_TRANSPORT"),
        ("destroy-5star-feedback", "DEFERRED"),
    ]))
    assert obs == []


def test_trains_with_both_classes():
    store = cl.CaeLearningStore()
    # 5 CONFIRMED + 5 REFUTED across runs -> both classes, >= MIN_TRAIN_SAMPLES
    for i in range(5):
        store.ingest(cl.observations_from_run(_run(f"c{i}", [("idor-read-basket", "EXPLOITED")])))
        store.ingest(cl.observations_from_run(_run(f"f{i}", [("idor-write-basket", "FAILED")])))
    assert store.can_train() is True
    model = store.train()
    assert model["status"] == "TRAINED"
    assert model["label"] == "NEURO_SYMBOLIC_JUSTIFIED_TRAINED"
    assert len(model["weights"]) == 4 and model["advisory_only"] is True
    dom = cl.CAE_LEARNING_HASH_DOMAIN
    core = {k: v for k, v in model.items() if k != "integrity"}
    assert model["integrity"]["canonical_sha256"] == cl.sha256_hex({"hash_domain": dom, "core": core})


def test_single_class_stays_prior_untrained():
    store = cl.CaeLearningStore()
    for i in range(10):
        store.ingest(cl.observations_from_run(_run(f"c{i}", [("idor-read-basket", "EXPLOITED")])))
    assert store.can_train() is False
    model = store.train()
    assert model["status"] == "PRIOR_UNTRAINED"
    assert model["reason"] == "SINGLE_CLASS"
    assert model["label"] == "NEURO_SYMBOLIC_NOT_JUSTIFIED_PRIOR_MODEL"


def test_reliability_posterior():
    store = cl.CaeLearningStore()
    store.ingest(cl.observations_from_run(_run("a", [("idor-read-basket", "EXPLOITED")])))
    store.ingest(cl.observations_from_run(_run("b", [("idor-read-basket", "EXPLOITED")])))
    store.ingest(cl.observations_from_run(_run("c", [("idor-read-basket", "EXPLOITED")])))
    store.ingest(cl.observations_from_run(_run("d", [("idor-read-basket", "FAILED")])))
    post = store.posteriors()["idor-read-basket"]
    assert post["successes"] == 3 and post["failures"] == 1
    assert abs(post["reliability"] - (4 / 6)) < 1e-9


def _run_all():
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); ok += 1
        except Exception:
            print(f"FAIL  {t.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(tests)} passed")
    return ok == len(tests)


if __name__ == "__main__":
    sys.exit(0 if _run_all() else 1)
