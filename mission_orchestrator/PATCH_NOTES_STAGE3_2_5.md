# Patch Notes — Stage 3.2.5 Waiting States: Evidence & Approval Dependency Control

## Added

- Waiting dependency contract schema `apts-mission-waiting-dependency-control-v1`.
- Mode `EXPLICIT_WAIT_DECLARATION_AND_LOCAL_RESOLUTION_EVIDENCE_FAIL_CLOSED`.
- Typed wait declarations for:
  - `WAIT_FOR_EVIDENCE` / `EVIDENCE`;
  - `WAIT_FOR_APPROVAL` / `APPROVAL`.
- Matching `SATISFIED` resolution requirement before `START` can return a waiting mission to `RUNNING`.
- Mandatory non-empty resolution `evidence_refs`.
- Durable transition evidence:
  - `mission_waiting_dependency`;
  - `mission_waiting_dependency_resolution`.
- Waiting dependency lineage reconstruction from the existing transition ledger.
- Guard checks:
  - `WAITING_DEPENDENCY_DECLARATION_FOR_WAIT`;
  - `WAITING_DEPENDENCY_LINEAGE_FOR_RETURN`;
  - `WAITING_DEPENDENCY_RESOLUTION_MATCH_FOR_RETURN`;
  - `WAITING_DEPENDENCY_RESOLUTION_EVIDENCE_FOR_RETURN`.
- `GET /api/missions/{mission_id}/waiting-dependency-contract`.
- Waiting dependency projection embedded in lifecycle-command discovery.
- Explicit approval-dependency versus Governance-authorization separation.
- Sixteen Stage-3.2.5 regression cases.
- `STAGE3_2_5_ACCEPTANCE.ps1`.

## Changed

- Current control advances to `stage3.2.5-waiting-dependency-control`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.2.5`.
- `START` from `WAITING_EVIDENCE` or `WAITING_APPROVAL` now fails closed unless active dependency lineage and matching resolution evidence exist.
- `WAIT_FOR_EVIDENCE` and `WAIT_FOR_APPROVAL` now require typed `metadata.dependency` declarations.
- Stage-3.2.5 dependency guards are no longer listed as deferred; Stage 3.2.6 and Stage 3.2.8 remain deferred.
- Prior regression fixtures are updated only where later lifecycle semantics supersede Stage-3.2.4 deferred behavior or current-control metadata.

## Preserved

- Stage-3.1.2 canonical lifecycle topology.
- Stage-3.1.6 version-vector/idempotency command gate.
- Stage-3.2.2 local fail-closed guard matrix.
- Stage-3.2.3 immutable PIP activation proof.
- Stage-3.2.4 planning/run activation lineage.
- Existing command journal, transition ledger, and Mission event lineage.
- Legacy direct state-transition API; direct waiting transitions do not fabricate Stage-3.2.5 dependency evidence.
- Repository migration level **8**.
- aptsGSS as sole Governance/authorization authority.
- `target_action_dispatch_enabled=false`.
- `target_actuation=false`.
- No source changes in aptsGSS or VulnDesk.

## Deliberately deferred

- No external dependency polling/subscription.
- No automatic event-driven resume.
- No Stage-3.2.6 pause/resume/replanning policy extension.
- No autonomous planner implementation.
- No verified cleanup/completion gate; Stage 3.2.8.
- No target action dispatch or actuation.

## Validation

- Python compile: PASS.
- Full regression: **182 passed**.
- Fresh SQLite HTTP smoke: PASS.
