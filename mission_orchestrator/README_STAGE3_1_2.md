# Stage 3.1.2 — Canonical Mission State Model

Stage 3.1.2 extends the **Global Mission Orchestrator (`APTS-MO01`)** created in 3.1.1 with a canonical, durable global mission lifecycle. The 3.1.1 `global_missions` identity and `mission_envelopes` artifacts remain immutable. Mutable lifecycle state is deliberately stored in separate tables.

## Implemented state machine

Canonical states:

```text
CREATED
PIP_BOUND
PLANNING
RUNNING
WAITING_EVIDENCE
WAITING_APPROVAL
REPLANNING
PAUSED
CLEANING_UP
COMPLETED
ABORTED
FAILED
EXPIRED
```

Terminal states are:

```text
COMPLETED | ABORTED | FAILED | EXPIRED
```

Terminal states have **no outgoing transitions**.

The primary success path is:

```text
CREATED -> PIP_BOUND -> PLANNING -> RUNNING -> CLEANING_UP -> COMPLETED
```

`RUNNING` may enter `WAITING_EVIDENCE`, `WAITING_APPROVAL`, `REPLANNING`, or `PAUSED`. Those states may legally return to execution/replanning according to the canonical transition table in `mission_orchestrator/state_model.py`. `FAILED`, `ABORTED`, and `EXPIRED` are fail-closed terminal exits from every non-terminal state.

## Concurrency invariant

Every transition request must provide `expected_state_version`. A transition succeeds only when that value exactly matches the current durable `state_version`. The update and append-only transition record are committed atomically. Stale writers receive HTTP `409 MISSION_STATE_VERSION_CONFLICT` rather than silently overwriting a newer state.

The initial snapshot is:

```text
state = CREATED
state_version = 1
terminal = false
```

Each successful transition increments `state_version` by exactly one.

## Persistence

Stage 3.1.2 adds:

- `mission_states` — one mutable current-state projection per canonical `mission_id`;
- `mission_state_transitions` — append-only transition ledger ordered by `to_state_version`.

Existing Stage-3.1.1 missions are automatically backfilled into `CREATED / state_version=1` when the repository starts or when migration `002_stage3_1_2_canonical_mission_state_model.sql` is applied.

No canonical envelope is rewritten during backfill or state transition.

## API

Existing Stage-3.1.1 endpoints remain:

- `GET /health`
- `POST /api/missions`
- `GET /api/missions/{mission_id}`
- `GET /api/missions/{mission_id}/envelope`

Stage 3.1.2 adds:

- `GET /api/missions/{mission_id}/state`
- `POST /api/missions/{mission_id}/state/transitions`
- `GET /api/missions/{mission_id}/state/transitions`

Example transition:

```json
{
  "expected_state_version": 1,
  "to_state": "PIP_BOUND",
  "actor": "mission-controller",
  "reason_code": "PIP_BOUND_CONFIRMED",
  "reason": "PIP reference has been confirmed for orchestration",
  "evidence_refs": ["pip:pip-stage312-001"],
  "metadata": {
    "source": "acceptance"
  }
}
```

## Important boundary

Stage 3.1.2 is **state authority, not execution authority**. It still does not implement:

- task decomposition;
- capability discovery/registry;
- CTI or Pentest dispatch;
- Governance authorization/approval evaluation;
- cross-subsystem event intake;
- target execution or actuation.

Therefore `PIP_BOUND`, `WAITING_APPROVAL`, and similar lifecycle markers are canonical global state markers only at this stage. They do not themselves prove that a downstream Governance decision, dispatch, or target action has occurred. Those integrations belong to later Stage-3.1 sub-stages.

## Local upgrade / run

For the current SQLite installation, no manual migration is required. Starting the service automatically creates the Stage-3.1.2 tables and backfills existing missions:

```powershell
cd D:\mission_orchestrator
python .\run\run_mission_orchestrator.py --host 127.0.0.1 --port 8780
```

For MariaDB/MySQL:

```powershell
mysql -u root -p < .\migrations\002_stage3_1_2_canonical_mission_state_model.sql
```

Then run the service with the same `MISSION_DB_*` environment variables used in Stage 3.1.1.

## Acceptance

In another PowerShell:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process Bypass -Force
.\STAGE3_1_2_ACCEPTANCE.ps1
```

Expected final line:

```text
STAGE 3.1.2 ACCEPTANCE: PASS
```
