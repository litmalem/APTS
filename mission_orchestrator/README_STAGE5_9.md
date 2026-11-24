# Stage 5.9 — Governance-Bound Multi-Agent Pentest E2E

Stage 5.9 implements the Stage-5 end-to-end assurance path defined by the APTS master roadmap:

```text
PIP
→ Pentest Orchestrator
→ Recon
→ Enumeration
→ Hypothesis
→ Attack Path
→ Proposed Validation
→ Governance
→ Result
→ Feedback
→ Replanning
```

The implementation **does not execute penetration-test actions**. It reconstructs and verifies the authoritative Stage-5 artifact chain, reuses Stage-5.8 shared-state/feedback/replanning contracts, performs fail-closed control-plane scenario probes, and persists SHA-bound `Pentest E2E evidence`. Stage 6 remains the controlled-execution and target-evidence authority.

## Implemented scenarios

- `SUCCESS`
- `DENIED_ACTION`
- `STALE_INTELLIGENCE`
- `TARGET_OUTSIDE_SCOPE`
- `AGENT_FAILURE`
- `CONFLICTING_EVIDENCE`
- `PARTIAL_RESULTS`

Negative-scenario injection is strictly a **control-plane E2E test mechanism**. It cannot carry arbitrary commands, payloads, or targets and never actuates a target.

## Main additions

- `pentest_subsystem/governance_bound_e2e.py`
  - canonical Stage-5.9 contract;
  - deterministic E2E run identity;
  - strict scenario request schema;
  - complete roadmap trajectory projection;
  - fail-closed governance probes for denied/out-of-scope paths;
  - Stage-5.8 feedback + local replanning reuse;
  - SHA-bound persisted E2E evidence;
  - restart/idempotency/tamper checks.
- `pentest_migrations/016_stage5_9_governance_bound_multi_agent_pentest_e2e.sql`
- Stage-5.9 HTTP routes and active runtime handler.
- 21 focused Stage-5.9 tests.
- `STAGE5_9_ACCEPTANCE.ps1`.

## Runtime/API

Active server signature:

```text
APTSPentestSubsystem/5.9
```

Contract:

```text
GET /api/pentest/governance-bound-e2e-contract
```

Run a scenario for an existing orchestration:

```text
POST /api/pentest/agentic-orchestrations/{orchestration_id}/e2e-run
```

List runs:

```text
GET /api/pentest/agentic-orchestrations/{orchestration_id}/e2e-runs
```

Retrieve one run:

```text
GET /api/pentest/e2e-runs/{e2e_run_id}
```

Stage-5.8 shared-state, feedback, handoff, and local-replan routes remain available under the Stage-5.9 handler.

## Authority boundary

Stage 5.9 explicitly preserves these constraints:

- no direct tool access;
- no external target I/O;
- no target actuation;
- no `ExecutionRequest` creation;
- no action-result creation;
- no new target-evidence fabrication;
- no confirmed-finding creation;
- no authorization minting;
- Stage-4.8 governance semantics remain fail-closed;
- Stage-5.8 replanning remains projection-only;
- Stage 6 remains the only controlled execution/evidence plane.

## Acceptance

With the Mission Orchestrator on `127.0.0.1:8780` and Pentest Subsystem on `127.0.0.1:8790`:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE5_9_ACCEPTANCE.ps1
```

Expected canonical inventory after this patch: **2030 tests**.
