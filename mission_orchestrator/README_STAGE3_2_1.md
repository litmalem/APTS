# Stage 3.2.1 — Mission Lifecycle Command Contract

Stage 3.2.1 is the first implementation stage of **3.2 — Control Mission Lifecycle**. It introduces an explicit lifecycle intent contract while preserving the closed Stage-3.1 canonical foundation.

## Contract

Schema: `apts-mission-lifecycle-command-v1`

Mode: `EXPLICIT_COMMAND_TO_CANONICAL_STATE_VIA_GUARDED_COMMAND_JOURNAL`

A lifecycle command carries:

- `command_id`
- `idempotency_key`
- `command`
- `expected_version_sha256`
- `expected_state_version`
- `actor`
- `reason_code`
- optional `reason`
- optional `evidence_refs`
- `target_state` only for `RESUME`
- optional `metadata`

Every lifecycle mutation is submitted through the existing Stage-3.1.6 guarded command journal as operation `LIFECYCLE_COMMAND`. The command then resolves to an existing Stage-3.1.2 canonical state transition. This gives the lifecycle layer both cross-domain version-vector concurrency protection and state-version CAS protection.

## Command mapping

| Lifecycle command | Canonical target |
|---|---|
| `BIND_PIP` | `PIP_BOUND` |
| `START_PLANNING` | `PLANNING` |
| `START` | `RUNNING` |
| `WAIT_FOR_EVIDENCE` | `WAITING_EVIDENCE` |
| `WAIT_FOR_APPROVAL` | `WAITING_APPROVAL` |
| `PAUSE` | `PAUSED` |
| `RESUME` | explicit target from the existing resume target set |
| `REPLAN` | `REPLANNING` |
| `BEGIN_CLEANUP` | `CLEANING_UP` |
| `COMPLETE` | `COMPLETED` |
| `ABORT` | `ABORTED` |
| `FAIL` | `FAILED` |
| `EXPIRE` | `EXPIRED` |

`RESUME` targets are deliberately restricted to the existing Stage-3.1.2 topology: `PIP_BOUND`, `PLANNING`, `RUNNING`, `REPLANNING`, or `CLEANING_UP`.

## API

### Discover contract for a mission

`GET /api/missions/{mission_id}/lifecycle-command-contract`

The response includes the static contract and `topology_eligible_commands`. This eligibility is explicitly **topology-only**: it is not Governance authorization and it is not the richer prerequisite guard matrix planned for Stage 3.2.2.

### Execute lifecycle command

`POST /api/missions/{mission_id}/lifecycle/commands`

Example:

```json
{
  "command_id": "lc-001",
  "idempotency_key": "idem-lc-001",
  "command": "BIND_PIP",
  "expected_version_sha256": "<current version-vector SHA-256>",
  "expected_state_version": 1,
  "actor": "operator",
  "reason_code": "PIP_READY",
  "reason": "Move mission into PIP_BOUND lifecycle state",
  "evidence_refs": [],
  "metadata": {}
}
```

## Boundaries

Stage 3.2.1 intentionally does **not** implement Stage 3.2.2 prerequisite guards, PIP artifact validation, approval decisions, evidence completion checks, planning, target-action dispatch, or target actuation. aptsGSS remains the external authoritative Governance plane.

Repository migration level remains **8** and no Stage-3.2.1 database migration is required.

## Regression baseline

`125 passed`.
