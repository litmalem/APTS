# Stage 2.7 — Granular PolicyDecision Revocation ↔ TaskContract Invalidation

Status of this patch: IMPLEMENTED IN SOURCE; local MariaDB + two-service E2E closure still required.

## Invariant

A revocation of PolicyDecision `D` may invalidate only TaskContracts whose
`policy_decision_id = D`. It must not flip the whole mission scope or invalidate
TaskContracts bound to another decision. Global emergency-stop remains a separate,
explicitly mission-wide safety mechanism.

## VulnDesk changes

- `CtiSubsystemOrchestrator.CONTROL_VERSION` -> `hybrid-event-driven-2.5-granular-policy-revocation`.
- `AUTHORIZATION_REVOKED` is projected synchronously at external-event ingress so
  a governance outbox delivery can block a committed task even while the dispatcher
  thread is busy.
- The event is a trigger only. VulnDesk calls the authoritative aptsGSS
  `GET /api/governance/decisions/{decision_id}` before accepting the revocation.
- If authoritative lookup is unavailable, only exact bound tasks fail closed.
- Exact lookup uses `mission_id + policy_decision_id + authorization_mode=REQUIRED`.
- COMMITTED task -> `BLOCKED_REVOKED`.
- RUNNING task -> `REVOCATION_PENDING_STOP`; late result is quarantined and the task
  becomes `CANCELLED_REVOKED`.
- COMPLETED/FAILED history is not rewritten; revocation metadata is appended.
- An atomic COMMITTED -> RUNNING compare-and-set requires no revocation marker,
  closing the revalidation-to-dispatch race window.
- Exact revocation no longer sets `runtime.policy_context["scope_allowed"] = False`.
- Global emergency-stop still cancels the mission.
- Durable revocation projection can be applied even when the in-memory mission runtime
  no longer exists (for example after a VulnDesk restart).

## Database migration

Apply:

`sql_update_cti_harmonized/06_granular_policydecision_revocation.sql`

It adds revocation metadata to `cti_task_contracts`, an exact lookup index, and the
`cti_policy_decision_revocations` durable ledger.

## aptsGSS changes

- `revoke_decision()` publishes exact binding material: revocation_id, decision_id,
  request_id, mission_id, decision_hash, scope/policy identifiers, actor, reason,
  timestamp, and authoritative source markers.
- Governance outbox payloads carry `governance_event_id` for consumer correlation and
  idempotency.
- Emergency-stop events are explicitly tagged as `GLOBAL_EMERGENCY_STOP`.

## Regression in build environment

- VulnDesk: 55 tests passed when excluding `test_nvd_bulk_upsert.py`; that unrelated
  suite requires `pymysql`, which is not installed in the build environment.
- aptsGSS: 19 tests passed with the same non-connecting `pymysql` import stub used for
  isolated unit validation.
- Stage 2.7-specific tests: VulnDesk 5 passed; aptsGSS 2 passed.

## Local E2E closure criteria

1. Apply migration 06 to the VulnDesk MariaDB schema.
2. Start aptsGSS and VulnDesk.
3. Create/observe an ALLOW PolicyDecision and committed REQUIRED TaskContract.
4. Revoke that exact decision through aptsGSS.
5. Confirm the aptsGSS outbox delivers `AUTHORIZATION_REVOKED`.
6. Confirm only TaskContracts with that `policy_decision_id` receive revocation metadata.
7. Confirm a COMMITTED bound task becomes `BLOCKED_REVOKED` and never emits
   `TASK_DISPATCHED`.
8. Confirm a TaskContract bound to another decision remains unchanged.
9. Confirm `cti_policy_decision_revocations.verification_status` is
   `VERIFIED_REVOKED` (or a documented fail-closed value during an authority outage).
10. Confirm mission-wide cancellation occurs only for explicit global emergency-stop,
    not for an ordinary decision-scoped revocation.
