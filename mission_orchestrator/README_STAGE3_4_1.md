# Stage 3.4.1 — Canonical Subsystem Registry & Capability Contract

## Purpose

Stage 3.4.1 opens **Stage 3.4 — Subsystem Routing & Task Delegation** by establishing the canonical vocabulary that later routing and delegation controls are allowed to use.

The stage introduces a durable, immutable, hash-verifiable registry for subsystem identity and capability declarations. It answers two questions only:

1. **Which canonical subsystems exist?**
2. **Which canonical capabilities are declared by each subsystem?**

It does **not** decide which subsystem receives a task and does **not** execute or authorize a task.

## Active control

- `control_version = stage3.4.1-canonical-subsystem-registry-capability-contract`
- HTTP server = `APTSMissionOrchestrator/3.4.1`
- repository migration level = `18`
- registry version = `1`
- registry schema = `apts-canonical-subsystem-registry-v1`
- subsystem contract schema = `apts-canonical-subsystem-contract-v1`
- capability contract schema = `apts-subsystem-capability-contract-v1`

## Canonical subsystem identities

Stage 3.4.1 registers exactly:

```text
CTI
PENTEST
```

Canonical identity is deliberately independent from:

- URL / network endpoint;
- IP address / port;
- process or worker instance;
- runtime health;
- deployment topology.

Therefore changing a service endpoint does not create a new canonical subsystem identity.

## Canonical capability contracts

Current capability vocabulary is aligned with the canonical planned-task vocabulary already used by Stage 3.3:

```text
CTI
  cti.read.context
  cti.analyze.context

PENTEST
  pentest.recon
  pentest.validate
```

Each capability contract carries:

- stable `capability_id` and `capability_version`;
- owning canonical `subsystem_id`;
- accepted planned-task schema version;
- capability classification and side-effect class;
- immutable SHA-256 integrity binding;
- explicit authority semantics.

Capability declaration is compatibility metadata only. It is not permission, authorization, dispatch, or actuation.

## Immutable registry snapshot

`mission_orchestrator/subsystem_registry.py` builds a deterministic canonical registry snapshot. The snapshot embeds independently hash-bound subsystem and capability contracts and is itself hash-bound.

Current canonical registry SHA-256:

```text
e4ba88928945631f469e4a70205bab6b0cb1f7584da805f31197da554108d1e1
```

The repository validates the persisted registry SHA-256 and the service verifies the nested contracts before exposing the read model. Integrity failure is fail-closed as `SUBSYSTEM_REGISTRY_INTEGRITY_ERROR`.

## Persistence

Migration `018_stage3_4_1_canonical_subsystem_registry_capability_contract.sql` adds three global stores:

```text
subsystem_registry_snapshots
canonical_subsystems
subsystem_capability_contracts
```

The seed is deterministic and idempotent. SQLite development/test repositories create and seed equivalent structures automatically. Production MySQL must apply migration 018.

These are global routing-definition stores. They are intentionally not added to the per-Mission persistence manifest, so Stage 3.4.1 does not alter historical per-Mission artifact hashing.

## Read-only APIs

```text
GET /api/subsystem-registry-definition
GET /api/subsystem-registry
GET /api/subsystems
GET /api/subsystems/{subsystem_id}
GET /api/subsystems/{subsystem_id}/capabilities
GET /api/subsystems/{subsystem_id}/capabilities/{capability_id}
```

Unknown subsystem/capability identifiers fail closed with `404`.

## Mission-admission vocabulary alignment

The canonical Mission validator now imports its supported `required_subsystems` vocabulary from the same registry module. This prevents the Mission contract and Stage-3.4 routing vocabulary from drifting apart.

Supported Mission `required_subsystems` remains:

```text
CTI
PENTEST
```

## Preserved Stage-3.1.5 routing boundary

The existence of `PENTEST` in the canonical registry does **not** widen the historical Stage-3.1.5 high-level routing/dispatch implementation.

Current health continues to declare:

```text
canonical_registered_subsystems = [CTI, PENTEST]
supported_routing_subsystems    = [CTI]
```

The first list describes canonical registry membership. The second describes the pre-existing Stage-3.1.5 runtime routing scope. They are intentionally different until later Stage-3.4 controls extend routing under explicit authority.

## Authority boundary

Mandatory invariants:

```text
REGISTRATION != AVAILABILITY
CAPABILITY   != PERMISSION
REGISTRY     != AUTHORIZATION
ROUTE        != EXECUTION
```

Stage 3.4.1 performs none of the following:

```text
runtime endpoint binding      = false
subsystem health probing      = false
candidate resolution          = false
route selection               = false
task delegation               = false
Governance authorization query= false
target-action dispatch        = false
target actuation              = false
```

Governance authorization authority remains:

```text
EXTERNAL_APTS_GSS / GOV-PLANE
```

## Tests

Stage 3.4.1 adds:

```text
tests/test_stage3_4_1_canonical_subsystem_registry_capability_contract.py
```

Focused coverage: **18 tests**.

It covers:

- active control and health declarations;
- deterministic canonical registry identity;
- nested SHA-256 verification;
- endpoint-independent subsystem identity;
- capability/authorization separation;
- durable SQLite seed and restart reconstruction;
- local-only registry reads with trap external clients;
- subsystem/capability read models;
- fail-closed unknown identifiers;
- tamper detection;
- component selector/capability helper determinism;
- Mission validator vocabulary alignment;
- preservation of historical Stage-3.1.5 CTI-only routing scope;
- migration-018 contract;
- SQLite schema creation.

Expected full regression after Stage 3.4.1:

```text
524 passed
```

## Acceptance

With the service running on port `8780`:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_4_1_ACCEPTANCE.ps1
```

Expected final result:

```text
STAGE 3.4.1 ACCEPTANCE: PASS
```

## Definition of Done

Stage 3.4.1 is complete when CTI and PENTEST possess stable canonical identities, their declared capabilities are immutable and hash-verifiable, registry state survives restart, the Mission contract uses the same subsystem vocabulary, all reads remain local-only, and no route selection, delegation, Governance authorization, target dispatch, or target actuation authority has been introduced.
