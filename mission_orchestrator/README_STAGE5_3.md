# Stage 5.3 — Enumeration Agent

Stage 5.3 activates the second Stage-5 specialist implementation under the Stage-5.1 local multi-agent orchestrator.

Active control:

`stage5.3-enumeration-agent`

Predecessor: `stage5.2-reconnaissance-agent`  
Pentest repository migration: **10**  
Next: **5.4 — Vulnerability Hypothesis Agent**

## Roadmap functions

The Enumeration Agent implements the Stage-5.3 roadmap functions:

```text
service enumeration
technology identification
version discovery
endpoint discovery
configuration observation
```

Stage 5.3 is deliberately **non-executing**. It consumes imported, authorized enumeration observations and may publish governed enumeration action proposals, but it never invokes scanners/binaries, opens target network connections, or actuates targets directly. Controlled target execution remains Stage-6 authority.

## Implemented behavior

The agent requires an existing Stage-5.2 Reconnaissance run for the same orchestration. It binds the exact predecessor `recon_run_id`, Recon output SHA-256, and Recon Evidence Bundle SHA-256 before accepting enumeration work. It then:

1. validates the Stage-4.1 boundary against the immutable Pentest task;
2. validates the exact Stage-5.2 predecessor run and hashes;
3. normalizes `SERVICE`, `TECHNOLOGY`, `VERSION`, `ENDPOINT`, and `CONFIGURATION` observations;
4. writes every imported observation as a Stage-4.9 `OBSERVATION` + `EVIDENCE` lineage pair;
5. excludes out-of-local-task-scope observations from the canonical asset model while preserving them as observed-only evidence;
6. deterministically aggregates in-scope observations into integrity-bound Enumerated Asset Models;
7. evaluates proposed active enumeration actions through Stage-4.8 scope/RoE enforcement plus a narrower local-task target-scope precheck;
8. publishes eligible/reviewable `ACTION_PROPOSAL` lineage records without execution;
9. persists a SHA-bound Enumeration Evidence Bundle;
10. marks the Stage-5.1 Enumeration subtask `SUCCEEDED` and releases `vulnerability_analysis` to `READY`.

## Enumerated Asset Model

Each asset model is SHA-256 integrity-bound and contains:

```text
asset identity
mission / pentest / task identity
target
services
technologies
versions
endpoints
configuration observations
evidence refs
confidence
integrity
```

Only observations within the immutable local Pentest-task scope may contribute to the asset model.

## Enumeration output contract

The capability-required output families are present:

```text
enumerated_assets
service_observations
evidence_refs
confidence
```

The Stage-5.3 output also exposes:

```text
technology_identifications
version_discoveries
endpoint_discoveries
configuration_observations
raw_evidence
governance
action_proposals
predecessor_reconnaissance
```

## Durable state

Migration `010_stage5_3_enumeration_agent.sql` adds:

- `pentest_enumeration_runs`

The store binds:

- deterministic `enumeration_run_id`;
- immutable request hash;
- Stage-5.1 orchestration/subtask identity;
- mission/pentest/task lineage;
- exact Stage-5.2 Recon predecessor identity and hashes;
- canonical Enumeration output hash;
- canonical Enumeration Evidence Bundle hash;
- completion timestamps.

Exact replay is idempotent. Restart at migration level 10 preserves Stage-5.2 data and does not downgrade predecessor metadata.

## APIs

```text
GET  /api/pentest/enumeration-agent-contract
GET  /api/contracts/enumeration-agent
GET  /api/contracts/enumerated-asset
GET  /api/contracts/enumeration-evidence
GET  /api/pentest/enumeration-runs
GET  /api/pentest/enumeration-runs/{enumeration_run_id}
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/enumeration
POST /api/pentest/agentic-orchestrations/{orchestration_id}/enumeration/run
```

Historical Stage-5.2 Reconnaissance routes remain available through handler inheritance.

`POST /api/execution/dispatches` remains fail-closed (`409`).

## Authority boundary

Stage 5.3 explicitly keeps the following disabled:

- raw tool or binary access by the specialist;
- direct external target-network I/O;
- target actuation;
- creation of `PolicyDecision` authorization;
- direct Stage-6 intake by the Stage-5.3 specialist (requests are submitted by a separate controlled Stage-6 service).

Stage-4.8 scope/RoE decisions remain **eligibility decisions, not authorization artifacts**. Stage 13 adds a narrowly bounded Stage-6 handoff for an explicitly persisted `TCP_BANNER_READ` proposal. Stage 5.3 still performs no target I/O and does not create an ExecutionRequest, authorization, or execution result.

Stage 13 only allows Stage 6 to intake an exact persisted `TCP_BANNER_READ` proposal after revalidating its Stage-5.3 run/evidence, Stage-4.8 decision, current task/orchestration/scope/RoE, explicit one-request budget, and the fixed Stage-6.4 adapter tuple. Semantic proposal techniques such as `SERVICE_ENUMERATION` remain non-executable until an exact registered adapter exists. Stage 6.2/GSS is the authorization authority; Stage 6.3 admission, Stage 6.4 adapter selection, Stage 6.5 runtime, and Stage 6.6 evidence remain mandatory.

The Stage-6.6 result is returned through a read-only exact-proposal lookup. Enumeration iteration verifies terminal success, sealed evidence, and mission/task/orchestration binding, then produces a separate integrity-bound iteration projection without updating the parent Stage-5.3 run.

## Acceptance

Start the current Pentest runtime on port 8790 and run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE5_3_ACCEPTANCE.ps1
```

Expected inventory: **1873 tests**.
