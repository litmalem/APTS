# Stage 2.9.8 Acceptance Criteria

## A. Mandatory preflight

- CTI `/health`: `status=ok`.
- `architecture_version=2026-08-harmonized`.
- `control_version=hybrid-event-driven-2.17-health-diagnostics` (atau version bump yang eksplisit dan benar).
- CTI deep diagnostics: `readiness_status=READY`, `mandatory_fail_count=0`.
- Governance health: healthy/ok.
- Governance deep diagnostics: `readiness_status=READY`, `mandatory_fail_count=0`.
- Governance outbox: `pending=0`, `failed=0`.

## B. Fresh governed mission

- ScopeContract terbentuk, `ACTIVE`, dan terikat pada `mission-stage298-e2e-*`.
- Mission start `accepted` dan canonical mission ID tidak berubah.
- Mission mencapai `COMPLETED` sebelum timeout.
- `last_error` kosong.
- `acquisition_actions=1`.
- `acquisition_sources` berisi `mitre-attack`.

## C. Canonical lineage and reconstruction

- Mission projection scope `MISSION`.
- `projection_metadata.quality=CANONICAL_V2`.
- `task_count > 0`.
- `causal_edge_count > 0`.
- Governed task lineage projection scope `TASK`.
- Governed task memiliki `TASK_COMMITTED`, authorization-revalidated event, dispatch event, dan terminal event.
- Revalidation harus ber-causation ke commit; dispatch harus ber-causation ke revalidation; terminal harus berada dalam causal chain.

## D. Governance binding and correlation

- Governed task `authorization_mode=REQUIRED`.
- `policy_decision_id` tersedia.
- `authorization_request_id` tersedia.
- `pre_dispatch_revalidation_status=VALID`.
- Governed task terikat ke ScopeContract E2E.
- Mission governance correlation `CORRELATED`.
- `governed_task_count >= 1`.
- `correlated_governed_task_count == governed_task_count`.
- `missing_required_reference_count=0`.
- `field_mismatch_count=0`.
- `missing_external_event_count=0`.
- `coverage_complete=true`.

## E. Integrity

- Mission integrity `PASS`.
- `verification_complete=true`.
- `violation_count=0`.
- `violated_task_count=0`.
- `unverifiable_task_count=0`.
- Setidaknya satu task memiliki `required_authority=true`.

## F. Diagnostics and outbox

- Mission diagnostics `HEALTHY`.
- `projection_quality=CANONICAL_V2`.
- `governance_correlation_status=CORRELATED`.
- `integrity_status=PASS` dan violation=0.
- `issues=[]`.
- Postflight outbox kembali `pending=0`, `failed=0`.
- CTI/Governance postflight tetap `READY` dan mandatory fail=0.

## G. Read-only probe invariant

Mission lineage, mission integrity, dan governed-task lineage dipanggil dua kali. Field waktu/generation duration tidak digunakan dalam fingerprint. Semantic fingerprint dari kedua pembacaan harus identik. Ini menutup acceptance bahwa probe tidak memutasi canonical evidence state.

## H. Stage 2.9.7

GUI bersifat opsional. `SKIP` pada check 2.9.7 bukan kegagalan dan tidak menghalangi closure 2.9.8.

## Final decision

`PASS` hanya jika `mandatory_fail_count=0`. Bukti final disimpan dalam `99_acceptance_summary.json`.
