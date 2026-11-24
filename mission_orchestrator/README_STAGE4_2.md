# Stage 4.2 — PIP Ingestion, Validation & Binding

## Status

Implementation candidate for deployment-host acceptance.

Stage 4.2 extends the separate Pentest Subsystem introduced in Stage 4.1. The Global
Mission Orchestrator remains closed at:

`stage3.9.10-global-mission-orchestrator-acceptance-regression-gate`

The active Pentest control becomes:

`stage4.2-pip-ingestion-validation-binding`

Default local endpoints:

- Global Mission Orchestrator: `http://127.0.0.1:8780`
- Pentest Subsystem: `http://127.0.0.1:8790`

## Roadmap objective

Stage 4.2 introduces the **Pentest Intelligence Package (PIP)** as an intelligence artifact
that crosses into the Pentest domain only after fail-closed validation and exact binding.
The validation pipeline covers:

```text
PIP identity
mission binding
source CTI
freshness
integrity
scope
confidence
provenance
```

The core semantic rule is explicit:

> PIP is intelligence input, not an execution command.

## Canonical contracts

`pentest_subsystem/pip_contract.py` adds three canonical identities:

- Stage-4.2 control contract: `apts-stage4.2-pip-ingestion-validation-binding-v1`
- PIP artifact schema: `apts-pentest-intelligence-package-v1`
- binding envelope: `apts-stage4.2-pip-ingestion-binding-envelope-v1`

The Stage-4.2 contract is SHA-bound to the exact Stage-4.1 Pentest boundary contract.
Stage 4.1 remains the authority for the accepted Mission Orchestrator → Pentest handoff;
Stage 4.2 does not mutate that boundary.

## Canonical PIP shape

A valid PIP contains:

```text
schema_version
pip_id
pip_version
mission_id
pentest_id
task_id
source_cti
issued_at
expires_at
scope
confidence
provenance
intelligence
integrity
```

### Identity and binding

- `pip_id` uses the `pip-` namespace.
- `mission_id`, `pentest_id`, and `task_id` must exactly match the validated Stage-4.1
  handoff used for the same ingestion operation.
- Stage 4.2 does not create a new mission/task identity.

### Source CTI

`source_cti` requires:

```text
source_type = CTI
source_system
artifact_id
artifact_version
artifact_sha256
```

This stage validates supplied CTI provenance metadata but deliberately performs no remote
CTI lookup or external network I/O.

### Freshness

Timestamps are canonical RFC3339 UTC values ending in `Z`.

The PIP is valid only when:

```text
issued_at <= validation_time < expires_at
```

Future/not-yet-valid and stale/expired PIPs fail closed.

### Integrity

The PIP carries:

```text
algorithm        = SHA-256
canonicalization = UTF8_SORTED_JSON_V1
hash_domain      = APTS_PENTEST_INTELLIGENCE_PACKAGE_V1
canonical_sha256 = SHA-256(canonical PIP core)
```

Any content modification after sealing invalidates the artifact.

### Scope

Stage 4.2 uses a deliberately conservative rule: the PIP scope must exactly equal the
accepted Stage-4.1 boundary scope. It does not infer whether a changed scope is a legal
narrowing. Machine-enforceable scope/RoE transformation belongs to later Stage-4 controls.

### Confidence and provenance

- `confidence` is a finite numeric value in `[0, 1]`.
- `provenance.producer` is mandatory.
- `provenance.source_refs` must be non-empty and duplicate-free.

## Ingestion binding envelope

A successful ingestion produces a deterministic SHA-bound envelope containing:

- normalized Stage-4.1 boundary payload plus its canonical Stage-4.1 envelope SHA-256;
- validated PIP artifact;
- exact mission/pentest/task/PIP identity binding;
- scope hash binding;
- PASS evidence for all eight validation dimensions;
- explicit non-execution semantics.

The envelope states:

```text
ingested                 = true
validated                = true
bound                    = true
intelligence_input_only  = true
accepted_for_execution   = false
pentest_task_materialized= false
workflow_materialized    = false
persisted                = false
authorization_minted     = false
tool_invocation_performed= false
target_actuation         = false
```

## Authority boundary

Stage 4.2 does **not** implement later Stage-4 capabilities prematurely:

- no local Pentest task repository (Stage 4.3);
- no Pentest lifecycle state machine (Stage 4.4);
- no Pentest event persistence (Stage 4.5);
- no local workflow orchestrator (Stage 4.6);
- no capability/tool execution runtime (Stage 4.7+);
- no target actuation;
- no database migration or durable Pentest store.

A PIP may carry intelligence about techniques, observations, or hypotheses, but the PIP
itself cannot cause a tool invocation or execution dispatch.

## HTTP API

### Health

```text
GET /health
```

Declares active Stage-4.2 control, Stage-4.1 predecessor binding, PIP schemas, validation
dimensions, migration level `0`, and explicit non-execution/non-persistence semantics.

### Stage-4.1 boundary contract (preserved)

```text
GET /api/pentest/boundary-contract
GET /api/contracts/pentest-boundary
POST /api/pentest/boundary/validate
```

### Stage-4.2 PIP contract

```text
GET /api/pentest/pip-contract
GET /api/contracts/pip-ingestion
```

### PIP ingestion / validation / binding

```text
POST /api/pentest/pip/ingest
```

Request body:

```json
{
  "boundary": { "...": "Stage-4.1 handoff payload" },
  "pip": { "...": "canonical PIP artifact" }
}
```

The operation is stateless and returns a binding envelope. It does not persist the PIP as a
Pentest task or start a workflow.

### Execution remains disabled

```text
POST /api/execution/dispatches
```

The active Stage-4.2 runtime rejects this route with HTTP `409` and
`STAGE4_2_EXECUTION_INTAKE_NOT_ENABLED`.

## Running Stage 4.2

From `D:\mission_orchestrator`:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\START_STAGE4_2_PENTEST.ps1
```

Equivalent direct command:

```powershell
python -m run.pentest_subsystem --host 127.0.0.1 --port 8790
```

Keep the Global Mission Orchestrator running on port `8780`.

## Acceptance

In another PowerShell window:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE4_2_ACCEPTANCE.ps1
```

The acceptance harness verifies:

- Stage-3.9.10 global predecessor remains closed;
- canonical Stage-4.1 boundary predecessor remains valid;
- Stage-4.2 runtime/control activation;
- canonical PIP contract/schema;
- successful fresh/integrity-valid PIP ingestion and exact binding;
- rejection of tampered, stale, or incorrectly bound PIPs through focused tests;
- explicit rejection of execution dispatch;
- Python compilation;
- canonical inventory of **1605 tests**;
- 15 focused Stage-4.2 tests;
- Stage-4.1 and critical Stage-3 predecessor regressions;
- full historical regression as final PASS/FAIL authority.

## Local qualification in this patch build

Completed locally:

```text
Python compilation: PASS
Canonical inventory: 1605 tests
Focused Stage 4.2: 15 passed
Focused Stage 4.1: 15 passed
Critical Stage-3/4 regression subset: 89 passed
```

The complete 1605-test historical suite is intentionally delegated to
`STAGE4_2_ACCEPTANCE.ps1` on the deployment host because prior runtime-facing tests can
exceed the interactive build window.

## Next stage

**Stage 4.3 — Pentest Mission & Task Contract**.
