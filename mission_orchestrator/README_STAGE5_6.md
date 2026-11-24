# Stage 5.6 — Exploitation Agent

Stage 5.6 activates the bounded `PENTEST_EXPLOITATION_AGENT` as the proposal/validation-planning specialist that sits between Stage 5.5 attack-path planning and Stage 5.7 impact analysis.

The implementation follows the roadmap boundary: Stage 5.6 determines **what validation/exploitation action should be proposed**, while Stage 6 remains responsible for **how a controlled action is actually executed**.

## Implemented flow

```text
Stage 5.5 candidate attack path
        ↓ exact hash binding
candidate validation action
        ↓
Stage 4.8 eligibility / scope-RoE evaluation
        ↓
non-executing ValidationTask
        ↓
non-executing ExploitActionProposal
        ↓
Stage 4.9 ACTION_PROPOSAL lineage
        ↓
Stage 5.1 validation + exploitation handoff
        ↓
Stage 5.7 impact_analysis READY

Actual target execution: deferred to Stage 6
```

## Deliverables

- canonical Stage-5.6 contract and SHA-bound definition;
- `ExploitActionProposal` contract;
- `ValidationTask` contract;
- deterministic `xplrun-*` identity;
- exact Stage-5.5 run/output/evidence binding;
- Stage-4.8 validation + exploitation capability eligibility decisions;
- Stage-4.9 `ACTION_PROPOSAL` lineage for eligible/review-required candidates;
- Stage-5.1 progress handoff for `validation` and `exploitation` subtasks;
- durable migration 13 store `pentest_exploitation_runs`;
- idempotent replay, restart recovery, and integrity verification;
- Stage-5.6 HTTP API and active runtime `APTSPentestSubsystem/5.6`;
- 28 focused tests and acceptance script.

## Explicit execution boundary

Stage 5.6 deliberately does **not**:

- accept caller-supplied commands, payloads, exploit code, shellcode, binaries, or tool parameters;
- create a Stage-6 `ExecutionRequest`;
- execute vulnerability validation;
- execute exploitation;
- invoke raw tools or binaries;
- open target-network connections;
- actuate a target;
- create `ACTION_RESULT` records;
- create new target execution evidence;
- materialize confirmed `FINDING` records;
- mint `PolicyDecision` authorization.

Stage-4.8 scope/RoE decisions remain local eligibility decisions, not execution authorization. Stage 6 remains the controlled execution and execution-evidence authority.

## HTTP surface

Contract routes:

```text
GET /api/pentest/exploitation-agent-contract
GET /api/contracts/exploitation-agent
GET /api/contracts/exploit-action-proposal
GET /api/contracts/validation-task
GET /api/contracts/exploitation-evidence
```

Run/query routes:

```text
POST /api/pentest/agentic-orchestrations/{orchestration_id}/exploitation/run
POST /api/pentest/agentic-orchestrations/{orchestration_id}/validation-exploitation/run
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/exploitation
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/validation-exploitation
GET  /api/pentest/exploitation-runs/{run_id}
GET  /api/pentest/exploitation-runs
```

Historical Stage-5.5 and earlier routes remain available through handler inheritance. `POST /api/execution/dispatches` remains fail-closed with HTTP `409`.

## Acceptance

Start the Global Mission Orchestrator and Pentest runtime, then execute:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE5_6_ACCEPTANCE.ps1
```

Expected canonical inventory: **1957 tests**.
