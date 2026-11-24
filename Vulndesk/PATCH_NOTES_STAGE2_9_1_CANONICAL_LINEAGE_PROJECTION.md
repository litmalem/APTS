# VulnDesk Stage 2.9.1 — Canonical Lineage Projection Model

## Baseline analyzed

- VulnDesk baseline: `hybrid-event-driven-2.11-cross-subsystem-lineage`.
- Stage 2.8 already persists the first-class lineage keys required by a canonical read model:
  `trace_id`, `causation_event_id`, `upstream_event_id`, `proposal_id`, `task_id`,
  `policy_decision_id`, `authorization_request_id`, and `revalidation_id`.
- Stage 2.8.7 already materializes decision/audit lineage.
- Stage 2.8.8 already persists authoritative external `gevent-*` references from aptsGSS.
- The uploaded `vvulndesk.sql` baseline contains all required columns and indexes.

Therefore **Stage 2.9.1 requires no database migration and no aptsGSS source change**.

## New control version

`hybrid-event-driven-2.12-canonical-lineage-projection`

## Implementation

New module:

`cti_services/lineage_projection.py`

The module provides a deterministic, read-only projection over four local lineage sources:

1. `cti_task_contracts` — durable TaskContract/business/governance binding snapshot.
2. `cti_events` — task lifecycle and causal event chain.
3. `cti_decision_traces` — decision materialization for the same task lineage.
4. `cti_audit_log` — decision-to-event audit bridge.

No source row is updated or repaired by the projector.

## Canonical projection schema

Schema identifier:

`cti-lineage-projection-v1`

Scope in 2.9.1:

`TASK`

Top-level projection:

- `identity`
  - `mission_id`
  - `task_id`
  - `trace_id`
  - `proposal_id`
- `task_contract`
- `governance_binding`
- `lifecycle`
- `events[]`
- `causal_edges[]`
- `upstream_edges[]`
- `decision_traces[]`
- `audit_records[]`
- `projection_metadata`

## Authority boundary

The projection never creates or reinterprets authority.

- aptsGSS / `GOV-PLANE` remains authoritative for PolicyDecision.
- Governance identifiers are projected only as external references.
- `correlation_status` is explicitly `NOT_EVALUATED_STAGE_2_9_4`.
- Internal `NOT_REQUIRED_INTERNAL` tasks retain null Governance identities.
- Stage 2.9.4 will perform cross-subsystem verification against aptsGSS.

## Causality boundary

2.9.1 preserves causal structure without deciding whether it is valid.

A causal edge contains:

- `cause_event_id`
- `effect_event_id`
- `cause_in_projection`

An unresolved parent is preserved as `cause_in_projection=false`; it is **not** classified as a violation in 2.9.1. Integrity/violation classification belongs to Stage 2.9.5.

## Historical compatibility

First preference is first-class `task_id` lineage.

A restricted fallback is supported for historical rows:

- events: same `mission_id` + `trace_id`, only when the event itself has no `task_id`;
- decision traces: same `mission_id` + `lineage_trace_id`, only when the trace itself has no `task_id`.

The projector never relabels those historical rows with a synthetic task identity.

Projection quality is exposed as:

- `CANONICAL_V2`
- `HISTORICAL_FALLBACK`
- `PARTIAL_NO_EVENTS`

## Orchestrator integration

`CtiSubsystemOrchestrator.project_task_lineage(task_id)` delegates to the canonical projector.

This is intentionally a service-level interface only. **No new HTTP lineage endpoint is added in Stage 2.9.1.** The HTTP Task Lineage Probe belongs to Stage 2.9.2.

## Health boundary

Only the existing `control_version` changes through the current `/health` response.
No lineage diagnostics block is added yet; detailed health/diagnostics belongs to Stage 2.9.6.

## Files changed

- `cti_services/lineage_projection.py` — new
- `cti_services/cti_subsystem_orchestrator.py`
- `cti_services/__init__.py`
- `tests/test_canonical_lineage_projection_stage2_9_1.py` — new
- `STAGE2_9_1_ACCEPTANCE.sql` — new
- `BUILD_VALIDATION_STAGE2_9_1.txt` — new

## Validation

- Focused Stage 2.9.1: `6 passed`
- Combined Stage 2.6 → 2.9.1 lineage/governance/runtime regression: `60 passed`
- Broad regression excluding the pre-existing `test_nvd_bulk_upsert.py`: `93 passed`
- Full-suite collection in the build container is blocked only because `pymysql` is not installed there. This is the same environment limitation documented in previous builds; `requirements.txt` already declares `PyMySQL>=1.1`.
- Uploaded `vvulndesk.sql` schema check: all Stage 2.9.1 required tables/columns present.

## Closure criterion for 2.9.1

Stage 2.9.1 can be closed after local runtime validation confirms that a fresh TaskContract can be projected through `CanonicalLineageProjector.project_task()` and the acceptance SQL returns the expected TaskContract/event/decision/audit rows.

Stage 2.9.2 should consume this projection directly and must not duplicate lineage reconstruction logic in the HTTP handler.
