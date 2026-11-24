# Stage 2.9.6-H1 — Durable Governance SCOPE_CHANGED Ingress Hardening

## Purpose

Close the operational defect exposed by Stage 2.9.6 diagnostics where Governance
transactional-outbox `SCOPE_CHANGED` events could retry indefinitely after the target
VulnDesk `MissionRuntime` was no longer present.

Observed failure pattern:

- Governance outbox delivery receives HTTP 500 from VulnDesk.
- VulnDesk raises `KeyError: Mission runtime not found: <mission_id>`.
- `SCOPE_CHANGED` remains `FAILED` and is retried indefinitely.

## Semantic rule

Authoritative Governance lifecycle/audit events are durable provenance and may be
accepted without a live in-memory mission runtime. Operational/reactive CTI events still
require a live runtime.

Stage 2.9.6-H1 adds only `SCOPE_CHANGED` to the existing durable governance ingress set:

- `SCOPE_CHANGED`
- `POLICY_DECISION_ISSUED`
- `POLICY_DECISION_REVALIDATED`
- `POLICY_DECISION_REVALIDATION_FAILED`
- `AUTHORIZATION_REVOKED`

The non-governance invariant remains unchanged: for example `SOURCE_DOWN` with no
runtime must still raise `KeyError`.

## Changed files

1. `cti_services/cti_subsystem_orchestrator.py`
2. `tests/test_cross_subsystem_lineage_stage2_8_8.py`

No database migration is required. No aptsGSS source change is required.

## Expected recovery

After the patched VulnDesk service is restarted, the already-running Governance outbox
worker should retry the six failed historical `SCOPE_CHANGED` events. They should be
accepted as durable audit/provenance ingress and transition naturally to `DELIVERED`.

Do not manually modify or delete Governance outbox records.
