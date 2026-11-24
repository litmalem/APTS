# Patch Notes — Stage 3.6.4 Dependency-Aware Task Completion

Stage 3.6.4 introduces the canonical task-completion commit boundary. The implementation consumes a VERIFIED Stage-3.6.3 `ebind-*`, resolves the exact task and dependency set from the current active Plan, verifies that every prerequisite task already has an immutable same-Plan `tcomp-*`, and then creates one immutable dependency-consistent completion record.

The patch adds migration 039 and the `mission_task_completion_commits` durable store, registers the `MISSION_TASK_COMPLETION_COMMITTED` event, exposes POST/GET/history/definition APIs, extends repository reconstruction/integrity and persistence-manifest coverage, advances runtime identity to `stage3.6.4-dependency-aware-task-completion`, and adds 20 focused tests. Canonical regression inventory becomes 1042 tests.

This stage intentionally separates **completion truth** from **downstream activation**. It accepts and commits task completion, but does not transition task lifecycle state, release dependencies, recalculate readiness, progress the Plan, complete the Mission, query Governance/runtime, redispatch, create a new execution attempt, dispatch a new target action, perform external network I/O, or actuate a target. Those authorities remain outside Stage 3.6.4, with dependency release/readiness reserved for Stage 3.6.5.
