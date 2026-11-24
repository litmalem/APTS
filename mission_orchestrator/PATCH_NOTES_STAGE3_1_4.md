# Patch Notes — Stage 3.1.4 Governance & Authorization Binding Contract

## Added

- capability-based Mission→Governance binding contract
- immutable Governance binding versions with optimistic concurrency
- local authorization-decision bindings with authoritative aptsGSS provenance
- durable cross-service operation journals for response-loss recovery
- fail-closed HTTP adapter for existing aptsGSS response envelopes
- exact external ScopeContract id/version/hash validation
- exact PolicyDecision scope/policy/hash/validity validation
- canonical excluded-target and out-of-scope prechecks
- default-deny unknown/unbound capability handling
- stale-binding detection after Stage-3.1.3 scope revision
- MariaDB/MySQL migration `004_stage3_1_4_governance_authorization_binding_contract.sql`
- six Stage-3.1.4 Mission Orchestrator API routes
- Stage-3.1.4 acceptance and documentation artifacts

## Preserved

- aptsGSS remains the policy, approval, emergency-stop, revocation, and authorization authority.
- Stage-3.1.1 mission envelope remains immutable.
- Stage-3.1.2 mission state remains unchanged by binding/evaluation.
- Stage-3.1.3 canonical scope/RoE/constraint snapshots remain append-only and are not rewritten by Stage 3.1.4.
- Existing Stage-3.1.1/3.1.2/3.1.3 acceptance scripts are not modified.
- `dispatch_enabled=false` and `target_actuation=false` remain hard architectural boundaries.

## Important semantic point

`authorization_granted=true` means aptsGSS issued an authoritative `ALLOW` for the bound request. It does **not** mean the Mission Orchestrator may dispatch the action. Every authorized target action is marked `pre_dispatch_revalidation_required=true`, and `execution_authorized` remains `false` in Stage 3.1.4.

## Regression

Current test suite after this patch:

```text
48 passed
```
