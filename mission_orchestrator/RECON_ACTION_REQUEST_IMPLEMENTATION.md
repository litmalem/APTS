# Stage 5.2 Recon Action Request contract

This update adds a versioned, integrity-bound `apts-recon-action-request-v1` artifact to Stage 5.2. Eligible Recon proposals now produce both the existing Stage 4.9 `ACTION_PROPOSAL` lineage record and an Action Request object in the immutable Recon run output (`output.action_requests`).

## Contract behavior

- Binds the Action Request to mission, Pentest task, orchestration, Recon run/subtask, and the persisted Stage 4.9 proposal reference and hash.
- Binds scope, task constraints, authorization reference, orchestration task graph, and capability registry snapshots by SHA-256.
- Uses only the server-owned Recon capability and the currently allowed `PASSIVE_DISCOVERY` technique. No adapter identifier, command, executable, or arbitrary target endpoint is accepted.
- Derives the target only from a target already in the immutable local task scope.
- Carries expected evidence, prerequisites, risk class, bounded timeout, deterministic idempotency key, correlation ID, causation ID, and policy version.
- Rejects missing or unknown fields and verifies the complete canonical SHA-256 integrity envelope.
- Marks requests `PROPOSED_AWAITING_STAGE6_INTAKE`. The contract does not grant authorization, create a Stage 6 execution request, invoke a tool, or perform target I/O. Stage 6 must still obtain and enforce fresh GSS authorization before any future execution integration.

## Contract endpoint

`GET /api/contracts/recon-action-request` returns the read-only Action Request contract and schema version. The existing Recon run response includes generated Action Requests under `run.output.action_requests`.

## Verification

The Stage 5.2 test suite covers valid generation and binding, unknown-field rejection, integrity tampering, and the read-only contract endpoint. No network/target collector was invoked during implementation or tests.
