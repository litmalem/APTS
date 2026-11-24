# Stage 3.5.8 — Timeout, Cancellation, Abort & Failure Propagation

Stage 3.5.8 closes the **runtime termination-control and verified non-success propagation boundary** after Stage 3.5.7 has captured an authoritative terminal execution result.

The stage adds two related but deliberately separated functions:

1. **Runtime termination control** while the exact Stage-3.5.6 execution projection is still `RUNNING`.
   The Mission Orchestrator may issue `TIMEOUT`, `CANCEL`, or `ABORT` to the exact downstream runtime endpoint already bound by Stage 3.5.5, persist an immutable `xterm-*` acknowledgement, and then wait for Stage 3.5.7 to capture the terminal runtime result.
2. **Terminal outcome verification and propagation** after Stage 3.5.7 has captured `SUCCEEDED`, `FAILED`, `TIMED_OUT`, or `CANCELLED`.
   The Mission Orchestrator verifies the immutable result/evidence binding and persists a canonical `xprop-*` outcome record. Non-success outcomes propagate through the existing canonical Stage-3.2 lifecycle command path; `SUCCEEDED` is verified at task-execution level but does **not** complete the Mission.

## Runtime identity

- `control_version`: `stage3.5.8-timeout-cancellation-abort-failure-propagation`
- HTTP server: `APTSMissionOrchestrator/3.5.8`
- repository migration: `34`
- stage schema: `apts-execution-timeout-cancellation-abort-failure-propagation-v1`

Termination-control contract:

- schema: `apts-execution-termination-control-v1`
- identity prefix: `xterm-`
- store: `mission_execution_termination_controls`
- authority: `MISSION_ORCHESTRATOR_EXECUTION_CONTROL_INTENT`
- mode: `FAIL_CLOSED_RUNTIME_TIMEOUT_CANCELLATION_ABORT_CONTROL_PENDING_TERMINAL_RESULT`
- runtime channel: `RUNTIME_EXECUTION_TERMINATION_CONTROL`
- persisted status: `ACKNOWLEDGED_PENDING_TERMINAL_RESULT`

Outcome-propagation contract:

- schema: `apts-execution-terminal-outcome-propagation-v1`
- identity prefix: `xprop-`
- store: `mission_execution_outcome_propagations`
- authority: `MISSION_ORCHESTRATOR_VERIFIED_EXECUTION_OUTCOME_PROPAGATION`
- mode: `VERIFIED_TERMINAL_OUTCOME_WITH_FAIL_FAST_MISSION_FAILURE_PROPAGATION`

## Termination-control semantics

A termination control is valid only when:

- Mission state is `RUNNING`;
- the caller binds the current mission version vector and state version;
- the active Plan head is exact and current;
- the Stage-3.5.4 `xattempt-*`, Stage-3.5.5 `xack-*`, and latest Stage-3.5.6 `xrun-*` identities and hashes are exact;
- Stage-3.5.3 authoritative pre-dispatch authorization remains valid evidence for the attempt;
- no Stage-3.5.7 terminal `xresult-*` has already been captured for the attempt;
- no prior immutable Stage-3.5.8 termination control exists for the attempt.

Action mapping:

| Control action | Runtime terminal state expected |
|---|---|
| `TIMEOUT` | `TIMED_OUT` |
| `CANCEL` | `CANCELLED` |
| `ABORT` | `CANCELLED` |

The runtime endpoint is reused from Stage 3.5.5. Stage 3.5.8 performs a runtime health probe and one explicit control I/O. It performs **no endpoint re-resolution**, **no Governance re-query**, **no dispatch redelivery**, **no new target-action dispatch**, and **no Mission state transition** at control-request time.

Exact replay with the same idempotency key returns the original `xterm-*` record and performs no additional runtime I/O. Reuse of the same idempotency key with different canonical content fails closed. A second termination control for the same execution attempt is rejected.

## Terminal outcome verification and propagation

Stage 3.5.8 treats the immutable Stage-3.5.7 `xresult-*` as the authoritative terminal execution source. It does not query the runtime again during outcome propagation.

Canonical mapping:

| Stage-3.5.7 result | Stage-3.5.8 classification | Task outcome | Mission propagation |
|---|---|---|---|
| `SUCCEEDED` | `VERIFIED_SUCCESS` | `VERIFIED_COMPLETED` | none; Mission remains `RUNNING` |
| `FAILED` | `VERIFIED_FAILURE` | `VERIFIED_FAILED` | lifecycle `FAIL` → Mission `FAILED` |
| `TIMED_OUT` | `VERIFIED_TIMEOUT` | `VERIFIED_TIMED_OUT` | lifecycle `FAIL` → Mission `FAILED` |
| `CANCELLED` without prior control | `VERIFIED_CANCELLATION` | `VERIFIED_CANCELLED` | lifecycle `ABORT` → Mission `ABORTED` |
| `CANCELLED` after `CANCEL` | `VERIFIED_CANCELLATION` | `VERIFIED_CANCELLED` | lifecycle `ABORT` → Mission `ABORTED` |
| `CANCELLED` after `ABORT` | `VERIFIED_ABORT` | `VERIFIED_CANCELLED` | lifecycle `ABORT` → Mission `ABORTED` |
| `CANCELLED` after `TIMEOUT` | `VERIFIED_TIMEOUT` | `VERIFIED_TIMED_OUT` | lifecycle `FAIL` → Mission `FAILED` |

A runtime `SUCCEEDED` result after an acknowledged Stage-3.5.8 termination control is treated as an inconsistent trajectory and fails closed.

For non-success outcomes, Stage 3.5.8 uses a **deterministic canonical lifecycle command identity** derived from the Stage-3.5.7 result identity. This makes failure propagation idempotent and provides a crash-recovery path if the terminal lifecycle transition commits before the `xprop-*` row is persisted.

## Authority boundary

Stage 3.5.8 exercises **execution-outcome verification authority** and **non-success failure/abort propagation authority**. It deliberately does not exercise Mission success-completion authority.

Therefore:

- `SUCCEEDED` means the execution attempt has a verified successful terminal result;
- it does **not** mean the Mission is complete;
- successful Mission/task closure remains a later boundary;
- `FAILED`, `TIMED_OUT`, and `CANCELLED` are fail-fast and are propagated through the already-established canonical lifecycle control plane.

## Event lineage and repository integrity

New events:

- `MISSION_EXECUTION_TERMINATION_CONTROL_ACKNOWLEDGED`
- `MISSION_EXECUTION_TERMINAL_OUTCOME_PROPAGATED`

Repository reconstruction verifies both Stage-3.5.8 stores, their canonical hashes, source identity bindings, event cardinality/payload consistency, persistence-manifest inclusion, restart durability, and tamper detection.

## API surface

Termination control:

- `POST /api/missions/{mission_id}/execution-termination-controls`
- `GET /api/missions/{mission_id}/execution-termination-controls`
- `GET /api/missions/{mission_id}/execution-termination-controls/{termination_control_id}`

Outcome propagation:

- `POST /api/missions/{mission_id}/execution-outcome-propagations`
- `GET /api/missions/{mission_id}/execution-outcome-propagations`
- `GET /api/missions/{mission_id}/execution-outcome-propagations/{outcome_propagation_id}`

Definition:

- `GET /api/missions/{mission_id}/execution-timeout-cancellation-abort-failure-propagation-definition`

## Verification

Windows acceptance:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_5_8_ACCEPTANCE.ps1
```

Focused proof:

```powershell
python -m pytest -q tests\test_stage3_5_8_timeout_cancellation_abort_failure_propagation.py
```

Canonical inventory after Stage 3.5.8: **931 tests**, including **20 focused Stage-3.5.8 tests**.

Stage 3.5.8 closes the timeout/cancellation/abort/failure-propagation boundary. The declared next boundary is **Stage 3.5.9**.
