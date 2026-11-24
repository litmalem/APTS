# Stage 5.5 — Attack-Path Planning Agent

Stage 5.5 activates the fourth Stage-5 specialist under the Stage-5.1 local multi-agent orchestrator.

Active control:

`stage5.5-attack-path-planning-agent`

Predecessor: `stage5.4-vulnerability-hypothesis-agent`  
Pentest repository migration: **12**  
Next: **5.6 — Exploitation Agent**

## Roadmap transform

The Attack-Path Planning Agent implements the Stage-5.5 planning transform:

```text
Initial Access
      ↓
Privilege Opportunity
      ↓
Credential / Trust Relationship
      ↓
Target Objective
```

The Stage-5.5 deliverables are:

- canonical **Attack-Path Graph**;
- deterministic **Candidate Path Ranking**;
- integrity-bound **Path Provenance**.

The planner is deliberately **planning-only and non-executing**. It consumes authoritative Stage-5.4 vulnerability hypotheses and turns them into evidence-bound candidate routes for later validation. Candidate routes are hypotheses about what may need validation; they are not proof that a route is reachable, exploitable, or authorized for execution.

## Implemented behavior

For a Stage-5.1 orchestration whose `attack_path_analysis` subtask is eligible, Stage 5.5:

1. validates the immutable Stage-4.1 Pentest boundary against the task;
2. requires the exact authoritative Stage-5.4 Vulnerability Hypothesis run for the same orchestration;
3. binds the predecessor `vulnerability_hypothesis_run_id`, Stage-5.4 output SHA-256, and Stage-5.4 evidence-bundle SHA-256;
4. rejects caller-supplied executable attack steps, commands, payloads, or tool parameters;
5. builds one candidate path per selected Stage-5.4 hypothesis;
6. materializes the four canonical planning stages as conditional graph nodes;
7. binds the `INITIAL_ACCESS` planning node to the unvalidated Stage-5.4 hypothesis and required-validation contract;
8. models later stages as conditional opportunities/checkpoints rather than executable instructions;
9. creates path provenance linking the hypothesis, vulnerability knowledge, Stage-4.9 evidence references, enumerated-asset integrity, and predecessor hashes;
10. ranks paths deterministically for **validation priority**, not exploit-success probability;
11. aggregates selected candidate paths into a SHA-bound directed conditional graph;
12. persists an integrity-bound Stage-5.5 evidence bundle;
13. supports exact idempotent replay and restart-safe durable state;
14. marks Stage-5.1 `attack_path_analysis` `SUCCEEDED` and releases the Stage-5.6 `validation` subtask to `READY`.

## Candidate path model

Each path is deterministic and SHA-256 integrity-bound. Its canonical stage sequence is:

```text
INITIAL_ACCESS
PRIVILEGE_OPPORTUNITY
CREDENTIAL_OR_TRUST_RELATIONSHIP
TARGET_OBJECTIVE
```

All transitions are conditional (`CONDITIONALLY_PRECEDES`). The model explicitly records:

```text
reachability_confirmed = false
validation_executed = false
finding_created = false
execution_request_created = false
execution_authorized = false
execution_deferred_to_stage6 = true
```

This prevents a planning hypothesis from being confused with an executed or validated attack chain.

## Candidate Path Ranking

The implemented deterministic ranking policy is:

`EVIDENCE_CONFIDENCE_THEN_LOWER_VALIDATION_IMPACT`

For each candidate path, the score is derived from Stage-5.4 hypothesis confidence and the estimated impact of the required validation. The score is explicitly labeled:

`VALIDATION_PRIORITY_HEURISTIC_NOT_EXPLOIT_SUCCESS_PROBABILITY`

The purpose is to order bounded validation work, not to estimate the probability of successful exploitation.

`planning_preferences.max_candidate_paths` limits the selected candidate set deterministically (default 25, maximum 100).

## Path provenance

Every candidate path contains an integrity-bound provenance record that ties the plan back to:

```text
mission_id / pentest_id / pentest_task_id / orchestration_id
Stage-5.4 vulnerability_hypothesis_run_id
Stage-5.4 output SHA-256
Stage-5.4 evidence-bundle SHA-256
hypothesis_id / hypothesis_ref / hypothesis integrity
knowledge_id / knowledge_ref / knowledge content SHA-256
supporting Stage-4.9 evidence refs
enumerated asset integrity
```

The result is reconstructable planning lineage without introducing a parallel evidence authority.

## Attack-Path Graph

The graph is a directed, conditional planning projection over the selected candidates. It contains candidate nodes and edges only; it does not assert confirmed reachability. The graph, ranking object, each candidate path, each path-provenance record, the output, and the Stage-5.5 evidence bundle are separately SHA-bound.

## Strict request surface

The canonical Stage-5.5 request contains only:

```text
schema_version
request_id
idempotency_key
actor
boundary
hypothesis_context {
  vulnerability_hypothesis_run_id
  output_sha256
  evidence_bundle_sha256
}
planning_preferences {
  max_candidate_paths
  ranking_policy
}
metadata
```

Unknown top-level fields are rejected. In particular, executable `command`, `attack_steps`, `payload`, and `tool_parameters` fields are not accepted by the planner.

## Durable state

Migration `012_stage5_5_attack_path_planning_agent.sql` adds:

- `pentest_attack_path_planning_runs`

The store binds the deterministic run identity, immutable request hash, Stage-5.1 orchestration identity, mission/pentest/task lineage, exact Stage-5.4 predecessor identity and hashes, output hash, evidence-bundle hash, and completion metadata.

Exact replay is idempotent. Restart at migration level 12 preserves Stage-5.4 and earlier repository state.

## APIs

```text
GET  /api/pentest/attack-path-planning-agent-contract
GET  /api/contracts/attack-path-planning-agent
GET  /api/contracts/attack-path-graph
GET  /api/contracts/candidate-path-ranking
GET  /api/contracts/path-provenance
GET  /api/contracts/attack-path-planning-evidence
GET  /api/pentest/attack-path-planning-runs
GET  /api/pentest/attack-path-planning-runs/{attack_path_planning_run_id}
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/attack-path-planning
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/attack-path-analysis
POST /api/pentest/agentic-orchestrations/{orchestration_id}/attack-path-planning/run
POST /api/pentest/agentic-orchestrations/{orchestration_id}/attack-path-analysis/run
```

Historical Stage-5.4 and earlier routes remain available through handler inheritance.

`POST /api/execution/dispatches` remains fail-closed (`409`).

## Authority boundary

Stage 5.5 explicitly keeps the following disabled:

- caller-provided executable attack sequences;
- vulnerability validation execution;
- confirmed-finding creation;
- execution-request creation;
- raw tool or binary access;
- direct external target-network I/O;
- target actuation;
- `PolicyDecision` minting.

Stage 5.5 determines **candidate paths that may warrant controlled validation**. Stage 6 remains the authority for controlled execution.

## Acceptance

Start the Global Mission Orchestrator and current Pentest runtime, then run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE5_5_ACCEPTANCE.ps1
```

Expected canonical inventory: **1929 tests**.
