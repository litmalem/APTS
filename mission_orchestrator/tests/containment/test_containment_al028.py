"""AL-028 containment probe suite (Fase 2) as pytest assertions.

Thin wrapper over ``containment_harness``: every probe must be contained
(fail-closed), the evidence record must be tamper-evident, and the positive
control must stay ELIGIBLE-yet-non-executing so the suite is not trivially
denying everything. Pure functions only, so no temp dir / DB is required.
"""
from __future__ import annotations

import pytest

from tests.containment.containment_harness import (
    run_containment_probes,
    verify_containment_evidence,
)

_RECORD = run_containment_probes()
_PROBES = {p["probe_id"]: p for p in _RECORD["probes"]}


@pytest.mark.parametrize("probe_id", sorted(_PROBES))
def test_probe_is_contained(probe_id: str) -> None:
    probe = _PROBES[probe_id]
    assert probe["contained"], f"containment breach in {probe_id}: {probe['observed']}"


def test_overall_contained_no_breaches() -> None:
    assert _RECORD["contained"] is True
    assert _RECORD["breached_probe_ids"] == []


def test_evidence_record_is_tamper_evident() -> None:
    assert verify_containment_evidence(_RECORD) is True
    tampered = {**_RECORD, "contained": not _RECORD["contained"]}
    assert verify_containment_evidence(tampered) is False


def test_positive_control_is_eligible_but_non_executing() -> None:
    # Guards against a harness that "passes" by denying everything.
    assert _PROBES["P0"]["observed"]["status"] == "ELIGIBLE"
    assert _PROBES["P0"]["observed"]["no_execution_invariants"] is True


def test_covers_all_four_escape_vectors() -> None:
    vectors = {p["vector"] for p in _RECORD["probes"]}
    assert {"scope-write-escape", "network-egress-escape",
            "off-schema-tool-call", "prompt-injection-override"} <= vectors
