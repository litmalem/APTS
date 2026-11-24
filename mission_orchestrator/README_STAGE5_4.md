# Stage 5.4 — Vulnerability Hypothesis Agent

Stage 5.4 activates the third Stage-5 specialist implementation under the Stage-5.1 local multi-agent orchestrator.

Active control:

`stage5.4-vulnerability-hypothesis-agent`

Predecessor: `stage5.3-enumeration-agent`  
Pentest repository migration: **11**  
Next: **5.5 — Attack-Path Planning Agent**

## Roadmap transform

The Vulnerability Hypothesis Agent implements the Stage-5.4 roadmap transform:

```text
Observation
     ↓
Knowledge / CTI
     ↓
Hypothesis
     ↓
Confidence
     ↓
Required Validation
```

The Stage-5.4 deliverables are a canonical **Hypothesis Model** and an **Evidence-to-Hypothesis lineage**.

Stage 5.4 is deliberately **read-only and non-executing**. It correlates authoritative Stage-5.3 enumeration evidence with explicitly provenance-bound vulnerability knowledge/CTI. It does not validate a hypothesis on the target, does not create a confirmed finding from an unvalidated hypothesis, and does not perform target-side effects. Controlled execution remains Stage-6 authority.

## Implemented behavior

The agent requires an existing Stage-5.3 Enumeration run for the same orchestration. The caller cannot re-introduce or replace observations: Stage 5.4 consumes the authoritative Stage-5.3 `enumerated_assets` and binds the exact predecessor `enumeration_run_id`, Enumeration output SHA-256, and Enumeration Evidence Bundle SHA-256. It then:

1. validates the Stage-4.1 boundary against the immutable Pentest task;
2. validates the exact Stage-5.3 predecessor run and hashes;
3. validates explicit knowledge/CTI source provenance plus `content_sha256`;
4. deterministically correlates knowledge selectors with authoritative enumerated assets;
5. creates zero hypotheses when no selector match is supported by evidence;
6. creates integrity-bound `OPEN / UNVALIDATED` Hypothesis Models for supported correlations;
7. derives hypothesis confidence conservatively from knowledge confidence and matched evidence confidence;
8. models the required validation technique, expected evidence, and impact without executing it;
9. writes a Stage-4.9 `HYPOTHESIS` lineage object whose parent is authoritative Stage-4.9 `EVIDENCE`;
10. preserves all supporting evidence references inside the hypothesis lineage;
11. never materializes a Stage-4.9 `FINDING` from an unvalidated hypothesis;
12. persists a SHA-bound Vulnerability Hypothesis Evidence Bundle;
13. supports exact idempotent replay and restart-safe durable state;
14. marks the Stage-5.1 `vulnerability_analysis` subtask `SUCCEEDED` and releases `attack_path_analysis` to `READY`.

## Knowledge / CTI contract

Each knowledge item is explicit, provenance-bound, and content-hash-bound. Supported knowledge families are:

```text
CVE
ADVISORY
CTI_PATTERN
CONFIGURATION_PATTERN
WEAKNESS_PATTERN
INTERNAL_KNOWLEDGE
```

A canonical item includes:

```text
knowledge_id
knowledge_type
source { source_kind, source_id, source_ref }
content_sha256
title
summary
vulnerability_id (optional)
published_at (optional)
match selectors
confidence
required_validation
```

Match selectors may constrain product, version, technology, service, endpoint, target, or configuration observations. Every selector family supplied by the knowledge item must be satisfied by the authoritative Stage-5.3 asset/evidence projection before the item can support a hypothesis.

## Hypothesis Model

Each model is deterministic and SHA-256 integrity-bound. It records:

```text
hypothesis identity
mission / pentest / task / orchestration identity
target
statement
status = OPEN
validation_state = UNVALIDATED
knowledge provenance + knowledge content hash
matched correlation dimensions
supporting Stage-4.9 evidence refs
confidence
required validation contract
semantics
integrity
```

Critical semantics are explicit:

```text
confirmed_finding = false
validation_required = true
validation_executed = false
execution_deferred_to_stage6 = true
```

A hypothesis is therefore a testable vulnerability proposition, not a confirmed vulnerability finding.

## Confidence semantics

For a supported knowledge-to-asset correlation, Stage 5.4 uses a conservative confidence rule:

```text
hypothesis confidence = min(
    knowledge confidence,
    mean(confidence of matched authoritative evidence)
)
```

The confidence is not an exploit-success probability and does not authorize execution.

## Required Validation

Stage 5.4 records what validation would be required next, including:

```text
technique
summary
expected_evidence
estimated_impact
capability_id = validation
safety_class = CONTROLLED_VALIDATION_REQUIRED
execution_deferred_to_stage6 = true
```

No validation technique is executed by Stage 5.4.

## Evidence-to-Hypothesis lineage

The implementation reuses Stage-4.9 lineage semantics rather than creating a parallel evidence system. Each generated hypothesis receives a deterministic Stage-4.9 `HYPOTHESIS` record:

```text
parent_type = EVIDENCE
status = OPEN
supporting_evidence_refs = [...]
contradicting_evidence_refs = []
target_ref = ...
```

The lineage binds the hypothesis to both authoritative observed evidence and the source/hash of the vulnerability knowledge that caused the correlation.

## Vulnerability Hypothesis output contract

The capability-required output families are present:

```text
vulnerability_hypotheses
evidence_refs
confidence
```

The Stage-5.4 output also exposes:

```text
predecessor_enumeration
knowledge_refs
evidence_to_hypothesis_lineage
required_validations
semantics
integrity
```

## Durable state

Migration `011_stage5_4_vulnerability_hypothesis_agent.sql` adds:

- `pentest_vulnerability_hypothesis_runs`

The store binds:

- deterministic `vulnerability_hypothesis_run_id`;
- immutable request hash;
- Stage-5.1 orchestration/subtask identity;
- mission/pentest/task lineage;
- exact Stage-5.3 Enumeration predecessor identity and hashes;
- canonical Hypothesis output hash;
- canonical Vulnerability Hypothesis Evidence Bundle hash;
- evidence-to-hypothesis lineage metadata;
- completion timestamps.

Exact replay is idempotent. Restart at migration level 11 preserves predecessor state and does not downgrade repository metadata.

## APIs

```text
GET  /api/pentest/vulnerability-hypothesis-agent-contract
GET  /api/contracts/vulnerability-hypothesis-agent
GET  /api/contracts/vulnerability-hypothesis
GET  /api/contracts/vulnerability-hypothesis-evidence
GET  /api/pentest/vulnerability-hypothesis-runs
GET  /api/pentest/vulnerability-hypothesis-runs/{vulnerability_hypothesis_run_id}
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/vulnerability-hypothesis
GET  /api/pentest/agentic-orchestrations/{orchestration_id}/vulnerability-analysis
POST /api/pentest/agentic-orchestrations/{orchestration_id}/vulnerability-hypothesis/run
POST /api/pentest/agentic-orchestrations/{orchestration_id}/vulnerability-analysis/run
```

Historical Stage-5.3 Enumeration and earlier routes remain available through handler inheritance.

`POST /api/execution/dispatches` remains fail-closed (`409`).

## Authority boundary

Stage 5.4 explicitly keeps the following disabled:

- raw tool or binary access by the specialist;
- direct external target-network I/O;
- target actuation;
- execution intake;
- active vulnerability validation;
- conversion of unvalidated hypotheses into confirmed findings;
- creation of `PolicyDecision` authorization.

Stage 5.4 determines **what vulnerability may plausibly exist and what evidence would be required to validate it**. It does not perform that validation.

## Acceptance

Start the current Pentest runtime on port 8790 and run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE5_4_ACCEPTANCE.ps1
```

Expected inventory: **1901 tests**.
