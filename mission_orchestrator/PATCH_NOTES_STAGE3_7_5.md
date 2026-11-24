# Stage 3.7.5 Patch Notes — Deterministic Replan Candidate Generation

## Change summary

Stage 3.7.5 adds the candidate-generation layer immediately after Stage 3.7.4. An immutable ReplanSnapshot can now be transformed into exactly one durable deterministic ReplanCandidate without refreshing external context, re-querying Governance, mutating the source Plan, creating/activating a successor Plan, validating/committing a replan, superseding a Plan, dispatching work, or actuating an external target.

### Added

- `mission_orchestrator/replan_candidate.py`
  - strict candidate-generation request normalization;
  - caller-supplied candidate/task/dependency/commit material rejection;
  - deterministic request fingerprinting;
  - canonical `rpcand-*` and `rpinv-*` identity generation;
  - Stage-3.7.4 ReplanSnapshot integrity binding;
  - deterministic unfinished-task / remainder-DAG projection;
  - completed-predecessor satisfaction projection;
  - canonical planner-invocation hashing;
  - canonical candidate-payload hashing;
  - immutable ReplanCandidate construction/verification;
  - explicit candidate-only authority boundary;
  - Stage-3.7.6 reservation as the next control.

- `migrations/049_stage3_7_5_deterministic_replan_candidate_generation.sql`
  - durable `mission_replan_candidates` store;
  - unique candidate/invocation/snapshot/episode identities;
  - unique Mission-scoped idempotency key;
  - source snapshot/adaptation/Plan foreign-key bindings;
  - canonical JSON and lookup indexes.

- `tests/test_stage3_7_5_deterministic_replan_candidate_generation.py`
  - 21 focused proofs covering contract, deterministic generation, ordering, source bindings, concurrency, no-Governance-refresh, authority exclusions, idempotency/cardinality, persistence/integrity, and HTTP boundaries.

### Runtime integration

- `mission_orchestrator/service.py`
  - activates `stage3.7.5-deterministic-replan-candidate-generation`;
  - exposes Stage-3.7.5 health metadata;
  - creates/retrieves/lists deterministic ReplanCandidates;
  - verifies Stage-3.7.4 snapshot and current source Plan/Mission head before generation;
  - records `MISSION_REPLAN_CANDIDATE_GENERATED` exactly once;
  - integrates candidate integrity into Mission repository reconstruction.

- `mission_orchestrator/repository.py`
  - SQLite/MySQL candidate table creation;
  - candidate persistence and retrieval helpers;
  - idempotency/snapshot lookup;
  - conflict translation.

- `mission_orchestrator/repository_model.py`
  - repository migration head raised from 48 to **49**;
  - candidate persistence store added to repository manifest/reconstruction.

- `mission_orchestrator/api_service.py`
  - server version raised to `APTSMissionOrchestrator/3.7.5`;
  - candidate GET/POST and definition routes added;
  - Stage-3.7.5 conflict/not-found/guard error mappings added.

- `mission_orchestrator/errors.py`
  - candidate conflict/not-found/guard exceptions added.

- `mission_orchestrator/mission_events.py`
  - canonical candidate-generation event type registered.

## Deterministic planning semantics

Stage 3.7.5 deliberately uses a deterministic local planner profile:

```text
CANONICAL_REPLAN_REMAINDER_DAG_V1
```

The immutable Stage-3.7.4 snapshot is the sole authoritative planning input. Source tasks are canonically ordered, tasks already represented by durable completion records are omitted from new executable candidate work, remaining dependencies are preserved, and completed-to-retained dependencies are represented as satisfied predecessors.

No LLM/free-form planner output is accepted from the caller and no external context refresh is performed.

## Current-head regression rebase

Historical tests whose assertions intentionally follow the **current repository head** were rebased from Stage 3.7.4 / migration 48 / server 3.7.4 to Stage 3.7.5 / migration 49 / server 3.7.5. Historical stage-local constants remain unchanged when they document the original stage rather than the current repository head.

A residual Stage-3.1.10 migration-count assertion was also rebased from 48 to 49 after the complete-suite proof exposed it. Its explicit migration-name list already contained migration 049; only the stale count was corrected.

## Authority exclusions retained

Stage 3.7.5 remains candidate-only. It does not grant authority for successor-Plan activation, Plan validation, replan commit, Plan supersession, Mission state transition, routing/delegation, dispatch/execution, Governance refresh, external-context refresh, or target actuation.

Build-sandbox validation completed with 1257/1257 canonical tests PASS in 954.19s (15m54s), 21/21 focused Stage-3.7.5 tests PASS, and 22/22 predecessor/current-head probes PASS. See `PATCH_FILE_LIST_STAGE3_7_5.txt` for the exact release payload and `REGRESSION_EVIDENCE_STAGE3_7_5.txt` for detailed evidence.
