# Stage 3.6.7 Patch Notes

This patch advances the Mission Orchestrator head from Stage 3.6.6 to **Stage 3.6.7 — Completion Readiness & Blockers**.

The stage introduces immutable `mready-*` contracts bound to the canonical Mission lifecycle/version vector, the current active Plan, and one exact Stage-3.6.6 `msceval-*` evaluation. Readiness is derived deterministically as `READY` or `BLOCKED`; blockers are explicit, ordered, and fail closed.

The patch adds migration 042, durable store `mission_completion_readiness_decisions`, canonical event `MISSION_COMPLETION_READINESS_EVALUATED`, create/list/get/definition APIs, idempotency, optimistic concurrency, restart reconstruction, repository-integrity verification, and current-head regression rebasing.

The authority boundary remains strict: Stage 3.6.7 does not transition Mission state, exercise Mission-success completion authority, progress Plans, release dependencies, query Governance/runtime, dispatch work, perform external network I/O, or actuate targets.

Build-environment verification: Python compilation PASS, pytest collection exactly 1102, and focused Stage-3.6.7 20/20 PASS. Host-side `STAGE3_6_7_ACCEPTANCE.ps1` remains the final full-regression gate.
