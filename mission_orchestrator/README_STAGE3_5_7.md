# Stage 3.5.7 — Execution Result / Evidence / Artifact Capture

Stage 3.5.7 closes the **authoritative runtime terminal-result capture boundary** after Stage 3.5.6 has established a durable RUNNING execution projection. The Mission Orchestrator reads the terminal result from the exact downstream runtime already bound by Stage 3.5.5, validates the immutable Stage 3.5.4/3.5.5/3.5.6 identities, and persists a canonical `xresult-*` record containing the terminal outcome plus immutable evidence/artifact manifests.

Stage 3.5.7 does **not** decide that the planned task or mission is complete. Result capture is evidence acquisition. Outcome verification and completion authority remain deferred to Stage 3.5.8.

## Runtime identity

- `control_version`: `stage3.5.7-execution-result-evidence-artifact-capture`
- HTTP server: `APTSMissionOrchestrator/3.5.7`
- repository migration: `33`
- schema: `apts-execution-result-evidence-artifact-capture-v1`
- identity prefix: `xresult-`
- store: `mission_execution_result_captures`
- mode: `AUTHORITATIVE_RUNTIME_TERMINAL_RESULT_WITH_IMMUTABLE_EVIDENCE_ARTIFACT_MANIFEST`
- authority: `DOWNSTREAM_SUBSYSTEM_RUNTIME_EXECUTION_RESULT`
- source mission state: `RUNNING`
- terminal execution states: `SUCCEEDED`, `FAILED`, `CANCELLED`, `TIMED_OUT`
- captured attempt status: `TERMINAL_RESULT_CAPTURED`
- runtime result channel: `RUNTIME_EXECUTION_TERMINAL_RESULT_READ`

## Execution-control lineage

`Stage 3.5.1 xdispatch -> Stage 3.5.2 xelig -> Stage 3.5.3 xreval -> Stage 3.5.4 xattempt/xenv -> Stage 3.5.5 xack -> Stage 3.5.6 xrun -> Stage 3.5.7 xresult`

The Stage-3.5.4 execution attempt, Stage-3.5.5 delivery acknowledgement, and Stage-3.5.6 RUNNING projection remain immutable source records. Stage 3.5.7 adds a separate append-only terminal-result evidence record.

## Required source bindings

Before any runtime result I/O, Stage 3.5.7 requires:

1. Mission remains in canonical `RUNNING` state and request concurrency guards match the current mission state/version vector.
2. The supplied active `pver-*` identity, version, and canonical SHA-256 match the active Plan head.
3. The supplied `xack-*` Stage-3.5.5 delivery exists, verifies cryptographically, and matches the current execution attempt.
4. The supplied `xattempt-*` and `xenv-*` Stage-3.5.4 identities and canonical SHA-256 values match the Stage-3.5.5 source binding.
5. The supplied `xrun-*` Stage-3.5.6 projection exists, verifies cryptographically, is `RUNNING / RUNNING_HEARTBEAT_CONFIRMED`, and is the **latest durable RUNNING projection for that execution attempt**.
6. No terminal result has already been captured for the execution attempt.

Stale mission state, version-vector, Plan, delivery, attempt, or RUNNING projection bindings fail closed **before** runtime result I/O.

## Runtime terminal-result protocol

Stage 3.5.7 reuses the exact runtime endpoint persisted by Stage 3.5.5. It does not resolve the endpoint again, does not redeliver the dispatch, and issues no new Governance authorization query.

The runtime is queried for the terminal execution result and must bind exactly to:

- `mission_id`
- `execution_attempt_id`
- `dispatch_envelope_id`
- target subsystem via `observed_by`
- `execution_started = true`
- terminal `execution_state` in `SUCCEEDED | FAILED | CANCELLED | TIMED_OUT`
- non-empty `completed_at`
- at least one authoritative evidence reference

A result can optionally include a human-readable summary and zero or more artifact references.

## Evidence and artifact manifests

Evidence is mandatory. Artifacts are optional.

Each evidence/artifact item is normalized to immutable manifest metadata:

- stable identifier
- `type`
- `uri`
- lowercase SHA-256 digest
- optional `media_type`
- optional non-negative `size_bytes`
- structured metadata

Stage 3.5.7 deliberately does **not** persist raw artifact/evidence payloads. Inline fields such as `content`, `data`, `payload`, `bytes`, `body`, `base64`, or `blob` are rejected. The Mission Orchestrator persists references, digests, provenance, counts, and canonical manifest hashes instead.

This design keeps large or sensitive runtime output outside the orchestration database while retaining enough material for deterministic integrity verification and later outcome validation.

## Idempotency and cardinality

- exact request replay with the same `idempotency_key` returns the original `xresult-*` record and performs no new runtime I/O;
- reusing an idempotency key with changed request content fails closed;
- only one terminal-result capture is permitted per execution attempt;
- a second idempotency key cannot create a second terminal result for the same `xattempt-*`.

## Event lineage and repository integrity

Each durable result capture emits:

`MISSION_EXECUTION_RESULT_EVIDENCE_ARTIFACT_CAPTURED`

The event carries the result identity, terminal execution state, canonical result SHA-256, evidence/artifact counts and manifest digests, and explicit non-completion semantics.

Repository reconstruction verifies:

- canonical result-capture contract integrity;
- one terminal result per execution attempt;
- source `xrun-*` existence/hash and attempt binding;
- evidence/artifact manifest count and digest consistency;
- event cardinality and event payload consistency;
- persistence-manifest inclusion;
- restart durability;
- tamper detection.

## Explicit non-authorities

Stage 3.5.7 performs:

- runtime health probe: **yes**
- runtime terminal-result query: **yes**
- terminal result capture: **yes**
- evidence-reference capture: **yes**
- artifact-reference capture: **when present**

Stage 3.5.7 does **not** perform:

- new Governance query
- runtime endpoint resolution
- dispatch redelivery
- new target-action dispatch
- task-completion decision
- mission state transition

A runtime `SUCCEEDED` result is therefore **not equivalent** to verified task completion. Stage 3.5.8 remains responsible for verification/completion semantics.

## API surface

- `POST /api/missions/{mission_id}/execution-result-captures`
- `GET /api/missions/{mission_id}/execution-result-captures`
- `GET /api/missions/{mission_id}/execution-result-captures/{result_capture_id}`
- `GET /api/missions/{mission_id}/execution-result-capture-definition`

## Verification

Windows acceptance:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_5_7_ACCEPTANCE.ps1
```

Focused Python proof:

```powershell
python -m pytest -q tests\test_stage3_5_7_execution_result_evidence_artifact_capture.py
```

Stage 3.5.7 closes only the terminal result/evidence/artifact capture boundary. **Stage 3.5.8** remains the next execution-lifecycle boundary.
