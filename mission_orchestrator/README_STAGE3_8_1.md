# Stage 3.8.1 — Canonical Observability & Trace Identity Contract

Stage 3.8.1 opens the observability track by defining a canonical, deterministic **Mission root trace identity** without adding telemetry export, runtime probing, operational authority, a durable store, or a database migration.

## Runtime identity

- `control_version`: `stage3.8.1-canonical-observability-trace-identity-contract`
- HTTP `server_version`: `APTSMissionOrchestrator/3.8.1`
- repository migration level: `53` (**unchanged**)
- new database migration: **none**
- new durable store: **none**
- trace schema: `apts-canonical-observability-trace-identity-v1`
- trace-context schema: `apts-observability-trace-context-v1`

## Contract semantics

The Mission root `trace_id` and `root_span_id` are derived deterministically from the immutable canonical Mission identity:

`mission_id + canonical envelope SHA-256 + explicit hash domain`

The emitted identifiers use W3C-compatible widths (32 lowercase hexadecimal characters for `trace_id`, 16 for `span_id`), but Stage 3.8.1 does **not** yet implement cross-process propagation or an exporter. Those belong to later observability stages.

Because the identity is derived from already-durable Mission data, it is stable across process restart and does not require a new table. Repeated reads are side-effect free and do not append Mission events.

## Authority boundary

Stage 3.8.1 is a read-only identity/projection control. It does not:

- authorize Governance or execution;
- query an external runtime or telemetry backend;
- create routing, delegation, dispatch, or execution attempts;
- mutate Mission state or Plan state;
- dispatch or actuate a target;
- add a database migration or durable store.

## API

- `GET /api/missions/{mission_id}/observability-trace`
- `GET /api/observability/trace-contract`

## Verification

Run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_8_1_ACCEPTANCE.ps1
```

The target-host harness validates runtime activation, Python compilation, exact canonical test inventory, full regression, the focused Stage 3.8.1 suite, predecessor Stage 3.7.10 non-regression, deterministic restart-stable trace identity, no repository/event mutation, and the final no-authority/no-I/O/no-actuation boundary.
