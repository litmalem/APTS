# VulnDesk Stage 2.9.4 — Cross-Subsystem Governance Correlation

## Baseline analyzed

- `Vulndesk(20260829-023750).zip`
- `Vulndesk(20260829-023743).sql`
- `aptsGSS(20260829-023743).zip`
- `AptsGSS(20260829-023743).sql`

The baseline already contains:

- Stage 2.9.1 canonical Task lineage projection;
- Stage 2.9.2 Task Lineage Probe API;
- Stage 2.9.3 Mission Lineage Reconstruction;
- Stage 2.8.8 authoritative `gevent-*` cross-subsystem provenance persisted in TaskContract,
  event, DecisionTrace, and audit layers.

Stage 2.9.4 turns those external references into an explicit read-side correlation with the
independent Governance & Safety Plane. No authority is moved into VulnDesk.

## New VulnDesk control version

`hybrid-event-driven-2.15-cross-subsystem-governance-correlation`

## New Governance read contract

VulnDesk consumes:

`GET /api/governance/correlation/missions/{mission_id}`

The response is a mission-scoped authoritative snapshot containing existing durable:

- ScopeContracts;
- authorization requests;
- PolicyDecisions;
- Governance transactional-outbox events;
- Governance audit records.

The operation is read-only and is **not** an authorization/revalidation operation.

## Correlation behavior

`CrossSubsystemGovernanceCorrelator` correlates a canonical Task/Mission projection against
one aptsGSS mission snapshot using stable identifiers already persisted by Stage 2.8.8:

- `authorization_request_id -> gov_authorization_requests.request_id`;
- `policy_decision_id -> gov_policy_decisions.decision_id`;
- `scope_contract_id -> gov_scope_contracts.scope_contract_id`;
- `authorization_governance_event_id -> gov_event_outbox.event_id`;
- `pre_dispatch_governance_event_id -> gov_event_outbox.event_id`;
- `revocation_event_id -> gov_event_outbox.event_id`;
- mission event `upstream_event_id=gevent-* -> gov_event_outbox.event_id`.

For correlated records it also compares binding dimensions such as mission, request,
PolicyDecision hash, scope/version, policy/version, action/resource dimensions,
revalidation id/task id, and revocation id.

## Correlation statuses

Task correlation can report:

- `CORRELATED` — required authoritative references exist and asserted fields match;
- `PARTIAL` — one or more required records are absent or asserted fields differ;
- `NOT_REQUIRED_INTERNAL` — TaskContract does not require external Governance authority;
- `UNAVAILABLE` — Governance endpoint is unreachable/disabled;
- `PROTOCOL_ERROR` — Governance endpoint returned an invalid correlation contract.

Mission correlation can report:

- `CORRELATED`;
- `PARTIAL`;
- `NOT_REQUIRED`;
- `UNAVAILABLE` / `PROTOCOL_ERROR`.

## Stage boundary

Stage 2.9.4 reports **correlation facts only**:

`classification = CORRELATION_FACTS_ONLY_STAGE_2_9_4`

It deliberately does not classify a missing/mismatched record as an integrity violation.
That remains Stage 2.9.5:

`integrity_classification_status = NOT_EVALUATED_STAGE_2_9_5`

Governance outage also does not erase the local canonical lineage; the local projection is
returned with an explicit correlation availability status.

## Existing API behavior

The existing endpoints are preserved and now enriched at the orchestrator boundary:

- `GET /api/cti/tasks/{task_id}/lineage`
- `GET /api/cti/missions/{mission_id}/lineage`

The local Stage 2.9.1/2.9.3 canonical projection remains unchanged. The response gains a
`governance_correlation` section, while:

- Task `governance_binding.correlation_status` is updated with the runtime correlation status;
- Mission `projection_metadata.governance_correlation_status` is updated similarly.

## Schema / migration

**No database migration is required.**

The baseline schemas already contain all required identifiers and mission indexes. aptsGSS
remains the authoritative database; no cross-database foreign key is introduced.

## Files added

- `cti_services/governance_correlation.py`
- `tests/test_cross_subsystem_governance_correlation_stage2_9_4.py`
- `STAGE2_9_4_ACCEPTANCE.ps1`
- `STAGE2_9_4_ACCEPTANCE.sql`
- `PATCH_NOTES_STAGE2_9_4_CROSS_SUBSYSTEM_GOVERNANCE_CORRELATION.md`
- `BUILD_VALIDATION_STAGE2_9_4.txt`
- `INSTALL_STAGE2_9_4.txt`

## Files changed

- `cti_services/governance_client.py`
- `cti_services/cti_subsystem_orchestrator.py`
- `cti_services/interface_catalog.py`
- `cti_services/__init__.py`
- current-control assertions in Stage 2.9.1–2.9.3 regression tests.

## Next stage

2.9.1 Canonical Lineage Projection Model — complete  
2.9.2 Task Lineage Probe API — complete  
2.9.3 Mission Lineage Reconstruction — complete  
**2.9.4 Cross-Subsystem Governance Correlation — implemented**  
2.9.5 Integrity / Violation Probe — next
