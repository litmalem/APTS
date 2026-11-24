# Patch Notes — Stage 3.1.10 Acceptance & Regression Gate

## Added

- Static Stage-3.1 acceptance/release contract in `mission_orchestrator/acceptance_gate.py`.
- Stage-3.1.10 health metadata that declares the closure gate without runtime self-certification.
- Ten Stage-3.1.10 closure/regression tests.
- `STAGE3_1_10_ACCEPTANCE.ps1` for full local regression plus live Mission/Governance/CTI contract probes.
- Installation, manifest, and release documentation for Stage 3.1.10.

## Changed

- Current Mission Orchestrator `control_version` advances to `stage3.1.10-acceptance-regression-gate`.
- `supported_controls` now explicitly retains Stage 3.1.9 and appends Stage 3.1.10.
- Existing Stage-3.1.6 through Stage-3.1.9 regression assertions are updated to recognize the new current control version.
- Package description advances from “through Stage 3.1.9” to “through Stage 3.1.10”.
- HTTP server version/banner advances to Stage 3.1.10 so operator-visible runtime identity does not remain on the Stage-3.1.9 label.

## Preserved

- Repository migration level **8**; no Stage-3.1.10 migration.
- Existing canonical identity, state, Scope/RoE/Constraint, Governance binding, routing, versioning, persistence, validation, event, and lineage schemas.
- aptsGSS as sole policy/approval/revocation/emergency-stop authority.
- CTI/VulnDesk ownership of CTI-local state and plan versions.
- Governed CTI subsystem routing as a non-actuating control-plane operation.
- `dispatch_enabled=false` for target-action execution.
- `target_action_dispatch_enabled=false`.
- `target_actuation=false`.

## Deliberately not added

- No Global Planner.
- No target-action dispatch or target actuation.
- No new policy/authorization authority.
- No new event-delivery bus.
- No new public event-write API.
- No new durable store or schema migration.
- No Stage-3.1.10 source patch for aptsGSS or VulnDesk.

## Validation

- Python compile: PASS.
- Full local regression: **111 passed**.
- Live acceptance is provided by `STAGE3_1_10_ACCEPTANCE.ps1` and must be run against the operator's active Mission/Governance/CTI services.
