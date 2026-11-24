# Patch Notes — Stage 3.4.1 Canonical Subsystem Registry & Capability Contract

## Added

- `mission_orchestrator/subsystem_registry.py`
  - canonical CTI/PENTEST identities;
  - immutable subsystem contracts;
  - immutable capability contracts;
  - deterministic registry snapshot and SHA-256 verification;
  - subsystem/component and capability helper functions.
- persistence stores:
  - `subsystem_registry_snapshots`;
  - `canonical_subsystems`;
  - `subsystem_capability_contracts`.
- migration `018_stage3_4_1_canonical_subsystem_registry_capability_contract.sql`.
- read-only registry/subsystem/capability APIs.
- fail-closed registry/subsystem/capability error types.
- `tests/test_stage3_4_1_canonical_subsystem_registry_capability_contract.py` with 18 cases.
- Stage-3.4.1 README, install guide, live acceptance script, patch manifest, and SHA-256 inventory.

## Changed

- active control -> `stage3.4.1-canonical-subsystem-registry-capability-contract`;
- HTTP server identity -> `APTSMissionOrchestrator/3.4.1`;
- package declaration -> through Stage 3.4.1;
- repository migration level -> `18`;
- canonical Mission `required_subsystems` validation now consumes the registry vocabulary;
- historical assertions that intentionally track current runtime control/server/migration metadata are rebased to Stage 3.4.1.

## Canonical registry

```text
CTI
  cti.read.context
  cti.analyze.context

PENTEST
  pentest.recon
  pentest.validate
```

Registry SHA-256:

```text
e4ba88928945631f469e4a70205bab6b0cb1f7584da805f31197da554108d1e1
```

## Preserved

- all Stage-3.1 through Stage-3.3.10 canonical Mission/lifecycle/planning artifacts;
- Stage-3.3.10 planning closure contract;
- existing per-Mission persistence-manifest semantics;
- existing Stage-3.1.5 CTI-only high-level routing scope;
- `EXTERNAL_APTS_GSS` as sole Governance authorization authority;
- no subsystem health probe;
- no runtime endpoint binding;
- no Stage-3.4.2 candidate resolution;
- no Stage-3.4.3 eligibility gate;
- no route selection;
- no task delegation;
- no target-action dispatch or target actuation.

## Boundary

```text
REGISTRATION != AVAILABILITY
CAPABILITY   != PERMISSION
REGISTRY     != AUTHORIZATION
ROUTE        != EXECUTION
```

## Validation target

```text
historical Stage 3.1.1-3.3.10 : 506 tests
new Stage 3.4.1               : 18 tests
expected total                 : 524 passed
```
