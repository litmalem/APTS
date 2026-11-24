# Stage 5.8 — Cross-Agent Feedback, Shared State & Replanning

Stage 5.8 closes the local Stage-5 specialist loop by projecting authoritative specialist artifacts into a versioned shared state, recording explicit handoffs and evidence-bound feedback, and producing deterministic local replan decisions.

## Implemented flow

```text
Recon → Enumeration → Hypothesis → Attack Path → Validation/Exploitation → Impact
   \__________________________________________________________________________/
                                  ↓
                     authoritative repository projection
                                  ↓
                   versioned SHA-bound shared state
                                  ↓
                  agent handoff + cross-agent feedback
                                  ↓
                     deterministic replan decision
                                  ↓
           NO_CHANGE | REPLAN_LOCAL | DEFER_TO_STAGE6 |
                     ESCALATE_GOVERNANCE
```

The shared-state contract contains the roadmap domains:

- validated facts;
- mission context;
- pentest state;
- findings;
- evidence;
- task ownership.

Stage 5.8 keeps validated observations separate from hypotheses, attack paths, exploit proposals, and provisional post-validation findings. Caller input cannot directly inject shared facts, findings, or evidence into the shared-state snapshot.

## Deliverables

- `pentest_subsystem/cross_agent_feedback.py`
  - canonical Stage-5.8 contract and definition;
  - strict shared-state refresh, feedback, and local-replan request contracts;
  - versioned SHA-bound shared state derived from authoritative repository artifacts;
  - partial-pipeline snapshots and deterministic source fingerprints;
  - evidence index and task ownership projection;
  - SHA-bound agent-handoff records;
  - cross-agent feedback ownership/evidence/state-version checks;
  - deterministic `EARLIEST_AFFECTED_CAPABILITY` local replanning;
  - governance escalation and Stage-6 defer semantics;
  - restart-safe/idempotent repository persistence.
- migration `015_stage5_8_cross_agent_feedback_shared_state_replanning.sql`.
- active API handler `APTSPentestSubsystem/5.8`.
- Stage-5.8 regression tests and deployment-host acceptance gate.

## Replanning semantics

The Stage-5.8 local replan is deliberately a **projection**, not an immediate mutation of the active Stage-5.1 orchestration record.

Rules:

- `STALE_INTELLIGENCE` → restart projection from `reconnaissance`;
- `CONFLICTING_EVIDENCE`, `PARTIAL_RESULT`, `SPECIALIST_FAILURE` → reopen the earliest affected capability and downstream work;
- `INSUFFICIENT_EVIDENCE` for validation/exploitation/impact → `DEFER_TO_STAGE6`;
- `SCOPE_OR_ROE_CHANGE` → `ESCALATE_GOVERNANCE`;
- `NO_REPLAN_REQUIRED` → `NO_CHANGE`.

Unaffected succeeded work is preserved. Specialist replay is not automatically started and the active Stage-5.1 plan is not mutated by Stage 5.8.

## Execution boundary

Stage 5.8 does **not**:

- invoke pentest tools or binaries;
- open external target-network connections;
- actuate a target;
- create Stage-6 `ExecutionRequest` or `ActionResult` records;
- fabricate new target-derived evidence;
- create confirmed findings;
- mint `PolicyDecision` authorization;
- grant specialist agents raw target access.

Stage 6 remains the controlled execution and target-evidence authority.

## HTTP surface

Contract routes:

```text
GET /api/pentest/cross-agent-feedback-contract
GET /api/contracts/cross-agent-feedback
GET /api/contracts/shared-state
GET /api/contracts/agent-handoff
GET /api/contracts/local-replanning
```

Shared state / handoff / feedback / replanning routes:

```text
POST /api/pentest/agentic-orchestrations/{orchestration_id}/shared-state/refresh
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/shared-state
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/shared-states
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/handoffs
POST /api/pentest/agentic-orchestrations/{orchestration_id}/feedback
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/feedback
POST /api/pentest/agentic-orchestrations/{orchestration_id}/local-replan
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/local-replans
```

Historical Stage-5.7 and earlier routes remain available by handler inheritance. `POST /api/execution/dispatches` remains fail-closed with HTTP `409`.

## Acceptance

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE5_8_ACCEPTANCE.ps1
```

Canonical inventory after this patch: **2009 tests**.
