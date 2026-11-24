# Stage 4.9 — Evidence, Finding & Lineage Foundation

Stage 4.9 implements the canonical, append-only **evidence / finding / pentest lineage foundation** for the Pentest Subsystem. It follows Stage 4.8 scope/RoE eligibility enforcement and remains strictly non-executing.

## Active control

`stage4.9-evidence-finding-lineage-foundation`

Predecessor: `stage4.8-governance-scope-roe-enforcement`  
Pentest repository migration: `7`  
Next stage: `4.10 — Pentest Foundation Acceptance Gate`

## Canonical object model

The Stage-4.9 lineage model supports the seven roadmap objects:

- `OBSERVATION`
- `EVIDENCE`
- `FINDING`
- `HYPOTHESIS`
- `ACTION_PROPOSAL`
- `ACTION_RESULT`
- `ARTIFACT`

Every persisted object carries:

- canonical identity (`record_id`, type, mission, pentest, task, object version)
- provenance
- timezone-aware timestamp
- exact parent reference with parent SHA-256
- canonical SHA-256 integrity metadata

The local Pentest task is the lineage root. The root projection also carries the upstream mission/task/PIP binding hashes so local lineage remains reconstructible back to the cross-subsystem task/PIP anchor.

## Evidence model

Evidence is intentionally distinct from observations and findings. Evidence can reference canonical artifacts and content hashes, but Stage 4.9 does not store raw artifact bytes inline. Artifact records use URI + SHA-256 metadata.

## Finding model

A finding carries status, severity, target reference, impact assessment, confidence, and at least one canonical supporting `EVIDENCE` reference. Optional hypothesis and contradicting-evidence references must resolve within the same Pentest task lineage.

## Lineage semantics

Parent relationships are type-constrained and fail closed. Parent objects must already exist, must belong to the same mission / pentest / task identity, and must match their canonical hash. This prevents forward references, cross-task splicing, and silent parent substitution.

The durable lineage projection is reconstructed from the append-only repository and exposes:

- task/PIP root anchor
- monotonic local sequence
- record IDs/types/hashes
- parent edges
- per-type counts
- current lineage heads
- projection integrity hash

## Runtime / API

- `GET /api/pentest/lineage-contract`
- `POST /api/pentest/lineage/records`
- `GET /api/pentest/lineage/records/{record_id}`
- `GET /api/pentest/evidence/{record_id}`
- `GET /api/pentest/findings/{record_id}`
- `GET /api/pentest/tasks/{pentest_task_id}/lineage`
- `GET /api/pentest/tasks/{pentest_task_id}/evidence`
- `GET /api/pentest/tasks/{pentest_task_id}/findings`

Historical Stage-4.1 through Stage-4.8 routes remain available through the inherited handler/service chain.

## Persistence

Migration `007_stage4_9_evidence_finding_lineage_foundation.sql` adds `pentest_lineage_objects` with:

- immutable record/idempotency identity
- mission/pentest/task lineage
- monotonic task-local sequence
- exact parent type/ID/hash
- canonical object hash + JSON
- append-only update/delete triggers

Exact replay is idempotent. Reuse of a record ID or idempotency key with different immutable content is rejected.

## Authority boundary

Stage 4.9 does **not**:

- mint `PolicyDecision`
- perform controlled execution
- invoke pentest tools
- perform external network I/O
- actuate targets

`ACTION_PROPOSAL` and `ACTION_RESULT` are canonical lineage records only. Controlled target execution remains Stage 6 authority.

## Validation performed in the implementation environment

- Python compilation: PASS
- Focused Stage 4.9: **36 passed**
- Stage 4.1 → 4.9 regression: **209 passed**
- Critical Stage 3 + Stage 4 regression: **115 passed**
- Canonical inventory: **1784 tests collected**

The full historical suite is intentionally delegated to `STAGE4_9_ACCEPTANCE.ps1` on the deployment host and remains the final PASS/FAIL authority.
