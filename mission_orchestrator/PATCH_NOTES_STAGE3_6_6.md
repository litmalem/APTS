# Stage 3.6.6 Patch Notes

This patch advances the Mission Orchestrator head from Stage 3.6.5 to **Stage 3.6.6 — Success-Criteria Satisfaction Evaluation**.

The stage introduces an immutable `msceval-*` evaluation contract bound to the canonical Mission success criteria, the active Plan, the Mission version vector, and one exact Stage-3.6.5 `moutcome-*` aggregate. Supported deterministic aggregate metrics are compared directly to each criterion's `expected` value. Unsupported application-specific criteria fail closed as `INDETERMINATE`.

The stage adds migration 041, durable store `mission_success_criteria_evaluations`, canonical event `MISSION_SUCCESS_CRITERIA_EVALUATED`, create/list/get/definition APIs, idempotency, optimistic concurrency, restart reconstruction, repository integrity verification, and current-head regression rebasing.

The authority boundary remains strict: Stage 3.6.6 does not decide Mission-completion readiness, transition Mission state, progress Plans, release dependencies, query Governance/runtime, dispatch work, perform external network I/O, or actuate targets.

Verification performed in the build environment: Python compilation PASS; pytest collection exactly 1082; focused Stage-3.6.6 20/20 PASS; Stage-3.6.1 19/19 PASS; Stage-3.6.2 20/20 PASS. The complete 1082-test run was not completed inside the available tool window, so host-side `STAGE3_6_6_ACCEPTANCE.ps1` remains required for final acceptance.
