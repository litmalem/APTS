# Stage 3.1.8 — Canonical Mission API & Validation Layer

## Purpose

Stage 3.1.8 stabilizes the **Canonical Mission API** of the Global Mission Orchestrator (`APTS-MO01`) after the Stage-3.1.1 through Stage-3.1.7 identity, state, Scope/RoE/Constraint, Governance binding, governed routing, concurrency/versioning, and durable repository contracts have been established.

This stage does **not** add a planner or target execution path. Its job is to make the canonical mission contract externally consumable through a stable API and to provide a local, fail-closed **preflight validation layer** before a caller persists/adopts a mission draft for later planning.

The authority boundary remains unchanged:

- `APTS-MO01` owns canonical global mission definition and its local durable artifacts.
- `aptsGSS / GOV-PLANE` remains the sole authority for policy decisions, approval, revocation, hard-deny, and emergency-stop semantics.
- VulnDesk/CTI remains authoritative for CTI-local mission `state_version` and `plan_version`.
- Stage 3.1.8 validation performs no Governance decision, CTI dispatch, planning, target dispatch, or target actuation.

## Canonical Mission API schema

Stage 3.1.8 declares:

- `canonical_mission_api_schema_version = apts-canonical-mission-api-v1`
- `canonical_mission_validation_schema_version = apts-canonical-mission-validation-v1`
- `validation_mode = PREFLIGHT_NO_PERSISTENCE_FAIL_CLOSED`

Existing stable APIs remain available:

- `POST /api/missions`
- `GET /api/missions/{mission_id}`
- `GET /api/missions/{mission_id}/envelope`
- `GET /api/missions/{mission_id}/state`
- `POST /api/missions/{mission_id}/state/transitions`
- `POST /api/missions/{mission_id}/scope-contract`
- `GET /api/missions/{mission_id}/scope-contract`
- Stage-3.1.4 through Stage-3.1.7 Governance, routing, version-vector, command, projection, and repository endpoints.

Stage 3.1.8 adds:

- `POST /api/missions/validate`
- `GET /api/missions/{mission_id}/canonical-contract`

## Preflight validation request

`POST /api/missions/validate` accepts a **draft**, not a persisted mission:

```json
{
  "mission": {
    "idempotency_key": "operator-001",
    "source_system": "OPERATOR_API",
    "created_by": "operator",
    "mission_kind": "AUTONOMOUS_PENTEST",
    "objective": {
      "type": "SECURITY_VALIDATION",
      "target_ref": "lab-target"
    },
    "budgets": {
      "time_seconds": 1800
    },
    "required_subsystems": ["CTI", "PENTEST"]
  },
  "scope_contract": {
    "expected_contract_version": 0,
    "idempotency_key": "scope-001",
    "actor": "operator",
    "scope": {
      "targets": [
        {
          "target_type": "CIDR",
          "target_value": "127.0.0.0/8",
          "environment": "LAB"
        }
      ]
    },
    "roe": {
      "allowed_action_classes": ["INTERNAL_REASONING", "TARGET_RECON"],
      "prohibited_action_classes": ["DESTRUCTIVE_ACTION"],
      "maximum_concurrency": 2,
      "destructive_actions_allowed": false,
      "credential_usage_allowed": false,
      "persistence_allowed": false,
      "human_approval_required_for": []
    },
    "constraints": {
      "max_actions": 20,
      "max_duration": 1800,
      "risk_threshold": "MODERATE",
      "resource_budget": {},
      "data_handling_policy": {
        "classification": "INTERNAL"
      }
    }
  }
}
```

The endpoint deliberately reuses the same canonical normalizers used by the write APIs. A draft therefore cannot be validated under one representation and later normalized into a materially different representation by the existing mission/scope write contracts.

## Validation pipeline

The Stage-3.1.8 preflight pipeline is ordered and fail-closed:

1. **SCHEMA**
   - validation wrapper shape;
   - mission create-contract fields and JSON types;
   - Scope/RoE/Constraint top-level contract shape;
   - unknown-field rejection.
2. **SEMANTIC**
   - canonical `objective.type` must be present;
   - at least one canonical subsystem must be declared;
   - currently supported canonical subsystem declarations are `CTI` and `PENTEST`.
3. **SCOPE**
   - target/domain/network/service normalization;
   - Scope/RoE consistency;
   - target/include-vs-exclude conflict rejection;
   - action-class and approval semantics;
   - at least one positive scope element is required for canonical admission.
4. **CONSTRAINTS**
   - positive action/duration limits;
   - supported risk threshold;
   - JSON-valid resource/data-handling constraints;
   - cross-contract duration alignment: `scope_contract.constraints.max_duration` cannot exceed a declared mission duration budget (`time_seconds`, `max_duration`, or `duration_seconds`).

A valid response contains deterministic request SHA-256 fingerprints and explicitly states that no persistence, authority query, planning, or target action was performed.

## Fail-closed validation error

A Stage-3.1.8 preflight failure returns HTTP 400:

```json
{
  "status": "error",
  "code": "MISSION_VALIDATION_FAILED",
  "validation_phase": "SCOPE",
  "validation_check_id": "SCOPE_ROE_CONTRACT",
  "message": "...",
  "persistence_performed": false,
  "authority_query_performed": false,
  "planning_performed": false,
  "target_action_performed": false
}
```

This error is separate from legacy resource-write validation (`MISSION_CONTRACT_INVALID`) so clients can attribute a failed composite preflight to the exact admission layer.

## Canonical contract read projection

`GET /api/missions/{mission_id}/canonical-contract` provides one **local-only** read projection containing:

- canonical mission identity;
- immutable envelope;
- current canonical mission state;
- current Scope/RoE/Constraint snapshot when present;
- scope snapshot/version identifiers;
- explicit execution-boundary fields.

Before a Scope contract exists:

- `contract_status = IDENTITY_STATE_ONLY`
- `contract_complete = false`

After the current Scope snapshot exists:

- `contract_status = SCOPE_BOUND`
- `contract_complete = true`

The projection does not query live Governance or CTI and does not claim external authority state.

## Database change

**No database migration is added in Stage 3.1.8.**

The validation layer is stateless. The canonical contract projection reads the already durable Stage-3.1.1 through Stage-3.1.7 repository model. Repository migration level remains **7**.

## Health contract

`GET /health` now reports, among others:

- `control_version=stage3.1.8-canonical-mission-api-validation-layer`
- `canonical_mission_api_schema_version=apts-canonical-mission-api-v1`
- `canonical_mission_api_stabilized=true`
- `canonical_mission_validation_schema_version=apts-canonical-mission-validation-v1`
- `canonical_mission_validation_mode=PREFLIGHT_NO_PERSISTENCE_FAIL_CLOSED`
- `canonical_mission_validation_pipeline=[SCHEMA, SEMANTIC, SCOPE, CONSTRAINTS]`
- `canonical_mission_preflight_enabled=true`
- `validation_external_authority_queries=false`
- Stage-3.1.7 repository migration level remains `7`.

Safety remains unchanged:

- `dispatch_enabled=false`
- `target_action_dispatch_enabled=false`
- `target_actuation=false`

## Acceptance evidence

Local validation performed for this patch:

- `python -m compileall -q mission_orchestrator tests` — PASS
- `python -m pytest -q` — **91 passed**
- live HTTP `/health` smoke — PASS
- live HTTP `POST /api/missions/validate` — PASS
- live HTTP validation failure / phase attribution — PASS
- live HTTP `GET /api/missions/{mission_id}/canonical-contract` before and after Scope binding — PASS

## Intentional Stage-3.1.8 boundary

Stage 3.1.8 does not implement:

- Global Planner or autonomous task decomposition;
- new Governance authority;
- policy/approval decisions inside Mission Orchestrator;
- target action dispatch or target actuation;
- replacement of CTI/Pentest subsystem-local state authority;
- a new repository source of truth or database migration.

It closes the **API and validation-layer** concern only, preserving the authority and execution boundaries established by the prior stages.
