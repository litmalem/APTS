# Stage 5.7 — Post-Exploitation & Impact Agent

Stage 5.7 activates the bounded `PENTEST_POST_EXPLOITATION_IMPACT_AGENT` as the impact-analysis specialist after Stage 5.6 exploitation proposal preparation.

The implementation follows the Stage-5/Stage-6 architectural boundary: Stage 5.7 determines **what post-validation impact is plausible, what evidence is still missing, and when the workflow must stop or escalate**. It does not perform post-exploitation actions. Stage 6 remains responsible for controlled execution and target-derived evidence.

## Implemented flow

```text
Stage 5.6 ExploitActionProposal + ValidationTask
        ↓ exact run/output/evidence hash binding
Stage 5.5 attack-path provenance revalidation
        ↓
ImpactAnalysis
  ├─ reached privilege: NOT OBSERVED at Stage 5
  ├─ accessible resources: NOT OBSERVED at Stage 5
  ├─ potential lateral movement: projection only
  ├─ security impact: potential only
  ├─ business impact: operator-declared context only
  ├─ evidence sufficiency: explicit Stage-6 gaps
  └─ stop conditions: fail-closed / review / defer
        ↓
provisional PostValidationFinding
        ↓
Stage 5.1 impact_analysis handoff
        ↓
Stage-5 specialist pipeline complete
        ↓
Stage 5.8 shared-state / feedback / replanning

Actual target execution and confirmation: deferred to Stage 6
```

## Deliverables

- canonical Stage-5.7 contract and SHA-bound definition;
- `ImpactAnalysis` contract covering every roadmap focus item;
- provisional `PostValidationFinding` contract;
- deterministic `imprun-*` identity;
- exact Stage-5.6 run/output/evidence binding;
- Stage-5.5 attack-path provenance preservation and verification;
- evidence-sufficiency model that distinguishes Stage-5 projection from Stage-6 observation;
- explicit stop/escalation/defer conditions;
- optional, strictly typed operator business context (`business_criticality`, `data_sensitivity`, `availability_criticality`);
- Stage-5.1 `impact_analysis` handoff and specialist-pipeline completion;
- durable migration 14 store `pentest_post_exploitation_impact_runs`;
- idempotent replay, restart recovery, and integrity verification;
- Stage-5.7 HTTP API and active runtime `APTSPentestSubsystem/5.7`;
- 28 focused tests and deployment-host acceptance script.

## Confirmation semantics

Stage 5.7 deliberately treats impact findings as **provisional**. It does not infer a successful compromise merely because Stage 5.6 produced an eligible validation proposal.

Without Stage-6 execution evidence, Stage 5.7 records:

- reached privilege as not observed;
- accessible resources as not observed;
- lateral movement as potential only and never executed;
- security impact as potential/unconfirmed;
- business impact only as a contextual projection based on operator-declared criticality;
- evidence sufficiency as incomplete for confirmed impact.

This prevents a proposal-plane artifact from being promoted into a false proof-of-compromise claim.

## Explicit execution boundary

Stage 5.7 deliberately does **not**:

- accept caller-supplied post-exploitation results, credentials, commands, payloads, exploit code, shellcode, or tool parameters;
- enumerate target resources by contacting a target;
- extract credentials or secrets;
- execute lateral movement;
- invoke raw tools or binaries;
- open target-network connections;
- actuate a target;
- create a Stage-6 `ExecutionRequest` or `ActionResult`;
- create new target execution evidence;
- materialize a confirmed Stage-4.9 `FINDING`;
- claim proof of compromise;
- mint `PolicyDecision` authorization.

Stage 6 remains the controlled execution and execution-evidence authority.

## HTTP surface

Contract routes:

```text
GET /api/pentest/post-exploitation-impact-agent-contract
GET /api/contracts/post-exploitation-impact-agent
GET /api/contracts/impact-analysis
GET /api/contracts/post-validation-finding
GET /api/contracts/post-exploitation-impact-evidence
```

Run/query routes:

```text
POST /api/pentest/agentic-orchestrations/{orchestration_id}/post-exploitation-impact/run
POST /api/pentest/agentic-orchestrations/{orchestration_id}/impact-analysis/run
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/post-exploitation-impact
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/impact-analysis
GET  /api/pentest/post-exploitation-impact-runs/{run_id}
GET  /api/pentest/impact-analysis-runs/{run_id}
GET  /api/pentest/post-exploitation-impact-runs
GET  /api/pentest/impact-analysis-runs
```

Historical Stage-5.6 and earlier routes remain available through handler inheritance. `POST /api/execution/dispatches` remains fail-closed with HTTP `409`.

## Acceptance

Start the Global Mission Orchestrator and Pentest runtime, then execute:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE5_7_ACCEPTANCE.ps1
```

Expected canonical inventory: **1985 tests**.
