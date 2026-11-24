# Stage 3.9.5 — Dispatch → Execution → Evidence Continuity

## Status

Implementation candidate for host acceptance. The active control is
`stage3.9.5-dispatch-execution-evidence-continuity`. Repository migration stays at
**53**; this stage introduces neither a database migration nor a durable store.

## Canonical E2E trajectory

The verified Stage 3.9.4 handoff is the input: the `collect-cti` root task is the
only READY task, has a `CTI / cti.read.context` route, has an authoritative
pre-delegation `ALLOW`, and has accepted handoff ownership. Stage 3.9.5 exercises
the existing authorities in this order:

1. The existing lifecycle command moves `PLANNING(v3)` to `RUNNING(v4)`.
2. Stage 3.5.1 materializes a canonical dispatch identity for that owned task.
3. Stage 3.5.2 checks static dispatch eligibility and execution preconditions.
4. Stage 3.5.3 obtains a **fresh authoritative** pre-dispatch Governance `ALLOW`.
5. Stage 3.5.4 commits one durable execution attempt and immutable envelope.
6. Stage 3.5.5 resolves/delivers to the injected sandbox runtime and records its acknowledgement.
7. Stage 3.5.6 observes `RUNNING` and a heartbeat for the same attempt.
8. Stage 3.5.7 captures the terminal `SUCCEEDED` result with an evidence manifest and optional artifact manifest. Both store SHA-256 references and provenance; inline payloads remain forbidden.

The segment head remains `RUNNING(v4)` with 31 Mission events and seven Stage 3.5
execution artifacts. There is one dispatch, eligibility gate, revalidation,
attempt, runtime acknowledgement, running projection, and result capture. No task
outcome, verified task completion, mission outcome aggregation, or mission success
declaration is committed. Stage 3.9.6 owns Completion → Outcome.

## Qualification and authority

The canonical, SHA-256-bound qualification contract anchors the immutable
Stage 3.9.4 contract digest. The verifier reads durable artifacts and the
verified event chain, checks the exact 22-event predecessor prefix and complete
31-event order, full predecessor repository integrity, identity/plan/task/route lineage, pre-dispatch `ALLOW`, single
attempt/envelope, runtime acknowledgement, heartbeat, manifest hashes, and exact
repository footprint. It also compares Stage 3.5.9 read-only execution replay
references with every durable execution artifact.

Read-only endpoints:

```text
GET /api/e2e/dispatch-execution-evidence-qualification-contract
GET /api/missions/{mission_id}/e2e-dispatch-execution-evidence-qualification
```

The verifier performs no Governance query, runtime I/O, dispatch redelivery,
attempt creation, target actuation, or lifecycle transition. The focused tests
exercise the real Stage 3.5 methods with injected deterministic Governance and
runtime doubles in the Stage 3.9 control-plane sandbox. The existing Stage
3.5.8 failure/termination controls and Stage 3.5.9 recovery checkpoints retain
their own authority; no recovery checkpoint is fabricated at this pre-outcome
segment head. Stage 3.9.8 will test restart/replay/recovery over the extended
E2E trajectory.

## Negative cases

Focused coverage rejects a missing terminal result, a pre-dispatch Governance
`DENY`, a stale revalidation request, missing evidence, and durable evidence
manifest or predecessor Plan drift. Exact attempt replay preserves the same attempt/envelope and
does not repeat delivery or append an event. Restart and repeated HTTP verifier
reads reconstruct the same segment without external calls.

## Acceptance

Copy the overlay into `D:\mission_orchestrator`, restart the application, then run
from that directory:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_5_ACCEPTANCE.ps1
```

The script checks the active runtime, contract endpoint, compilation, exact
test inventory, focused and predecessor tests, the Stage 3.5 regression, and
the complete historical regression. It does not authorize external target
actions.
