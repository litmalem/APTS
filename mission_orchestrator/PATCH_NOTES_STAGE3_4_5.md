# Patch Notes — Stage 3.4.5 Governance-Bound Delegation Authorization

## Added

- Immutable `delegation_authorization` contract and verifier.
- External Governance-bound authorization flow for an exact Stage-3.4.4 route decision.
- Deterministic Governance operation correlation for lost-response recovery.
- Durable `AUTHORIZED`, `DENIED`, and `REVIEW_REQUIRED` evidence.
- `mission_delegation_authorizations` repository store.
- Migration `022_stage3_4_5_governance_bound_delegation_authorization.sql`.
- Event `MISSION_TASK_DELEGATION_AUTHORIZATION_RECORDED`.
- POST/GET Stage-3.4.5 APIs and definition endpoint.
- Repository-integrity verification for source route, selected subsystem/capability, Governance decision, and event lineage.
- 30 focused Stage-3.4.5 tests.

## Changed

- Runtime control version: `stage3.4.5-governance-bound-delegation-authorization`.
- Mission Orchestrator server version: `APTSMissionOrchestrator/3.4.5`.
- Repository migration level: `22`.
- Persistence manifest includes `mission_delegation_authorizations`.
- Historical regression expectations rebased only where they describe the current repository/runtime inventory.

## Preserved boundaries

Stage 3.4.5 does not perform delegation, dispatch, endpoint resolution, health probing, resource assignment, target-action authorization, target actuation, or Mission-version-vector extension. `aptsGSS / GOV-PLANE` remains authoritative for authorization.
