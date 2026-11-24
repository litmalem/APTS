# Stage 3.9.4 Hotfix 1 — Regression Rebase

## Trigger
Host acceptance reached the full regression gate with 1485 collected tests and reported 9 failures / 1476 passes.

All nine failures were stale `supported_controls` ordering/cardinality assertions in predecessor regression tests. The runtime chain correctly contains:

`... -> stage3.9.2 -> stage3.9.3 -> stage3.9.4`

but the affected legacy assertions were still rebased as if Stage 3.9.3 did not exist:

`... -> stage3.9.2 -> stage3.9.4`.

## Scope
This hotfix changes regression expectations only. It does not change runtime authority, mission repository schema, database migration level, routing semantics, delegation semantics, governance semantics, dispatch semantics, or execution behavior.

Affected regression tests:

- `test_stage3_4_10_routing_delegation_acceptance_regression_gate.py`
- `test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py`
- `test_stage3_8_10_observe_reconstruct_acceptance_regression_gate.py`
- `test_stage3_8_1_canonical_observability_trace_identity_contract.py`
- `test_stage3_8_6_deterministic_mission_timeline_reconstruction.py`
- `test_stage3_8_7_integrity_gap_consistency_diagnostics.py`
- `test_stage3_8_8_observability_metrics_health_operator_diagnostics.py`
- `test_stage3_8_9_forensic_query_evidence_bundle_reconstruction_api.py`

## Canonical supported-control tail

The authoritative tail is now asserted as:

`stage3.9.1 -> stage3.9.2 -> stage3.9.3 -> stage3.9.4`

with Stage 3.9.3 preserved as the immediate predecessor of Stage 3.9.4.

## Validation
The exact nine host-failing node IDs were rerun after the rebase:

`9 passed in 4.89s`

The Stage 3.9.4 acceptance script remains unchanged and should be rerun on the host to execute the canonical inventory and full regression.
