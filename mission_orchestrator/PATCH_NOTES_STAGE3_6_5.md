# PATCH NOTES — Stage 3.6.5 Mission Outcome Aggregation

## Added

- `mission_orchestrator/mission_outcome_aggregation.py`
  - normalized aggregation request and idempotency fingerprint;
  - deterministic active-plan task classification;
  - canonical Mission Outcome Aggregation contract/hash verification;
  - explicit authority-boundary contract and definition metadata.
- migration `040_stage3_6_5_mission_outcome_aggregation.sql`.
- durable repository store `mission_outcome_aggregations`.
- API create/list/get/definition routes.
- canonical event type `MISSION_OUTCOME_AGGREGATED`.
- Stage-3.6.5 repository-integrity verification including row-vs-contract projection checks.
- focused 20-test Stage-3.6.5 proof suite.

## Updated

- runtime control version -> `stage3.6.5-mission-outcome-aggregation`.
- HTTP server version -> `APTSMissionOrchestrator/3.6.5`.
- repository migration level -> `40`.
- repository persistence manifest/count projection includes `mission_outcome_aggregations`.
- historical regression expectations updated to the current control/server/repository migration level while preserving stage-specific migration metadata.

## Deliberately unchanged

Stage 3.6.5 does not perform success-criteria evaluation, Mission completion/readiness decisions, dependency release, readiness recalculation, Plan progression, Governance/runtime I/O, dispatch/redelivery, target actuation, or Mission state transitions.
