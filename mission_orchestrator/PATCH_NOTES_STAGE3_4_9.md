# Patch Notes — Stage 3.4.9 Routing/Delegation Event Lineage, Replay & Recovery

## Added

- Canonical routing/delegation event-sublineage projected from the verified Mission event ledger.
- Deterministic read-only routing/delegation replay with replay hash and exact event/hash-chain bindings.
- Durable restart-safe routing/delegation recovery checkpoint contract with domain-separated SHA-256 integrity verification.
- Canonical recovery reconstruction from durable route decision, delegation, delivery/ownership receipt, and zero-or-more Stage-3.4.8 recovery controls.
- Strict snapshot guards for Mission version, state version, route/delegation/delivery identity+hash, Stage-3.4.8 control count, routing/delegation event count, and event-chain tip hash.
- Exact-idempotent checkpoint replay with conflict rejection for idempotency-key reuse against a changed request.
- Per-snapshot uniqueness: one checkpoint per delivery receipt and Stage-3.4.8 control count.
- New checkpoint eligibility only when the Stage-3.4.8 control chain advances.
- Strict rejection of caller-supplied route candidates, authorization decisions, ownership state, recovery-control content, dispatch commands, or execution content.
- Durable `mission_routing_delegation_recovery_checkpoints` persistence store.
- Migration `026_stage3_4_9_routing_delegation_event_lineage_replay_recovery.sql`.
- Repository create/read/list/idempotency support, restart reconstruction, persistence-manifest accounting, and tamper detection.
- Canonical event `MISSION_ROUTING_DELEGATION_RECOVERY_CHECKPOINTED`.
- GET APIs for lineage, replay, recovery, checkpoint history/checkpoint lookup, and lineage definition.
- POST API for immutable recovery-checkpoint creation.
- Stage-3.4.9 health/capability metadata and runtime identity.
- 22 focused Stage-3.4.9 tests covering runtime activation, canonical definition, lineage selection/order, replay determinism/read-only behavior, checkpoint binding, idempotency, stale guards, forbidden fields, event extension, restart recovery, Stage-3.4.8 advancement, repository integrity, tamper detection, and migration declaration.

## Changed

- Runtime control version to `stage3.4.9-routing-delegation-event-lineage-replay-recovery`.
- Mission Orchestrator server version to `APTSMissionOrchestrator/3.4.9`.
- Repository migration level to `26`.
- Supported-control inventory now includes Stage 3.4.9.
- Repository persistence/integrity model now includes `mission_routing_delegation_recovery_checkpoints`.
- Historical regression assertions that encoded the repository's then-current migration count were rebased to the canonical `REPOSITORY_MIGRATION_LEVEL`; stage-local historical migration identities remain unchanged.

## Preserved authority boundaries

Stage 3.4.9 performs no rerouting, Governance authorization, redelivery, ownership transfer, retry/fallback/reassignment action, endpoint resolution, runtime health probe, resource assignment, external network I/O, work dispatch, execution authorization, target-action dispatch, or target actuation.

The explicit invariants are:

```text
routing_delegation_replay_read_only = true
routing_delegation_replay_side_effects_performed = false
routing_delegation_replay_is_execution = false
routing_delegation_recovery_reconstructs_from_durable_repository = true
routing_delegation_recovery_external_network_io_performed = false
routing_delegation_recovery_governance_query_performed = false
routing_delegation_recovery_is_authorization = false
routing_delegation_recovery_is_routing = false
routing_delegation_recovery_is_redelivery = false
routing_delegation_recovery_is_ownership_transfer = false
routing_delegation_recovery_dispatch_performed = false
routing_delegation_recovery_execution_authorized = false
routing_delegation_recovery_target_action_dispatch_enabled = false
routing_delegation_recovery_target_actuation = false
```

## Validation

- Python compile: PASS.
- Full Stage 3.1-3.4.9 regression: `767 passed in 430.18s`.
- Focused Stage 3.4.9: `22 passed in 29.77s`.
