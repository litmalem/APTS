# Stage 3.1.4 — Governance & Authorization Binding Contract

## Purpose

Stage 3.1.4 connects the **canonical mission definition owned by APTS-MO01** to the **authoritative Governance & Safety Plane (`aptsGSS`, component `GOV-PLANE`)** without transferring policy authority to the Mission Orchestrator.

The stage introduces two immutable local artifacts:

1. **Mission Governance Binding Contract** — binds an exact Stage-3.1.3 canonical Scope/RoE/Constraint snapshot and an explicit capability set to one authoritative aptsGSS `ScopeContract`.
2. **Mission Authorization Decision Binding** — binds one concrete capability/resource request to the authoritative aptsGSS `PolicyDecision`, preserving decision provenance locally.

Stage 3.1.4 **does not dispatch or actuate anything**. An `ALLOW` from Governance records authorization provenance only. Target execution remains disabled until a later stage implements pre-dispatch revalidation and dispatch enforcement.

## Authority boundary

| Concern | Authority in Stage 3.1.4 |
|---|---|
| Mission identity/envelope | APTS-MO01 |
| Canonical mission state | APTS-MO01 |
| Canonical mission Scope/RoE/Constraints | APTS-MO01 |
| Capability-to-scope binding definition | APTS-MO01 |
| Policy evaluation / allow-deny-review | **aptsGSS / GOV-PLANE** |
| Emergency stop / hard deny / approval | **aptsGSS / GOV-PLANE** |
| Pre-dispatch revalidation | Required, not yet implemented |
| Dispatch / target actuation | **Disabled** |

The Mission Orchestrator can constrain what it asks Governance to authorize, but it cannot manufacture an `ALLOW` decision.

## Security semantics

The binding contract records these invariants explicitly:

- `CAPABILITY_BASED`
- default effect = `DENY`
- fail closed on missing/unknown/stale/malformed authority state
- canonical RoE cannot be widened by a capability binding
- `DESTRUCTIVE_ACTION` is a hard deny
- human-approval requirements cannot be weakened
- emergency-stop authority remains external and preemptive
- an unbound capability is denied locally before Governance evaluation
- an excluded/out-of-scope target is denied locally before Governance evaluation
- authoritative aptsGSS scope id/version/hash must still match the immutable local binding before each authorization evaluation
- pre-dispatch revalidation is mandatory for authorized target actions
- `dispatch_enabled=false`
- `target_actuation=false`

### Negative scope handling

The uploaded aptsGSS scope matcher considers positive `allowed=true` targets when determining membership. Therefore Stage 3.1.4 performs a mandatory canonical negative-scope precheck in APTS-MO01 before calling Governance. Explicit exclusions take precedence over broader positive CIDRs/domains. This prevents a resource such as an excluded IP inside an allowed CIDR from reaching the external evaluation path.

This local precheck does **not** replace Governance authorization. A request that survives the precheck still requires an authoritative `PolicyDecision` from aptsGSS.

## Governance binding request

`POST /api/missions/{mission_id}/governance-binding`

Representative request:

```json
{
  "expected_binding_version": 0,
  "idempotency_key": "binding-001",
  "actor": "mission-controller",
  "policy_set_id": "default-policy",
  "name": "Mission capability binding",
  "capabilities": [
    {
      "capability_id": "pentest.recon",
      "subject_component": "PENTEST-A01",
      "action_class": "TARGET_RECON",
      "action_name": "recon",
      "authorization_mode": "REQUIRED",
      "resource_types": ["IP", "HOST", "DOMAIN"],
      "max_risk_level": "MODERATE",
      "requires_human_approval": false
    }
  ],
  "reason": "Bind the exact canonical scope to Governance"
}
```

The request uses optimistic concurrency through `expected_binding_version` and normal idempotency through `idempotency_key`.

### Canonical-to-Governance projection

APTS-MO01 projects the exact current Stage-3.1.3 snapshot into an aptsGSS `ScopeContract` and records correlation metadata including:

- mission scope contract id/version
- mission scope snapshot id
- mission scope SHA-256
- binding operation id
- binding request SHA-256
- authority-boundary marker

Only explicitly bound capabilities become positive action constraints. Canonically prohibited action classes are projected as explicit `DENY` constraints. Allowed-but-unbound action classes remain absent, allowing aptsGSS to deny them by default.

## Authorization request

`POST /api/missions/{mission_id}/authorization-bindings`

Representative request:

```json
{
  "idempotency_key": "auth-001",
  "capability_id": "pentest.recon",
  "resource_type": "IP",
  "resource_value": "127.0.0.1",
  "context": {
    "environment": "LAB"
  },
  "evidence_refs": ["evidence://mission/recon/001"],
  "requested_by": "mission-controller"
}
```

The Mission Orchestrator does not accept caller-supplied `subject_component`, `action_class`, or `action_name` on this route. Those values are locked by the capability binding, limiting request-time parameter substitution.

## Decision provenance

For a valid authoritative decision, the immutable local authorization binding records at least:

- `authorization_request_id`
- `policy_decision_id`
- `policy_decision_hash`
- decision = `ALLOW | DENY | REVIEW`
- reason codes and constraints
- approval requirement / approval request id
- `policy_set_id` and `policy_version`
- authoritative `scope_contract_id` and `scope_version`
- validity window
- Governance event id when available
- authority = `aptsGSS`
- authority component = `GOV-PLANE`

An authoritative `ALLOW` produces:

- `authorization_granted=true`
- `governance_status=AUTHORIZED`
- `execution_authorized=false`

The last value is deliberate: Stage 3.1.4 is a binding/provenance control, not a dispatch gate.

## Distributed idempotency and response-loss recovery

A local operation journal is committed **before** cross-service calls.

### Scope creation recovery

`mission_governance_binding_operations.operation_id` is included in aptsGSS ScopeContract metadata. If aptsGSS commits the scope but the HTTP response is lost, a retry reads:

`GET /api/governance/correlation/missions/{mission_id}`

and recovers the externally committed scope by operation id instead of creating a duplicate.

### PolicyDecision recovery

`mission_authorization_operations.operation_id` is included in the authoritative authorization request context. If the PolicyDecision is committed but its HTTP response is lost, a retry uses the same Governance correlation projection to recover the request and decision, preserving one external decision per idempotent operation.

## Data model

Stage 3.1.4 adds five tables:

- `mission_governance_binding_heads`
- `mission_governance_binding_versions`
- `mission_governance_binding_operations`
- `mission_authorization_operations`
- `mission_authorization_bindings`

SQLite creates them automatically on repository startup. MariaDB/MySQL uses:

`migrations/004_stage3_1_4_governance_authorization_binding_contract.sql`

## API additions

- `POST /api/missions/{mission_id}/governance-binding`
- `GET /api/missions/{mission_id}/governance-binding`
- `GET /api/missions/{mission_id}/governance-binding/history`
- `POST /api/missions/{mission_id}/authorization-bindings`
- `GET /api/missions/{mission_id}/authorization-bindings/history`
- `GET /api/missions/{mission_id}/authorization-bindings/{authorization_binding_id}`

Important HTTP failure mappings:

- `403 MISSION_AUTHORIZATION_FAIL_CLOSED`
- `409 MISSION_GOVERNANCE_BINDING_CONFLICT`
- `409 MISSION_AUTHORIZATION_CONFLICT`
- `502 GOVERNANCE_AUTHORITY_PROTOCOL_ERROR`
- `503 GOVERNANCE_AUTHORITY_UNAVAILABLE`

## Runtime configuration

```text
MISSION_GOVERNANCE_BASE_URL=http://127.0.0.1:8770
MISSION_GOVERNANCE_TIMEOUT_SECONDS=3.0
```

The HTTP adapter validates the existing aptsGSS transport envelopes (`scope_contract`, `policy_decision`, and `correlation_snapshot`) before using their contents.

## Health contract

`GET /health` now reports:

- `control_version=stage3.1.4-governance-authorization-binding-contract`
- `governance_binding_enabled=true`
- `governance_binding_mode=CAPABILITY_BASED_DEFAULT_DENY_FAIL_CLOSED`
- `decision_provenance_mode=AUTHORITATIVE_POLICYDECISION_IMMUTABLE_BINDING`
- `governance_authorization_authority=EXTERNAL_APTS_GSS`
- `governance_authority=aptsGSS`
- `governance_authority_component=GOV-PLANE`
- `pre_dispatch_revalidation_required=true`
- `dispatch_enabled=false`
- `target_actuation=false`

Stages 3.1.1, 3.1.2, and 3.1.3 remain listed under `supported_controls`.

## Regression coverage

Stage-3.1.4 tests cover:

- exact scope/capability binding
- optimistic binding versioning
- idempotent replay
- response-loss recovery without duplicate external side effects
- canonical RoE expansion rejection
- hard-deny preservation
- human-approval preservation
- stale binding after scope revision
- unknown capability default deny
- exclusion/out-of-scope local deny
- authoritative ALLOW/DENY provenance
- no dispatch after ALLOW
- malformed Governance response fail-closed behavior
- immutable envelope/state/scope preservation
- real aptsGSS HTTP transport-envelope unwrapping contract
- authority separation in health diagnostics

Run:

```powershell
python -m pytest -q
```

Then, with both `aptsGSS` and `mission_orchestrator` running:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\STAGE3_1_4_ACCEPTANCE.ps1
```
