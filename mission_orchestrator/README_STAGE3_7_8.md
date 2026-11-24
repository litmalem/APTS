# Stage 3.7.8 — Atomic Replan Commit, Supersession & Handoff

Stage 3.7.8 finalizes the Stage-3.7 adaptation episode after Stage 3.7.7 has already performed the authoritative Governance revalidation, appended the successor Plan version, and atomically advanced the active Plan head.

## Runtime contract

- `control_version`: `stage3.7.8-atomic-replan-commit-supersession-handoff`
- repository migration: `52`
- stage schema: `apts-atomic-replan-commit-supersession-handoff-v1`
- contract schema: `apts-replan-supersession-handoff-contract-v1`
- identity prefix: `rphof-`
- persistence store: `mission_replan_handoffs`
- event: `MISSION_REPLAN_HANDOFF_READY`
- effective adaptation state: `HANDOFF_READY`
- downstream control: `STAGE3_4_ROUTING_THEN_STAGE3_5_DISPATCH`

## Architectural split from Stage 3.7.7

Stage 3.7.7 owns the actual atomic successor materialization and active-head CAS. Stage 3.7.8 does not rewrite that commit. Instead it verifies the committed predecessor/successor relation and active head, derives a deterministic in-flight task disposition projection, persists an immutable handoff record, and publishes the replay-safe handoff event.

This split preserves append-only Plan history and avoids a second Plan-head mutation.

## Task disposition policy

The canonical vocabulary is:

- `KEEP` — completed work or unfinished work retained by the successor and not currently in flight.
- `DRAIN` — valid retained work that is already in flight; existing execution is allowed to drain without a new dispatch.
- `CANCEL` — invalidated work that is already in flight. Stage 3.7.8 only declares that Stage 3.5 termination control is required; it performs no cancellation I/O.
- `SUPERSEDE` — invalidated work that is not in flight.
- `REPLACE` — reserved for an explicit future replacement mapping with a new task identity. The current deterministic Stage-3.7.5 candidate generator does not emit replacement identities.

Completed tasks are always preserved. Historical Plan rows are never mutated.

## Fail-closed guards

A handoff is rejected when any of these change after Stage 3.7.7:

- ReplanCommit identity/hash;
- predecessor Plan identity/version/hash;
- successor Plan identity/version/hash;
- active Plan head (must still be exactly the Stage-3.7.7 successor);
- Mission state/state_version;
- successor causal binding to the Stage-3.7.7 ReplanCommit.

The repository repeats the active-head and Mission-state checks inside the database transaction that inserts the handoff row.

## Authority boundary

Stage 3.7.8 **does**:

- verify Stage-3.7.7 atomic commit evidence;
- verify effective predecessor supersession and active successor head;
- derive deterministic task dispositions from durable local state;
- persist immutable handoff evidence;
- emit a replay-safe `MISSION_REPLAN_HANDOFF_READY` event.

Stage 3.7.8 **does not**:

- mutate historical Plan rows;
- transition Mission lifecycle state;
- query Governance;
- perform cancellation I/O;
- route or delegate tasks;
- dispatch execution;
- create execution attempts;
- perform target action dispatch or target actuation.

The actual downstream execution path remains successor Plan → Stage 3.4 routing/delegation → Stage 3.5 dispatch/execution.

## API

- `POST /api/missions/{mission_id}/replan-commits/{replan_commit_id}/handoff`
- `GET /api/missions/{mission_id}/replan-commits/{replan_commit_id}/handoff`
- `GET /api/missions/{mission_id}/replan-handoffs`
- `GET /api/missions/{mission_id}/replan-handoffs/{replan_handoff_id}`
- `GET /api/missions/{mission_id}/atomic-replan-commit-supersession-handoff-definition`

## Verification inventory

The Stage-3.7.8 focused suite contains 18 tests. The Stage-3.7.7 predecessor suite contains 22 tests. Canonical collection after this patch is 1322 tests.

Run `STAGE3_7_8_ACCEPTANCE.ps1` on the target host for the authoritative full Stage 3.1–3.7.8 regression gate.
