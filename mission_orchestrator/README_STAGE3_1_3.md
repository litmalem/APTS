# Stage 3.1.3 — Mission Scope, RoE & Constraint Contract

Stage 3.1.3 extends the **APTS Global Mission Orchestrator (`APTS-MO01`)** with a canonical, machine-readable mission boundary contract. The new artifact is independent of the immutable Stage-3.1.1 mission envelope and the mutable Stage-3.1.2 lifecycle projection.

The contract is intentionally **definition authority, not execution authorization**. `APTS-MO01` owns the canonical mission definition/snapshot. The uploaded `aptsGSS` remains the authoritative Governance plane for policy evaluation, `ALLOW/DENY/REVIEW`, human approval, revocation, hard-deny enforcement, and emergency stop. Governance binding is deliberately not performed in this sub-stage; that is a later integration concern.

## Canonical contract

Schema version:

```text
apts-mission-scope-roe-constraint-v1
```

Each mission has one stable `mission_scope_contract_id` and an append-only sequence of immutable snapshots:

```text
contract_version = 1, 2, 3, ...
snapshot_id      = mscope-snap-...
canonical_sha256 = SHA-256 over canonical contract core
```

A mutable head row points to the latest immutable version. Revisions use optimistic `expected_contract_version`, and every request also carries an `idempotency_key` so network retries do not create duplicate versions.

## Scope model

The canonical scope object contains:

- `targets[]`
- `excluded_targets[]`
- `network_ranges[]`
- `domains[]`
- `services[]`

`targets[]` and `excluded_targets[]` accept typed target objects using the current Governance-compatible target vocabulary:

```text
IP | CIDR | HOST | DOMAIN | URL | APPLICATION | OTHER
```

IP addresses, CIDRs, domains, absolute HTTP(S) URLs, service ports, and time windows receive semantic validation before persistence.

## Rules of Engagement model

The RoE object contains:

- `allowed_action_classes`
- `prohibited_action_classes`
- `allowed_time_window`
- `maximum_concurrency`
- `destructive_actions_allowed`
- `credential_usage_allowed`
- `persistence_allowed`
- `human_approval_required_for`

The action-class vocabulary is harmonized with the uploaded `aptsGSS` Governance plane:

```text
INTERNAL_REASONING
REPORTING
CTI_SOURCE_READ
TARGET_RECON
TARGET_ENUMERATION
VULNERABILITY_VALIDATION
CONTROLLED_EXPLOITATION
POST_EXPLOITATION
CREDENTIAL_USE
PRIVILEGE_ESCALATION
LATERAL_MOVEMENT
DATA_ACCESS
DESTRUCTIVE_ACTION
```

Fail-closed semantic invariants include:

1. an action class cannot be both allowed and prohibited;
2. `human_approval_required_for` must be a subset of the allowed action classes;
3. `DESTRUCTIVE_ACTION` cannot be in the allow-list while `destructive_actions_allowed=false`;
4. `CREDENTIAL_USE` cannot be in the allow-list while `credential_usage_allowed=false`;
5. the allowed time window must be timezone-aware and `end_at > start_at`.

These checks define internal consistency only. They **do not grant authorization**.

## Constraint model

The constraint object contains:

- `max_actions`
- `max_duration`
- `risk_threshold`
- `resource_budget`
- `data_handling_policy`

`max_actions` and `max_duration` must be positive integers. `risk_threshold` uses:

```text
LOW | MODERATE | HIGH | CRITICAL
```

`MEDIUM` is accepted only as a compatibility alias and is canonicalized to `MODERATE`, matching current `aptsGSS` risk semantics.

## Persistence

Stage 3.1.3 adds:

```text
mission_scope_contract_heads
mission_scope_contract_versions
```

`mission_scope_contract_versions` is append-only. A revision never updates or deletes a prior snapshot. The Stage-3.1.1 `mission_envelopes` table is not modified.

## API

Existing Stage-3.1.1 and Stage-3.1.2 endpoints remain available. Stage 3.1.3 adds:

```text
POST /api/missions/{mission_id}/scope-contract
GET  /api/missions/{mission_id}/scope-contract
GET  /api/missions/{mission_id}/scope-contract/history
```

### Initial version

```json
{
  "expected_contract_version": 0,
  "idempotency_key": "scope-op-001",
  "actor": "operator-01",
  "scope": {
    "targets": [
      {
        "target_type": "CIDR",
        "target_value": "127.0.0.0/8",
        "environment": "LAB"
      }
    ],
    "excluded_targets": [
      {
        "target_type": "IP",
        "target_value": "127.0.0.254",
        "environment": "LAB"
      }
    ],
    "network_ranges": ["127.0.0.0/8"],
    "domains": ["lab.example.test"],
    "services": [
      {
        "name": "https",
        "protocol": "TCP",
        "port": 443,
        "target_ref": "lab.example.test"
      }
    ]
  },
  "roe": {
    "allowed_action_classes": ["TARGET_RECON", "VULNERABILITY_VALIDATION"],
    "prohibited_action_classes": ["DESTRUCTIVE_ACTION", "CREDENTIAL_USE"],
    "allowed_time_window": {
      "start_at": "2026-09-02T00:00:00Z",
      "end_at": "2026-09-03T00:00:00Z"
    },
    "maximum_concurrency": 2,
    "destructive_actions_allowed": false,
    "credential_usage_allowed": false,
    "persistence_allowed": false,
    "human_approval_required_for": ["VULNERABILITY_VALIDATION"]
  },
  "constraints": {
    "max_actions": 20,
    "max_duration": 1800,
    "risk_threshold": "MODERATE",
    "resource_budget": {
      "max_network_requests": 500
    },
    "data_handling_policy": {
      "classification": "INTERNAL",
      "retention_days": 7,
      "export_allowed": false
    }
  },
  "reason": "Initial laboratory boundary",
  "metadata": {
    "environment": "LAB"
  }
}
```

For the first snapshot, `expected_contract_version` must be `0`. A revision sends the current version, for example `1`, and receives version `2`. A stale writer receives HTTP `409 MISSION_SCOPE_CONTRACT_CONFLICT`.

## Boundary with the Stage-3.1.1 envelope

Stage 3.1.1 already allowed a `bindings.scope` reference so existing Stage-2 Governance identifiers could be carried during transition. Stage 3.1.3 does **not** rewrite that immutable reference. The new mission contract is a separate canonical artifact with its own stable identity, snapshots, and hashes.

This separation is deliberate: later Governance Binding can correlate the mission contract snapshot to an authoritative `aptsGSS` ScopeContract without retroactively mutating the original mission envelope.

## Local run

SQLite auto-creates the new tables:

```powershell
cd D:\mission_orchestrator
python .\run\run_mission_orchestrator.py --host 127.0.0.1 --port 8780
```

For MariaDB/MySQL apply:

```powershell
mysql -u root -p < .\migrations\003_stage3_1_3_mission_scope_roe_constraint_contract.sql
```

## Acceptance

With the service running in another PowerShell:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process Bypass -Force
.\STAGE3_1_3_ACCEPTANCE.ps1
```

Expected terminal line:

```text
STAGE 3.1.3 ACCEPTANCE: PASS
```
