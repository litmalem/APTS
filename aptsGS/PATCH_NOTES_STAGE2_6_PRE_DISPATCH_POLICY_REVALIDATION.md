# Stage 2.6 — Pre-dispatch PolicyDecision Revalidation

Baseline input: `hybrid-event-driven-2.3-pip-persistence-hardening`.

New VulnDesk control version:

`hybrid-event-driven-2.4-pre-dispatch-policy-revalidation`

## Objective

Close the time-of-check/time-of-use gap between TaskContract commit and the actual dispatch of an externally authorized task.

For `authorization_mode=REQUIRED`, a committed TaskContract is no longer sufficient by itself. CTI-A01 must ask the independent Governance & Safety Plane to revalidate the exact bound PolicyDecision immediately before `TASK_DISPATCHED`.

## Authority boundary

- aptsGSS/GOV-PLANE remains the only authorization authority.
- VulnDesk does not recompute policy rules locally.
- VulnDesk sends the exact TaskContract binding back to aptsGSS.
- Any transport/protocol/revalidation uncertainty blocks dispatch (fail closed).
- Internal reasoning tasks with `NOT_REQUIRED_INTERNAL` do not acquire external execution authority.

## Revalidated dimensions

The new aptsGSS endpoint checks:

- decision_id
- authorization request_id
- mission_id
- PolicyDecision hash
- decision value = ALLOW
- decision lifecycle status = ACTIVE
- valid_from / valid_until
- exact authorization request dimensions
- current ScopeContract existence/status/mission/version
- current source/target scope membership
- current action constraint
- current PolicySet existence/status/version/effective window
- global emergency-stop state

## New API

`POST /api/governance/authorization/revalidate`

The endpoint validates an existing decision; it does **not** issue a new PolicyDecision.

## New VulnDesk events

- `TASK_AUTHORIZATION_REVALIDATED`
- `TASK_DISPATCH_BLOCKED`

The positive ordering is:

`TaskContract COMMITTED -> TASK_AUTHORIZATION_REVALIDATED -> TASK_DISPATCHED`

The negative ordering is:

`TaskContract COMMITTED -> TASK_DISPATCH_BLOCKED -> mission fail-closed`

## Database migration

Run:

`sql_update_cti_harmonized/05_pre_dispatch_policydecision_revalidation.sql`

It adds auditable revalidation/dispatch evidence to `cti_task_contracts`.

## Important limitation

This stage minimizes the TOCTOU window but cannot make two independent services atomically transactional. The revalidation call is placed immediately before dispatch. Eliminating the remaining network-scale window would require a stronger lease/capability-token or distributed transaction design, which is intentionally outside Stage 2.6.
