"""Fase 3 (Rancangan Learning Sejati, section 4.3) - Stage 5.2/5.3 enumeration-dimension priority policy.

Covers the OVVI advisory policy: a version-pinned, offline-trained Beta-Bernoulli policy learns which enumeration
dimension is most informative per target profile and reorders the validation starting point ONLY when a TRAINED
policy passes the leave-one-mission-out (LOMO) concordance gate; otherwise the canonical static order is kept
byte-identical. The policy is advisory (read-only) -- it never mutates sealed Stage 5.2/5.3 outputs, scope or RoE.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from pentest_subsystem import learning_dataset as ld
from pentest_subsystem import recon_enumeration_policy as rep
from pentest_subsystem.boundary_contract import sha256_hex
from pentest_subsystem.enumeration import EnumerationAgentRepository, EnumerationAgentValidationError


# ---- helpers ----------------------------------------------------------------------------------

def _hyp_record(entity_id: str, mission: str, dimension: str, label: int, profile: str = "HOST") -> dict:
    core = {
        "schema_version": ld.DATASET_SCHEMA_VERSION, "entity_kind": ld.KIND_HYPOTHESIS, "entity_id": entity_id,
        "mission_id": mission, "orchestration_id": "paorch-" + mission,
        "descriptors": {"matched_dimensions": [dimension], "target_type": profile, "knowledge_source": "k",
                        "evidence_ref_count": 1, "symbolic_confidence": 0.5},
        "label": label, "relevance_grade": 2 if label == 1 else 0,
        "label_outcome": "CONFIRMED" if label == 1 else "REFUTED",
        "provenance": {"label_source": ld.LABEL_SOURCE},
    }
    sha = sha256_hex({"hash_domain": ld.DATASET_HASH_DOMAIN, "record": core})
    rec = {**core, "record_sha256": sha}
    assert ld.verify_record(rec)
    return rec


def _dataset(missions=("m-a", "m-b", "m-c"), per=6):
    """`version` is highly productive (label 1), `service` is not (label 0). Canonical order puts version LAST, so a
    learned policy that surfaces version first beats the static order."""
    records = []
    for m in missions:
        for i in range(per):
            records.append(_hyp_record(f"v-{m}-{i}", m, "version", 1))
            records.append(_hyp_record(f"s-{m}-{i}", m, "service", 0))
    return records


def _trained_policy():
    policy = rep.fold_policy(rep.dimension_observations(_dataset()))
    assert policy["status"] == "TRAINED" and rep.policy_is_usable(policy)
    return policy


# ---- normalization & fail-safe ----------------------------------------------------------------

def test_normalize_dimension():
    assert rep.normalize_dimension("configuration:server_header") == "configuration"
    assert rep.normalize_dimension("VERSION") == "version"
    assert rep.normalize_dimension("target_type") is None
    assert rep.normalize_dimension("") is None


def test_prioritize_without_policy_is_canonical_order():
    advisory = rep.prioritize_dimensions(None, target_type="HOST")
    assert advisory["ordered_dimensions"] == list(rep.CANONICAL_ORDER)
    assert advisory["aggregation"] == rep.STATIC_ORDER
    assert advisory["policy_ref"] is None
    assert rep.verify_advisory(advisory)
    assert advisory["semantics"]["executes"] is False
    assert advisory["semantics"]["external_network_io_performed"] is False


def test_untrained_and_tampered_policy_fall_back_to_canonical():
    small = rep.fold_policy(rep.dimension_observations(_dataset(missions=("m-a",), per=2)))
    assert not rep.policy_is_usable(small)  # too few obs / single mission
    advisory = rep.prioritize_dimensions(small, target_type="HOST")
    assert advisory["ordered_dimensions"] == list(rep.CANONICAL_ORDER)
    tampered = deepcopy(_trained_policy())
    tampered["arms"]["HOST:version"]["mean"] = 0.0
    assert not rep.policy_is_usable(tampered)


# ---- learned reordering -----------------------------------------------------------------------

def test_trained_policy_reorders_by_informativeness():
    policy = _trained_policy()
    advisory = rep.prioritize_dimensions(policy, target_type="HOST")
    assert advisory["ordered_dimensions"][0] == "version"   # most informative first
    assert advisory["ordered_dimensions"][-1] == "service"  # least informative last
    assert advisory["aggregation"] == rep.LEARNED_ORDER
    assert advisory["policy_ref"]["policy_sha256"] == policy["policy_sha256"]
    assert rep.verify_advisory(advisory)
    # deterministic
    assert rep.prioritize_dimensions(policy, target_type="HOST") == advisory


def test_fold_policy_deterministic_and_verifies():
    obs = rep.dimension_observations(_dataset())
    p1, p2 = rep.fold_policy(obs), rep.fold_policy(list(reversed(obs)))
    assert p1 == p2 and rep.verify_policy(p1)


# ---- metric -----------------------------------------------------------------------------------

def test_pairwise_concordance():
    order = ["version", "service"]
    means = {"version": (0.9, 10), "service": (0.1, 10)}
    assert rep.pairwise_concordance(order, means) == 1.0
    assert rep.pairwise_concordance(["service", "version"], means) == 0.0
    assert rep.pairwise_concordance(order, {"version": (0.5, 0), "service": (0.1, 0)}) is None


# ---- LOMO promotion gate ----------------------------------------------------------------------

def test_single_mission_is_not_promotable():
    result = rep.evaluate_policy(_dataset(missions=("m-a",)))
    assert result["evaluation"]["promotable"] is False
    assert result["policy"] is None
    assert any("mission" in reason for reason in result["evaluation"]["not_promotable_reasons"])
    assert rep.verify_evaluation(result["evaluation"])


def test_multi_mission_learned_policy_is_promotable():
    result = rep.evaluate_policy(_dataset())
    ev = result["evaluation"]
    assert rep.verify_evaluation(ev)
    assert ev["mission_count"] == 3
    assert ev["promotable"] is True
    assert ev["lomo"]["concordance"] >= ev["canonical_baseline"]["concordance"]
    policy = rep.build_promoted_policy(_dataset())
    assert policy is not None and rep.policy_is_usable(policy)


def test_tampered_label_record_is_rejected():
    rec = _hyp_record("v-x", "m-a", "version", 1)
    rec["label"] = 0
    with pytest.raises(rep.EnumerationPriorityError):
        rep.dimension_observations([rec])


# ---- integration through the enumeration repository/service -----------------------------------

def test_repository_advisory_is_fail_safe_then_learned(tmp_path: Path):
    repo = EnumerationAgentRepository(tmp_path / "pentest.db")
    # fail-safe: no policy installed -> canonical order
    default = repo.advisory_enumeration_dimension_priority("HOST")
    assert default["ordered_dimensions"] == list(rep.CANONICAL_ORDER)
    assert default["aggregation"] == rep.STATIC_ORDER
    # install a trained policy -> learned order
    repo.set_enumeration_priority_policy(_trained_policy())
    learned = repo.advisory_enumeration_dimension_priority("HOST")
    assert learned["ordered_dimensions"][0] == "version"
    assert learned["aggregation"] == rep.LEARNED_ORDER
    assert rep.verify_advisory(learned)


def test_set_policy_rejects_untrained_and_tampered(tmp_path: Path):
    repo = EnumerationAgentRepository(tmp_path / "pentest.db")
    untrained = rep.fold_policy(rep.dimension_observations(_dataset(missions=("m-a",), per=2)))
    with pytest.raises(EnumerationAgentValidationError):
        repo.set_enumeration_priority_policy(untrained)
    tampered = deepcopy(_trained_policy())
    tampered["arms"]["HOST:service"]["mean"] = 0.99
    with pytest.raises(EnumerationAgentValidationError):
        repo.set_enumeration_priority_policy(tampered)
    repo.set_enumeration_priority_policy(None)  # clearing always allowed
    assert repo.enumeration_priority_policy is None
