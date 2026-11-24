# Stage 3.1.6 — Mission Versioning & Concurrency Mode

## Purpose

Stage 3.1.6 hardens the Global Mission Orchestrator (`APTS-MO01`) against **stale writes, duplicate commands, concurrent transitions, and cross-resource race conditions**.

Stages 3.1.2–3.1.5 already version their own local artifacts independently. Stage 3.1.6 does **not** collapse those authority domains into one synthetic version. Instead it introduces:

1. a canonical **Mission Version Vector** read model; and
2. an idempotent **Mission Command Gate** using optimistic concurrency.

The design preserves the existing authority split:

- APTS-MO01 owns global mission state, Scope/RoE/Constraint snapshots, Governance binding versions, and high-level routing contracts;
- `aptsGSS / GOV-PLANE` remains authoritative for Governance scope/policy versions and ALLOW/DENY/REVIEW semantics;
- VulnDesk/CTI remains authoritative for its local `state_version` and `plan_version`;
- Stage 3.1.6 only **observes** external version domains for concurrency protection and never rewrites them.

## Mission Version Vector

`GET /api/missions/{mission_id}/version-vector`

The returned vector is SHA-256 bound and currently observes:

| Version domain | Authority/source |
|---|---|
| `envelope_version` | APTS-MO01 immutable mission envelope |
| `state_version` | APTS-MO01 canonical state model |
| `scope_contract_version` | APTS-MO01 Scope/RoE/Constraint contract |
| `governance_binding_version` | APTS-MO01 Governance binding contract |
| `governance_scope_version` | authoritative aptsGSS scope bound by Stage 3.1.4 |
| `policy_version` | latest locally bound authoritative aptsGSS PolicyDecision, when present |
| `cti_state_version` | live VulnDesk CTI mission observation, after dispatch |
| `cti_plan_version` | live VulnDesk CTI mission observation, after dispatch |

The vector also binds the current scope snapshot/hash, Governance binding snapshot/hash, latest PolicyDecision identity, routed-task set fingerprint, and CTI observation status.

`observed_at` is intentionally **not** part of the version hash, so two reads of unchanged mission state produce the same `version_sha256`.

If a CTI mission has been recorded as dispatched but its version state cannot be read or is inconsistent, `version_vector_complete=false`. A guarded mutation then fails closed with HTTP `503 MISSION_VERSION_OBSERVATION_UNAVAILABLE`.

## Mission Command Gate

`POST /api/missions/{mission_id}/commands`

Representative request:

```json
{
  "command_id": "cmd-stage316-001",
  "idempotency_key": "stage316-001",
  "operation": "STATE_TRANSITION",
  "expected_version_sha256": "<version_sha256 from GET /version-vector>",
  "payload": {
    "expected_state_version": 1,
    "to_state": "PIP_BOUND",
    "actor": "mission-controller",
    "reason_code": "PIP_BOUND_CONFIRMED",
    "metadata": {}
  },
  "submitted_by": "mission-controller",
  "metadata": {
    "source": "stage3.1.6"
  }
}
```

The command gate performs the following sequence under one orchestrator concurrency critical section. All existing mutable mission service entry points are also serialized through the same re-entrant runtime guard, so legacy resource APIs cannot interleave with a guarded command inside one Mission Orchestrator process:

1. persist/recover the command journal entry;
2. reconstruct the current mission version vector;
3. reject an incomplete external observation fail-closed;
4. compare `expected_version_sha256` with the current vector hash;
5. validate the operation's native expected version (`expected_state_version`, `expected_contract_version`, or `expected_binding_version`) where applicable;
6. execute the existing Stage-3 operation;
7. reconstruct and persist the post-command version vector and result.

This does not replace the repository-level compare-and-swap controls already present in Stage 3.1.2, 3.1.3, and 3.1.4. It adds a **cross-resource guard** above them.

## Supported guarded operations

- `STATE_TRANSITION`
- `SCOPE_CONTRACT_PUT`
- `GOVERNANCE_BINDING_PUT`
- `AUTHORIZATION_BINDING_CREATE`
- `ROUTING_TASK_CREATE`
- `ROUTING_TASK_DISPATCH`

The original resource-specific APIs remain available for compatibility. Their existing per-resource OCC/idempotency guarantees remain unchanged and they share the same in-process mutation serialization guard. New workflows that need a consistent cross-resource read-before-write boundary should use the Stage-3.1.6 command gate.

For a future multi-process/active-active Mission Orchestrator deployment, the in-process critical section would need to be complemented by a shared distributed lock/lease or an equivalent single transactional command executor. Repository CAS constraints already remain the final barrier for state/scope/binding writes, but Stage 3.1.6 does not claim a distributed transaction across APTS-MO01, aptsGSS, and CTI.

## Duplicate command semantics

Each command is durably keyed by both:

- `command_id`; and
- `(mission_id, idempotency_key)`.

An identical completed replay returns the originally persisted result with `idempotent_replay=true`; it does not execute the underlying mutation again.

Reuse of the same command identity/idempotency key with a different canonical request fails with:

`409 MISSION_COMMAND_CONFLICT`

A stale version vector fails with:

`409 MISSION_VERSION_CONFLICT`

The stale command is retained in the command journal as `REJECTED_STALE`, providing auditable race evidence without mutating mission state.

## Concurrent transition invariant

Two guarded commands that start from the same `version_sha256` cannot both commit if the first changes any bound version domain. The winner changes the mission version vector; the loser then observes a hash mismatch and is rejected as stale.

For canonical state transitions, Stage 3.1.2 repository CAS on `expected_state_version` remains the final atomic state-write barrier.

## Command journal

Stage 3.1.6 adds:

`mission_command_journal`

Statuses include:

- `PENDING`
- `COMPLETED`
- `REJECTED_STALE`
- `FAILED_OBSERVATION`
- `FAILED`

The journal retains before/after version vectors and the canonical result for deterministic replay/audit.

## API additions

- `GET /api/missions/{mission_id}/version-vector`
- `POST /api/missions/{mission_id}/commands`
- `GET /api/missions/{mission_id}/commands`
- `GET /api/missions/{mission_id}/commands/{command_id}`

Existing Stage-3.1.1 through Stage-3.1.5 APIs remain available.

## Health contract

`GET /health` now reports, among others:

- `control_version=stage3.1.6-mission-versioning-concurrency`
- `mission_version_vector_schema_version=apts-mission-version-vector-v1`
- `mission_command_schema_version=apts-mission-command-v1`
- `mission_versioning_mode=MULTI_DOMAIN_VERSION_VECTOR_HASHED`
- `mission_concurrency_mode=OPTIMISTIC_VERSION_VECTOR_IDEMPOTENT_COMMAND_GATE`
- `mission_command_gate_enabled=true`
- `mission_stale_write_policy=REJECT_FAIL_CLOSED_HTTP_409`
- the observed version domains and supported guarded operations

The safety boundary remains unchanged:

- `dispatch_enabled=false`
- `target_action_dispatch_enabled=false`
- `target_actuation=false`

Stage 3.1.6 does not grant target execution authority.
