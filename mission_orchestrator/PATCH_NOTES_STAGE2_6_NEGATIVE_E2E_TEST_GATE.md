# Stage 2.6 Negative E2E Test Gate

Purpose: provide a deterministic, test-only synchronization barrier between TaskContract commit and authoritative pre-dispatch PolicyDecision revalidation.

Production behavior is unchanged unless `CTI_STAGE26_NEGATIVE_TEST_GATE` is explicitly enabled.

## Environment variables

- `CTI_STAGE26_NEGATIVE_TEST_GATE=1` enables the barrier.
- `CTI_STAGE26_NEGATIVE_TEST_GATE_DIR=<path>` optionally overrides the gate directory. Default: VulnDesk project root.
- `CTI_STAGE26_NEGATIVE_TEST_GATE_TIMEOUT_SECONDS=300` controls the maximum wait. Default: 300 seconds.

## Mission-specific release file

For mission `<mission_id>`, release the barrier by creating:

`.stage26-release-<mission_id>.gate`

The orchestrator deletes a stale mission-specific release file on entry, emits `PRE_DISPATCH_TEST_GATE_WAITING`, waits, then consumes the release file and emits `PRE_DISPATCH_TEST_GATE_RELEASED` before calling `_pre_dispatch_revalidate()`.

If the timeout expires, it emits `PRE_DISPATCH_TEST_GATE_TIMEOUT` and the mission fails closed without dispatch.

## Intended negative E2E sequence

1. PolicyDecision is issued as ALLOW / ACTIVE.
2. VulnDesk commits the REQUIRED TaskContract.
3. Gate pauses before revalidation.
4. Operator revokes the exact PolicyDecision through aptsGSS authoritative API.
5. Operator creates the mission-specific release file.
6. VulnDesk revalidates the exact bound PolicyDecision.
7. aptsGSS returns INVALID with `DECISION_STATUS_REVOKED`.
8. VulnDesk records `TASK_DISPATCH_BLOCKED`; the task must never emit `TASK_DISPATCHED`.

## Files changed

- `cti_services/cti_subsystem_orchestrator.py`
- `tests/test_stage26_negative_e2e_gate.py`

## Validation

50 selected Stage 1/2, D1/D2/D3, Stage 2.6, and gate regression tests pass.
