# Autonomous PIP-bound planning and Recon scope intake

## Install

Apply the files in this overlay to the matching paths at the root of the
combined APTS source tree. Keep Mission and Pentest configured to use the same
`APTS_PENTEST_DB`. Restart the Mission Orchestrator and Pentest Workspace after
copying the files.

The existing Mission worker already polls every 30 seconds. It now recovers
both `PIP_BOUND` and partially completed `PLANNING` missions. Once the active
GSS scope and immutable PIP have passed validation, the worker uses the guarded
`START_PLANNING` lifecycle command and creates the canonical plan, planner input
snapshot, task decomposition, dependency graph, deterministic planner output,
and feasibility validation. The stable idempotency keys allow it to resume
after a process restart.

Per allowed target, the plan lays out Recon context → WPT evidence intake →
Recon enrichment → Vulndesk CTI enrichment. These are planning definitions and
dependencies, not dispatched work.

## Recon target display

The active Pentest Workspace receives each current GSS scope target in the
Recon target selector as `Target scope · … · belum diobservasi`. Selecting a URL
loads it into the Recon target field. The entry is bound to its Mission, GSS
scope contract/version/hash, and source snapshot hash.

This is a durable declared-target context record. It does not create a Pentest
task, activate an orchestration, create a Recon run, import observations, or
contact the target. Stage 4.3 task materialization and fresh GSS authorization
for target actions remain separate guarded steps.

## Validation

`tests/test_autonomous_planning_handoff.py` covers AutoPIP through feasible
planning, durable Recon scope registration, replay idempotency, and the absence
of Recon runs. `tests/test_automatic_pip.py` updates the recovery sweep
expectation. The implementation was also exercised with a local end-to-end
test harness; Python sources compile and the Pentest UI JavaScript passes
`node --check`.
