# Stage 2.8.8 — Cross-Subsystem Enrichment / Acceptance

Stage 2.8.8 makes the authoritative aptsGSS outbox identity (`gevent-*`) a
first-class lineage key across subsystem boundaries.

## End-to-end model

`gov_event_outbox.event_id`
→ synchronous Governance response `governance_event_id`
→ VulnDesk TaskContract external reference
→ CTI `upstream_event_id`
→ DecisionTrace `upstream_event_id`
→ Audit `upstream_event_ref`
→ downstream CTI event.

Revocation continues the same external identity through:
`AUTHORIZATION_REVOKED`
→ `TASK_AUTHORIZATION_REVOKED`
→ `TASK_DISPATCH_BLOCKED`.

## aptsGSS implementation
- Authorization returns exact `POLICY_DECISION_ISSUED` `gevent-*`.
- Revalidation returns exact revalidation `gevent-*`.
- Revocation response returns exact revocation `gevent-*`.
- Governance audit preserves the same provenance identity.
- Health exposes
  `cross_subsystem_lineage_mode=AUTHORITATIVE_EVENT_ID_CORRELATED`.
- PolicyDecision hash is computed before transport provenance is added.
- No aptsGSS migration.

## VulnDesk implementation
- GovernanceClient requires valid `gevent-*` in live authorization and
  revalidation responses (fail closed).
- TaskContract persists issuance and revalidation Governance event IDs.
- TASK_COMMITTED and revalidation/block events use the authoritative `gevent-*`
  as first-class `upstream_event_id`.
- DecisionTrace persists `upstream_event_id`.
- Audit persists `upstream_event_ref`.
- Lifecycle decision/audit materialization propagates external upstream identity.
- Governance lifecycle outbox ingress is durable even after MissionRuntime
  termination/restart, allowing the transactional outbox to converge.
- Arbitrary non-Governance external events still require a live runtime.

## Migration
VulnDesk migration 08 adds local external-reference columns/indexes only.
No cross-database foreign key is introduced; aptsGSS remains authoritative.

## Install order
1. Stop both services and back up source + databases.
2. Patch aptsGSS first and restart it.
3. Apply VulnDesk `08_cross_subsystem_lineage.sql`.
4. Patch VulnDesk and restart it.
5. Run tests.
6. Run a fresh normal governed mission.
7. Run a separate fresh pre-dispatch revocation mission.
8. Run `STAGE2_8_8_ACCEPTANCE.sql`.

## Versions
VulnDesk:
`hybrid-event-driven-2.11-cross-subsystem-lineage`

aptsGSS health:
`cross_subsystem_lineage_mode=AUTHORITATIVE_EVENT_ID_CORRELATED`

## Closure
Build/regression PASS is not enough to close 2.8.8. Runtime cross-database
acceptance must prove issuance, revalidation, outbox convergence, durable local
ingress, decision/audit upstream binding, and revocation using fresh missions.
