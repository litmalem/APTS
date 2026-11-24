# Stage 3.6.6 — Success-Criteria Satisfaction Evaluation

Stage 3.6.6 adds a deterministic, immutable, evidence-bound evaluation of the canonical Mission `success_criteria`. It consumes one authoritative Stage-3.6.5 Mission Outcome Aggregation from the active Plan and produces criterion-level results without exercising Mission-completion authority.

## Canonical identity

- control: `stage3.6.6-mission-success-criteria-evaluation`
- server: `APTSMissionOrchestrator/3.6.6`
- stage schema: `apts-mission-success-criteria-evaluation-v1`
- contract schema: `apts-mission-success-criteria-evaluation-contract-v1`
- identity prefix: `msceval-`
- migration: `041_stage3_6_6_mission_success_criteria_evaluation.sql`
- store: `mission_success_criteria_evaluations`
- event: `MISSION_SUCCESS_CRITERIA_EVALUATED`

## Evaluation semantics

Each Mission criterion is evaluated against deterministic evidence exposed by the Stage-3.6.5 aggregate. Supported aggregate metrics include `all_tasks_verified_complete`, `all_tasks_terminal`, `terminal_non_success_present`, the task classification counts, and `mission_execution_outcome_summary`.

Criterion results are `SATISFIED`, `NOT_SATISFIED`, or `INDETERMINATE`. Unsupported criterion shapes/metrics fail closed as `INDETERMINATE`; the evaluator never guesses semantic meaning from arbitrary natural-language or application-specific criteria.

The overall result is `SUCCESS_CRITERIA_SATISFIED`, `SUCCESS_CRITERIA_NOT_SATISFIED`, or `SUCCESS_CRITERIA_INDETERMINATE`. An empty criterion set or any indeterminate criterion yields an indeterminate overall result.

## Authority boundary

Stage 3.6.6 evaluates evidence only. It does not decide Mission-completion readiness, transition Mission state, progress or supersede a Plan, release dependencies, recalculate readiness, query Governance/runtime services, dispatch work, perform external network I/O, or actuate targets.

## API

- `POST /api/missions/{mission_id}/mission-success-criteria-evaluations`
- `GET /api/missions/{mission_id}/mission-success-criteria-evaluations`
- `GET /api/missions/{mission_id}/mission-success-criteria-evaluations/{evaluation_id}`
- `GET /api/missions/{mission_id}/mission-success-criteria-evaluation-definition`

Create requests bind optimistic Mission state/version, the active Plan head, and an exact Stage-3.6.5 aggregation id/hash. Idempotency-key reuse with a different canonical request is rejected.

## Verification status in this build

- Python module compilation: PASS.
- Canonical pytest inventory collection: **1082 tests**.
- Focused Stage-3.6.6 suite: **20 passed**.
- Stage-3.6.1 focused file: **19 passed** after current-head rebase.
- Stage-3.6.2 focused file: **20 passed** after current-head rebase.
- Full 1082-test regression was not completed in the build environment because execution exceeded the available tool window. `STAGE3_6_6_ACCEPTANCE.ps1` therefore remains the authoritative host-side full-regression gate.

## Next stage

Stage **3.6.7** should consume the Stage-3.6.6 result to determine Mission-completion readiness under explicit governance/lifecycle constraints. Stage 3.6.6 itself intentionally does not own that transition authority.
