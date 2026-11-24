# aptsGSS Stage 2.9.4 — Governance Correlation Read Model

Stage 2.9.4 adds a read-only authoritative mission provenance endpoint for VulnDesk.

## New endpoint

`GET /api/governance/correlation/missions/{mission_id}`

It returns existing durable Governance state only:

- `gov_scope_contracts`;
- `gov_authorization_requests`;
- `gov_policy_decisions`;
- `gov_event_outbox` including decoded event payload;
- `gov_audit_log` including decoded audit payload.

The endpoint does not issue, renew, revalidate, revoke, or otherwise change authorization.
It exists so VulnDesk can correlate canonical lineage without direct database access.

## New health capability

`governance_correlation_probe_mode = MISSION_SCOPED_AUTHORITATIVE_READ_ONLY`

## Database

No schema migration is required. Existing mission indexes are sufficient and no
cross-database foreign key is introduced.

## Files changed

- `app/repositories.py`
- `app/governance_service.py`
- `app/main.py`
- `app/interface_catalog.py`

## File added

- `tests/test_governance_correlation_stage2_9_4.py`
