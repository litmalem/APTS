# Stage 3.7.7 Hotfix 1 — Regression Baseline Rebase

This is a **test-only** follow-up to Stage 3.7.7.

## Host evidence that triggered the hotfix

The authoritative host acceptance reached the complete canonical regression and reported:

- `1304` tests collected
- `1300 passed`
- `4 failed`
- runtime activation, authority-boundary proof, Python compile, and inventory checks all passed before the regression step

The four failing nodes were:

1. `tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py::test_12_stage35_supported_control_tail_is_complete_ordered_and_closed`
2. `tests/test_stage3_7_3_replan_eligibility_governance_gate.py::test_http_surface_exposes_stage373_routes_and_no_planner_or_commit_endpoint`
3. `tests/test_stage3_7_4_canonical_replan_snapshot_context_binding.py::test_http_surface_exposes_stage374_snapshot_routes_and_no_replan_commit_endpoint`
4. `tests/test_stage3_7_5_deterministic_replan_candidate_generation.py::test_http_surface_exposes_candidate_routes_and_no_commit_endpoint`

## Root cause

No Stage 3.7.7 runtime defect was exposed by the host run. The failures are stale regression expectations created by normal forward evolution of the control/API surface.

### A. Stage 3.5.10 supported-control positional baseline

The equality assertion for the complete current tail already passed, including:

- Stage 3.7.6
- Stage 3.7.7

However, the subsequent negative-index assertions were still calibrated to the prior tail length and omitted Stage 3.7.6 from the positional checks. Consequently, `tail[-18]` now resolves to Stage 3.5.10 rather than Stage 3.5.9.

The hotfix shifts the positional checks by one and explicitly verifies Stage 3.7.6 at `tail[-2]`, with Stage 3.7.7 remaining at `tail[-1]`.

### B. Stage 3.7.3–3.7.5 HTTP-surface baselines

These predecessor tests still asserted that the current `MissionOrchestratorHandler` source must not contain `replan-commit`.

That assertion was correct before Stage 3.7.7. It is no longer valid once Stage 3.7.7 intentionally introduces the authoritative commit surface:

- `GET /api/missions/{mission_id}/replan-commits`
- `GET /api/missions/{mission_id}/replan-commits/{commit_id}`
- `GET /api/missions/{mission_id}/replan-validations/{validation_id}/commit`
- `POST /api/missions/{mission_id}/replan-validations/{validation_id}/commit`
- the Stage 3.7.7 definition route

The predecessor tests are rebased so they continue to verify that their own Stage 3.7.3, 3.7.4, and 3.7.5 routes remain present while also accepting and verifying the intentional Stage 3.7.7 commit surface. The unrelated `replan-supersession` negative boundary remains intact.

## Scope

Test-only change. The hotfix does **not** modify:

- production runtime code
- database schema or migration level
- Stage 3.7.7 Governance authorization semantics
- successor Plan materialization
- active-head CAS behavior
- event contracts
- persistence store
- mission lifecycle/routing/delegation/dispatch/actuation authority boundaries

Stage 3.7.7 remains:

- control version: `stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization`
- repository migration level: `51`
- canonical pytest inventory: `1304`
- focused Stage 3.7.7 inventory: `22`

## Verification in the hotfix workspace

- Python compile: **PASS**
- canonical collection: **1304 tests collected**
- exact four formerly failing logical checks after rebase: **4 passed**
- focused Stage 3.7.7 suite: **22 passed in 26.46s**

A complete `1304`-test host regression is still required for formal acceptance because the host is the authoritative deployment environment.

## Installation

Extract `PATCH_STAGE3_7_7_HOTFIX1_REGRESSION_REBASE.zip` directly into:

`D:\mission_orchestrator`

and overwrite matching files under `tests\`.

No database migration and no service restart are required because this hotfix changes tests only. Then rerun:

`STAGE3_7_7_ACCEPTANCE.ps1`
