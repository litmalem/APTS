# Stage 5.1 — Full Agentic Pentest Workflow Orchestrator

Stage 5.1 is the first Stage-5 control and converts the Pentest Subsystem from a qualified platform into a **local multi-agent orchestration control plane**.

Active control:

`stage5.1-full-agentic-pentest-workflow-orchestrator`

Predecessor: `stage4.10-pentest-foundation-acceptance-gate`  
Pentest repository migration: **8**  
Next: **5.2 — Reconnaissance Agent**

## What is implemented

The local supervisor now performs the control-plane sequence:

```text
understand canonical task
→ decompose
→ assign specialist roles
→ observe progress
→ aggregate state
→ evaluate progress
→ replan
→ terminate / escalate
```

Task understanding is contract-driven rather than free-form model inference. Decomposition is deterministic and produces a versioned Agent Task Graph using the seven Stage-4.7 capabilities.

Specialist role assignments are created for Reconnaissance, Enumeration, Vulnerability Hypothesis, Attack-Path Planning, Exploitation/Validation, and Post-Exploitation Impact. At Stage 5.1 these are **role ownership records only**; their implementations arrive in Stages 5.2–5.7.

## Durable state

Migration 008 adds:

- `pentest_agentic_orchestrations`
- `pentest_agentic_plan_revisions`
- `pentest_agentic_progress_records`
- `pentest_agentic_replan_records`

Exact start/progress/replan replays are idempotent. Agent Task Graph state is hash-verified on read, and plan revisions are versioned.

## API

```text
GET  /api/pentest/agentic-orchestrator-contract
GET  /api/contracts/agentic-pentest-orchestrator
GET  /api/pentest/agentic-orchestrations
GET  /api/pentest/agentic-orchestrations/{orchestration_id}
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/plan-revisions
GET  /api/pentest/tasks/{pentest_task_id}/agentic-orchestration
POST /api/pentest/tasks/{pentest_task_id}/agentic-orchestration/start
POST /api/pentest/agentic-orchestrations/{orchestration_id}/progress
POST /api/pentest/agentic-orchestrations/{orchestration_id}/replan
```

`POST /api/execution/dispatches` remains fail-closed (`409`).

## Replanning actions

- `RETRY_FAILED`
- `REBUILD_REMAINING`
- `ESCALATE`
- `TERMINATE`

Successful subtasks are preserved across normal replanning. `TERMINATE` cancels remaining non-terminal subtasks. `ESCALATE` stops local autonomous continuation and exposes an explicit escalation state.

## Critical boundaries

Stage 5.1 preserves:

- Global Mission Orchestrator as global mission authority;
- Stage-4 lifecycle and event history as authoritative local foundations;
- Stage-4 capability/governance/lineage contracts;
- Stage 6 as the only controlled execution plane.

No Stage-5.1 code invokes tools, opens target network connections, or actuates a target.

## Acceptance

Start the current Pentest runtime on port 8790 and run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE5_1_ACCEPTANCE.ps1
```

Expected inventory: **1823 tests**.
