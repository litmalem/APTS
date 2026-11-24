# Patch Notes — Stage 3.2.3 Mission PIP Activation

## Added

- Mission PIP activation contract schema `apts-mission-pip-activation-v1`.
- Explicit local readiness projection for `CREATED -> PIP_BOUND`.
- `GET /api/missions/{mission_id}/activation-contract`.
- Activation projection embedded in lifecycle-command discovery.
- Canonical-envelope integrity guard specifically at the `BIND_PIP` activation boundary.
- Durable `mission_activation` evidence returned by successful `BIND_PIP` and embedded in transition metadata.
- Exact replay preservation of activation evidence without duplicate transition/event side effects.
- Twelve Stage-3.2.3 regression cases.
- `STAGE3_2_3_ACCEPTANCE.ps1`.

## Changed

- Current control advances to `stage3.2.3-mission-pip-activation`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.2.3`.
- Lifecycle guard matrix advertises `CANONICAL_ENVELOPE_INTEGRITY_FOR_PIP_ACTIVATION`.
- Previous regression assertions recognize Stage 3.2.3 as current while preserving Stage 3.2.2 in `supported_controls`.

## Preserved

- Stage 3.1.2 canonical topology authority.
- Stage 3.1.6 version-vector/idempotency gate.
- Stage 3.2.2 deterministic local guard matrix.
- Immutable Mission envelope as source of PIP id/version.
- Existing command journal, state transition ledger, and event lineage.
- Repository migration level **8**.
- aptsGSS as sole external Governance/authorization authority.
- `target_action_dispatch_enabled=false`.
- `target_actuation=false`.
- No source changes in aptsGSS or VulnDesk.

## Deliberately deferred

- No PIP artifact repository query or PIP semantic/content validation.
- No `PIP_BOUND -> PLANNING -> RUNNING` activation; Stage 3.2.4.
- No evidence/approval dependency resolver; Stage 3.2.5.
- No verified completion gate; Stage 3.2.8.

## Validation

- Python compile: PASS.
- Full regression: **152 passed**.
