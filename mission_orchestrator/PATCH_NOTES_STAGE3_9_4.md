# Patch Notes — Stage 3.9.4

## Added

- `mission_orchestrator/e2e_routing_delegation_governance_qualification.py`
  - canonical Stage 3.9.4 acceptance contract;
  - deterministic request builders for the existing Stage 3.3.5–3.3.8 and Stage 3.4.2–3.4.7 authorities;
  - read-only persisted-state qualification evaluator;
  - exact event-sequence and repository-footprint checks.
- Stage 3.9.4 qualification contract/read-only API routes.
- Stage 3.9.4 runtime health metadata.
- Focused Stage 3.9.4 tests, including governance ALLOW, DENY/fail-closed, idempotent replay, restart reconstruction, lineage continuity, and no-dispatch boundary checks.
- `STAGE3_9_4_ACCEPTANCE.ps1`.

## Changed

- Runtime control version: `stage3.9.4-routing-delegation-governance-continuity`.
- HTTP server version: `APTSMissionOrchestrator/3.9.4`.
- Historical regression expectations updated to the new active control/server version.

## Preserved

- Repository migration level: `53`.
- Existing Stage 3.3 planning authorities.
- Existing Stage 3.4 routing/delegation authorities.
- External aptsGSS as Governance decision authority.
- Pre-dispatch governance revalidation requirement.
- Stage 3.9.5 ownership of dispatch/execution/evidence.
