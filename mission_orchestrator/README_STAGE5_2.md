# Stage 5.2 — Reconnaissance Agent

Stage 5.2 activates the first Stage-5 specialist implementation under the Stage-5.1 local multi-agent orchestrator.

Active control:

`stage5.2-reconnaissance-agent`

Predecessor: `stage5.1-full-agentic-pentest-workflow-orchestrator`  
Pentest repository migration: **10** (bootstrap uses independent sidecar schema **v1**)  
Next: **5.3 — Enumeration Agent**

## Roadmap loop

The Reconnaissance Agent implements the Stage-5.2 control loop:

```text
Observe
→ Reason
→ Propose
→ Govern
→ Act
→ Observe
```

At this stage, **Act means publishing a governed discovery action proposal**, not directly running a scanner or opening a target connection. Controlled target execution remains a Stage-6 responsibility. This preserves the project invariants that specialist agents do not bypass governance or raw-tool boundaries.

## Implemented behavior

The agent accepts canonical, imported reconnaissance observations bound to an existing Stage-5.1 orchestration and its immutable Pentest task/boundary. It then:

1. validates the Stage-4.1 boundary against the immutable Pentest task;
2. normalizes HOST, DOMAIN, SERVICE, ATTACK_SURFACE, and RAW_EVIDENCE observations;
3. deterministically aggregates hosts, domains, services, attack-surface state, and confidence;
4. writes every imported observation as a Stage-4.9 `OBSERVATION` plus `EVIDENCE` lineage pair;
5. evaluates each proposed discovery action through Stage-4.8 scope/RoE enforcement;
6. additionally enforces the narrower local Pentest-task target scope;
7. publishes eligible/reviewable `ACTION_PROPOSAL` lineage records without execution;
8. persists a hash-bound Recon Evidence Bundle;
9. marks the Stage-5.1 reconnaissance subtask `SUCCEEDED` and releases Enumeration to `READY`.

## Recon output contract

Every completed run returns the roadmap-required output families:

```text
hosts
domains
services
attack_surface
raw_evidence
confidence
```

It additionally returns governance evaluations and any governed action proposals. Raw evidence is represented by canonical lineage references and SHA-256 digests rather than unbounded inline bytes.

## Durable state

Migrations `009_stage5_2_reconnaissance_agent.sql` and `010_stage5_2_recon_iteration.sql` add:

- `pentest_recon_runs`

The store binds:

- deterministic `recon_run_id`;
- immutable request hash;
- Stage-5.1 orchestration/subtask identity;
- mission/pentest/task lineage;
- canonical Recon output hash;
- canonical Recon Evidence Bundle hash;
- completion timestamps.

Exact replay is idempotent. Restart at migration level 10 is supported and does not downgrade predecessor repository metadata.

## Recon bootstrap contract

`POST /api/pentest/agentic-orchestrations/{orchestration_id}/reconnaissance/bootstrap` creates a durable **bootstrap anchor**, not a completed Recon run. The server derives target and scope only from the immutable Pentest task bound to the orchestration; callers cannot submit their own target, scope, observations, or evidence.

The bootstrap record is `READY_FOR_COLLECTION` and SHA-256 bound to the task, scope, and request. It does not create observations, evidence, Stage 6 requests, authorization, or external network traffic. It does not mark the Recon subtask complete or release Enumeration. That boundary avoids recording a task declaration as if it were a scan result. The following integration step can use this anchor to request an authorized Stage 6 WPT collection; only a verified Stage 6 result can become a Recon run.

The bootstrap table has a separately versioned sidecar schema so it does not alter the shared Pentest repository migration counter.

## APIs

```text
GET  /api/pentest/reconnaissance-agent-contract
GET  /api/contracts/reconnaissance-agent
GET  /api/contracts/recon-evidence
GET  /api/contracts/reconnaissance-bootstrap
GET  /api/pentest/reconnaissance-runs
GET  /api/pentest/reconnaissance-runs/{recon_run_id}
GET  /api/pentest/reconnaissance-bootstraps/{bootstrap_id}
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/reconnaissance
POST /api/pentest/agentic-orchestrations/{orchestration_id}/reconnaissance/run
POST /api/pentest/agentic-orchestrations/{orchestration_id}/reconnaissance/bootstrap
```

`POST /api/execution/dispatches` remains fail-closed (`409`).

## Authority boundary

Stage 5.2 explicitly keeps the following disabled:

- raw tool or binary access by the specialist;
- direct external target-network I/O;
- target actuation;
- creation of `PolicyDecision` authorization;
- Stage-6 controlled execution intake.

Stage-4.8 scope/RoE decisions remain **eligibility decisions, not authorization artifacts**.

## Acceptance

Start the current Pentest runtime on port 8790 and run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE5_2_ACCEPTANCE.ps1
```

Expected inventory: **1847 tests**.
