# Stage 4.10 — Pentest Foundation Acceptance Gate

Stage 4.10 closes **Stage 4 — APTS Pentest Subsystem Foundation**. It is an acceptance and regression gate, not a new execution phase. The runtime exposes a SHA-256-bound closure contract while the external PowerShell acceptance harness remains the authoritative PASS/FAIL mechanism.

## Active control

`stage4.10-pentest-foundation-acceptance-gate`

Predecessor: `stage4.9-evidence-finding-lineage-foundation`  
Pentest repository migration: **7 (unchanged)**  
Stage 4 output: **PENTEST_SUBSYSTEM_PLATFORM**  
Next stage: **5.1 — Full Agentic Pentest Workflow Orchestrator**

## Roadmap acceptance dimensions

The canonical Stage-4.10 contract binds the exact master-roadmap acceptance set:

1. persistence;
2. restart;
3. replay;
4. idempotency;
5. duplicate PIP;
6. stale PIP;
7. invalid scope;
8. denied action;
9. stop/kill;
10. event ordering;
11. cross-subsystem lineage.

Each dimension is mapped to already-implemented Stage-4 regression evidence. Stage 4.10 does not invent a second runtime implementation for these properties; it freezes their required evidence into the closure contract and executes them through `STAGE4_10_ACCEPTANCE.ps1`.

## Closure model

```text
Stage 3.9.10 Global Mission Orchestrator closure
                      │
                      ▼
4.1 Boundary / canonical contract
                      │
                      ▼
4.2 PIP validation / freshness / binding
                      │
                      ▼
4.3 Pentest mission/task contract + persistence
                      │
                      ▼
4.4 Lifecycle / state / abort semantics
                      │
                      ▼
4.5 Event runtime / ordering / replay
                      │
                      ▼
4.6 Local workflow skeleton / idempotency
                      │
                      ▼
4.7 Capability registry / tool contracts
                      │
                      ▼
4.8 Scope + RoE enforcement / deny + stop
                      │
                      ▼
4.9 Evidence / finding / cross-subsystem lineage
                      │
                      ▼
4.10 Pentest Foundation Acceptance Gate
                      │
          external acceptance harness
                      │
                      ▼
             PASS => STAGE 4 CLOSED
                      │
                      ▼
       PENTEST_SUBSYSTEM_PLATFORM
                      │
                      ▼
                   5.1
```

## Runtime semantics

The closure gate is deliberately declarative:

- `declared_only = true`;
- `runtime_self_certification = false`;
- `external_acceptance_execution_required = true`;
- `full_historical_regression_required = true`.

A `/health` response therefore declares the contract and expected evidence but never self-asserts that the deployment has passed acceptance.

## API

Read-only closure contract:

```text
GET /api/pentest/foundation-acceptance-gate-contract
GET /api/contracts/pentest-foundation-acceptance-gate
```

All Stage-4.1 through Stage-4.9 APIs remain available through the inherited handler/service chain.

## Authority boundary

Stage 4.10 adds no:

- database migration;
- durable store;
- `PolicyDecision` minting authority;
- target execution authority;
- tool invocation authority;
- external network I/O;
- target actuation.

`POST /api/execution/dispatches` remains fail-closed with `409`. Controlled target execution remains Stage 6 authority.

## Acceptance harness

Run after deploying the package and restarting both Mission Orchestrator (`8780`) and Pentest Subsystem (`8790`):

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE4_10_ACCEPTANCE.ps1
```

The harness validates:

- Stage 3.9.10 predecessor control;
- active Stage-4.10 control, server version, and migration 7;
- SHA-bound closure contract;
- execution-intake negative boundary;
- Python compilation;
- canonical inventory (**1799 tests**);
- focused Stage-4.10 regression (**15 tests**);
- Stage-4.1 → Stage-4.10 qualification chain (**224 tests** in the implementation environment);
- explicit roadmap acceptance-dimension regression (**31 tests** in the implementation environment);
- critical Stage-3 → Stage-4 closure regression (**105 tests** in the implementation environment);
- full historical pytest regression as final deployment-host PASS/FAIL authority.

## Implementation-environment evidence

Completed before packaging:

- Python compilation: **PASS**
- canonical inventory: **1799 tests collected**
- focused Stage 4.10: **15 passed**
- Stage 4.1 → 4.10 regression: **224 passed**
- explicit roadmap-dimension regression: **31 passed**
- critical Stage 3 → Stage 4 regression: **105 passed**

The full 1799-test historical suite is intentionally left to `STAGE4_10_ACCEPTANCE.ps1` on the deployment host, consistent with the closure contract's external-harness authority.
