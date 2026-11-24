# Post-Exploitation & Impact: P2

P2 uses `bounded-impact-rules-v3` and retains the additive
`apts-impact-assessment-v2` contract. No execution permissions are expanded.

## Evidence per claim

Each signal/target/hypothesis claim includes the source execution and path IDs
and SHA-256 values, JSON pointer, observation interval, verdict, explanatory note
and matching stored probe details. Current conflicts are distinguished from
changes between historical observations. Historical changes can reflect a real
target change and are not automatically treated as simultaneous contradictions.
Current contradictory observations escalate for review. Stale, blocked and
unsupported signals are explicitly labelled and cannot raise the business
review priority as usable observed signals.

These claims remain derived technical observations. They do not assert access,
privilege, compromise, data loss or service interruption. Missing probe details
are disclosed. Source timestamps come from the persisted execution run, not the
time the page is refreshed.

## Asset and service context

The UI saves operator declarations in versioned `pentest_impact_contexts` rows.
Each revision is bound to the verified task hash, mission, target and previous
revision hash. Updates use `expected_context_id`; concurrent edits require a
refresh. Repeating identical context does not create another version. Context
can also come from `objective.business_context` on the bound task when no UI
declaration exists.

Supported fields:

| Field | Meaning |
| --- | --- |
| service_name | Declared business service name, up to 200 characters |
| business_criticality | UNSPECIFIED / LOW / MEDIUM / HIGH / CRITICAL |
| data_sensitivity | Same levels |
| availability_criticality | Same levels |
| dependencies | Up to 30 unique `{service_name, criticality}` declarations |

Contextual exposure is the highest declared level among the asset dimensions
and dependent services. This is a transparent prioritization rule, not a
probability or measured loss. With no usable observed signal, the review priority
is VALIDATION_REQUIRED. Potential confidentiality, availability and service
consequences each state which additional evidence would be needed. Actual
business impact and impact on dependencies remain unconfirmed.

## Durable coordination

After a controlled execution record commits, new execution results and cached
execution replays call the impact bridge. The Impact workspace GET remains
read-only. The UI also provides an explicit publish/retry action for existing
results and revised business context.

Assessment and outbox event are committed together to
`pentest_impact_assessments` and `pentest_impact_outbox`. They are hash sealed and
deduplicated by assessment identity. Assessment identity binds policy, source
evidence, objective, context, claims and previous execution references.

The bridge refreshes the repository-derived Stage 5.8 shared state, records
feedback against the latest state and existing evidence index, then creates a
local coordination decision. Shared state keeps execution impact separate from
Stage 5 validated facts. Feedback binds the assessment and execution hashes.

| Impact recommendation | Stage 5.8 feedback | Coordination result |
| --- | --- | --- |
| STOP | NO_REPLAN_REQUIRED | NO_CHANGE |
| REPLAN | INSUFFICIENT_EVIDENCE for impact_analysis | DEFER_TO_STAGE6 |
| ESCALATE | IMPACT_REVIEW_REQUIRED | ESCALATE_GOVERNANCE |

IMPACT_REVIEW_REQUIRED is orchestrator-only and does not falsely assert that
scope or rules of engagement changed. It requests governance review; it cannot
grant approval. Stage 5.8 decisions remain projections: active plans are not
mutated and specialists/probes are not replayed automatically.
Impact-delivery feedback is excluded from automatic symbolic planner input;
otherwise its new receipt IDs would create a new snapshot and repeat execution
on every poll. Accepted planning feedback still uses the existing planner path.

Delivery status and receipts are visible in the UI and audit JSON. Receipt
integrity is verified on reads. Interrupted delivery stays PENDING and can be
retried after restart via cached execution replay or the publish button.
Deterministic feedback and replan identities prevent duplicate effects within a
shared-state version. A changed shared state receives a new bound delivery
attempt. Processed events are replayed from their receipt. Pending events whose
assessment inputs or plan changed are marked SUPERSEDED rather than applied to
the new state. There is no separate background retry daemon.

## UI API

- `GET /api/pentest/ui/post-exploitation-impact/workspace?limit=100`: derived
  assessments, context, claims and delivery status; no impact writes.
- `POST /api/pentest/ui/post-exploitation-impact/context`: exact fields
  `pentest_task_id`, `business_context`, `expected_context_id`.
- `POST /api/pentest/ui/post-exploitation-impact/publish`: exact fields
  `execution_run_id`, `expected_assessment_id`. The server recomputes the
  assessment and rejects stale plans or changed assessments. Caller-supplied
  assessment contents are rejected.

POST routes enforce the existing same-origin UI policy. Restart the Pentest
service after upgrading Python modules and refresh the browser to load the new
UI and CSS asset route. Older stored Stage 5.7 results remain readable; the
extended contextual assessment is present on newly generated results.
