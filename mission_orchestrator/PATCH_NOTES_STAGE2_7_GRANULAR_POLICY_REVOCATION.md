# Stage 2.7 — aptsGSS Granular PolicyDecision Revocation Event Contract

This patch keeps aptsGSS as the authoritative decision lifecycle owner and enriches the
revocation event so VulnDesk can correlate it to exact TaskContract bindings.

Changes:

- `GovernanceService.revoke_decision()` returns/publishes `revocation_id`, `decision_id`,
  `request_id`, `mission_id`, `decision_hash`, scope/policy identifiers,
  `decision_status=REVOKED`, actor/reason/timestamp, and authority markers.
- `GovernanceEventPublisher.publish()` embeds its `governance_event_id` in the durable
  outbox payload.
- Global emergency-stop events are explicitly tagged with
  `revocation_scope=GLOBAL_EMERGENCY_STOP`.
- `/health` exposes `policy_revocation_mode=GRANULAR_POLICY_DECISION_EVENT_OUTBOX`.

No new aptsGSS schema is required for Stage 2.7 because the existing decision lifecycle,
append-only hash-chained audit log, and transactional outbox already preserve the
revocation authority and evidence. The new TaskContract-side revocation projection is
stored by VulnDesk migration 06.
