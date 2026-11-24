# Stage 3.7.3 Patch Notes — Replan Eligibility & Governance Gate

## Change summary

Stage 3.7.3 adds a durable fail-closed eligibility/governance layer above the immutable Stage-3.7.1 adaptation detection and Stage-3.7.2 trigger classification contracts.

### Added

- `mission_orchestrator/replan_eligibility.py`
  - strict Stage-3.7.3 request normalization;
  - deterministic request fingerprint and `rpelig-op-*` operation identity;
  - static eligibility verification across Mission state/version, active Plan, Stage-3.7.1/3.7.2 lineage, Mission scope, and Governance binding;
  - immutable `rpelig-*` eligibility/governance contract construction and verification;
  - deterministic mapping of authoritative Governance PolicyDecision to `ELIGIBLE`, `NOT_ELIGIBLE`, or `REVIEW_REQUIRED`;
  - explicit no-REPLAN/no-planner/no-supersession/no-actuation authority boundary.
- migration `047_stage3_7_3_replan_eligibility_governance_gate.sql`;
- durable store `mission_replan_eligibility_governance_gates`;
- canonical Mission event `MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_EVALUATED`;
- Stage-3.7.3 POST/GET/list/definition API surfaces;
- authoritative Governance `AUTHORIZE_REPLAN` query with current external-scope revalidation;
- response-loss Governance PolicyDecision recovery by deterministic operation ID;
- Stage-3.7.3 repository reconstruction/integrity checks;
- 19 focused Stage-3.7.3 regression tests;
- authoritative Stage-3.7.3 acceptance script.

### Changed

- runtime `control_version` -> `stage3.7.3-replan-eligibility-governance-gate`;
- HTTP server version -> `APTSMissionOrchestrator/3.7.3`;
- repository migration level -> `47`;
- persistence manifest and repository record counts now include the Stage-3.7.3 eligibility/governance store;
- historical current-head regression assertions were rebased to Stage 3.7.3 / migration 47 while preserving stage-local historical semantics;
- Stage-3.7.1/3.7.2 read projections can expose an effective `ELIGIBLE` state only when the independent Stage-3.7.3 gate is eligible; source predecessor contracts remain immutable.

## Deliberately not added

Stage 3.7.3 does not add lifecycle `REPLAN`, ReplanSnapshot binding, planner invocation, ReplanCandidate creation, Plan-delta computation, successor-Plan validation/commit, Plan supersession, execution dispatch, target-action dispatch, external target I/O, or target actuation.
