# Stage 4.1 — Pentest Boundary & Canonical Contract

## Status

Implementation candidate for deployment-host acceptance.

Stage 4 begins a **new Pentest Subsystem runtime boundary** rather than extending the
Global Mission Orchestrator as though Stage 4 were another Stage-3 control. The Stage-3
orchestrator therefore remains closed at:

`stage3.9.10-global-mission-orchestrator-acceptance-regression-gate`

while the Pentest runtime activates:

`stage4.1-pentest-boundary-canonical-contract`

Default local endpoints:

- Global Mission Orchestrator: `http://127.0.0.1:8780`
- Pentest Subsystem: `http://127.0.0.1:8790`

## Roadmap objective

The Stage-4 master roadmap defines the subsystem boundary as:

```text
Mission Orchestrator
        ↓
Pentest Subsystem
        ↓
Pentest Workflow
```

and requires the canonical handoff fields:

```text
pentest_id
mission_id
task_id
scope
objective
constraints
RoE
authorization_reference
```

The implementation uses the machine field name `roe` for RoE.

## Canonical boundary contract

`pentest_subsystem/boundary_contract.py` introduces a SHA-256-bound contract that binds:

1. the closed Stage-3.9.10 Global Mission Orchestrator acceptance contract;
2. the canonical Stage-3.4.1 `PENTEST` subsystem registry contract;
3. the eight required Stage-4.1 handoff fields;
4. an explicit ownership model;
5. a fail-closed authority boundary;
6. the handoff to Stage 4.2.

Schema identities:

- boundary contract: `apts-stage4.1-pentest-boundary-canonical-contract-v1`
- validation envelope: `apts-pentest-boundary-handoff-envelope-v1`

## Ownership model

The boundary deliberately separates authority:

| Artifact | Authority | Stage-4.1 Pentest semantics |
|---|---|---|
| `mission_id` | Global Mission Orchestrator | immutable root-lineage reference |
| `task_id` | Global Mission Orchestrator | immutable upstream task reference |
| `scope` | Global Mission Orchestrator scope contract | may narrow; never widen |
| `objective` | Global Mission Orchestrator | read-only objective binding |
| `constraints` | Global Mission Orchestrator scope contract | mandatory; non-relaxable |
| `roe` | Global Mission Orchestrator scope contract | mandatory; non-relaxable |
| `authorization_reference` | external `aptsGSS` | reference only; Pentest cannot mint `ALLOW` |
| `pentest_id` | Pentest Subsystem | local Pentest lineage root |

The boundary contract does **not** treat a task, authorization, execution, or outcome as
interchangeable objects.

## Stage-4.1 authority boundary

Stage 4.1 is intentionally a contract/boundary stage. It does **not** implement later Stage-4
capabilities prematurely:

- no PIP ingestion (Stage 4.2);
- no local Pentest task repository (Stage 4.3);
- no Pentest lifecycle state machine (Stage 4.4);
- no Pentest event persistence (Stage 4.5);
- no local workflow orchestrator (Stage 4.6);
- no tool/capability execution runtime (Stage 4.7+);
- no target actuation;
- no database migration or durable Pentest store.

`POST /api/execution/dispatches` is therefore explicitly rejected with HTTP `409` and
`STAGE4_1_EXECUTION_INTAKE_NOT_ENABLED`. This is deliberate fail-closed behavior, not an
unimplemented silent fallback.

## HTTP API

### Health

```text
GET /health
```

Declares subsystem identity `PENTEST`, active Stage-4.1 control, predecessor binding,
contract hashes, required fields, ownership/invariants, migration level `0`, and the explicit
non-execution boundary.

### Canonical contract

```text
GET /api/pentest/boundary-contract
GET /api/contracts/pentest-boundary
```

Both aliases return the same read-only canonical boundary contract and definition.

### Validation-only handoff

```text
POST /api/pentest/boundary/validate
```

This validates and SHA-binds a proposed handoff object. It does not persist the object, start a
workflow, invoke a tool, make a governance decision, or actuate a target.

## Running the Pentest boundary runtime

From `D:\mission_orchestrator` in a separate PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\START_STAGE4_1_PENTEST.ps1
```

Equivalent direct command:

```powershell
python -m run.pentest_subsystem --host 127.0.0.1 --port 8790
```

Keep the existing Global Mission Orchestrator running on port `8780`.

## Acceptance

In another PowerShell window:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE4_1_ACCEPTANCE.ps1
```

The acceptance harness verifies:

- Stage-3.9.10 predecessor closure and `4.1` handoff;
- Pentest subsystem runtime identity/control;
- predecessor and registry binding;
- canonical contract API;
- validation-only handoff envelope;
- explicit rejection of execution dispatch;
- Python compilation;
- canonical inventory of **1590 tests**;
- 15 focused Stage-4.1 tests;
- boundary-critical Stage-3 regressions;
- full historical regression as final PASS/FAIL authority.

## Local qualification in this patch build

Completed locally:

```text
Python compilation: PASS
Canonical inventory: 1590 tests
Focused Stage 4.1: 15 passed
```

The authoritative deployment-host PASS remains the complete
`STAGE4_1_ACCEPTANCE.ps1` run, including its full historical regression.

## Next stage

**Stage 4.2 — PIP Ingestion, Validation & Binding**.
