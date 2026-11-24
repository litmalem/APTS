# Stage 3.9.8 patch notes

- Added SHA-256-bound **Restart / Replay / Recovery E2E Verification** contract and evaluator.
- Reused the existing Stage 3.7.9 recovery checkpoint authority; no new persistence or recovery authority was added.
- Extended the Stage 3.9.7 canonical 49-event head with exactly one `MISSION_REPLAN_RECOVERY_CHECKPOINTED` event.
- Canonical Stage 3.9.8 trajectory is 50 Mission events; adaptation/replan replay is exactly 10 events.
- Added durable restart verification using a fresh service instance bound to the same SQLite repository.
- Verifies exact mission state, active Plan v2, repository footprint, event chain/tip, replay sequence, and recovery projection before/after restart.
- Requires `recovery_consistency = PASS` and `recovered_from_durable_repository = true`.
- Verifies exact recovery-checkpoint request replay remains idempotent after restart with no duplicate event or record.
- Added tamper-negative coverage for persisted recovery checkpoint integrity.
- Added read-only contract/qualification routes and Stage 3.9.8 health fields.
- Rebases historical current-control/server-version assertions to Stage 3.9.8 while retaining Stage 3.9.7 in ordered supported-control history.
- Repository migration remains **53**.
- Canonical test inventory becomes **1545**; focused Stage 3.9.8 suite has **14 tests**.
