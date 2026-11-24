# Stage 3.6.8 Patch Notes

This patch advances the Mission Orchestrator head from Stage 3.6.7 to **Stage 3.6.8 — Verified Completion Declaration & Lifecycle Handoff**.

The stage adds immutable `mdecl-*` declarations that consume an exact current Stage-3.6.7 `READY` decision and revalidate its Stage-3.6.6 success-evaluation and Stage-3.6.5 mission-outcome evidence chain. A declaration is persisted before any lifecycle mutation.

After declaration, Stage 3.6.8 uses the existing canonical Stage-3.2 lifecycle command path—`BEGIN_CLEANUP` followed by `COMPLETE`—to transition `RUNNING -> CLEANING_UP -> COMPLETED`. The completion command receives exact Stage-3.2.8-compatible verified objective, criterion, cleanup, and dependency evidence. Direct state mutation is never used.

The patch adds migration 043, durable store `mission_verified_completion_declarations`, events `MISSION_VERIFIED_COMPLETION_DECLARED` and `MISSION_COMPLETION_LIFECYCLE_HANDOFF_COMPLETED`, create/list/get/definition APIs, idempotent partial-handoff recovery, repository reconstruction/integrity checks, health metadata, and regression-head rebasing to migration 43/control 3.6.8.

Focused build verification: Python compilation PASS, pytest collection exactly 1122, and focused Stage-3.6.8 20/20 PASS. `STAGE3_6_8_ACCEPTANCE.ps1` is the authoritative host-side full-regression gate.
