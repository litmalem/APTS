# Stage 3.2.8 Acceptance Hotfix — Mission Event Cardinality

## Root cause

The Stage 3.2.8 runtime implementation is correct. A successful guarded lifecycle command intentionally persists:

1. exactly one canonical state transition, which emits `MISSION_STATE_TRANSITIONED`; and
2. exactly one completed command-journal record, which emits `MISSION_COMMAND_COMPLETED`.

Therefore a successful `COMPLETE` command advances the Mission event ledger by **two** canonical events, not one.

The original Stage 3.2.8 acceptance script incorrectly asserted `event_count + 1`. This contradicted the preserved Stage 3.1.6 command-journal semantics and Stage 3.1.9 Mission event lineage. Stage 3.2.7 already treated terminal lifecycle commands consistently by requiring event growth rather than exactly one total event.

## Changes

- Correct Stage 3.2.8 acceptance Section [9] to require exactly:
  - one state transition;
  - one `MISSION_STATE_TRANSITIONED` event;
  - one `MISSION_COMMAND_COMPLETED` event.
- Verify the state-transition event is causally bound to the committed `COMPLETED` transition.
- Verify the command-completed event is causally bound to the exact `COMPLETE` command.
- Verify local parent chaining places `MISSION_COMMAND_COMPLETED` immediately after `MISSION_STATE_TRANSITIONED`.
- Preserve the replay assertion: exact replay appends neither another transition nor another Mission event.
- Strengthen the existing Stage 3.2.8 pytest replay test with the same initial event-cardinality/causality assertions.

## Runtime impact

None. No Mission Orchestrator runtime source file changes. No database migration. No Governance change. No target execution/actuation change.

## Validation

- Python compile: PASS
- Full regression: **234 passed**
