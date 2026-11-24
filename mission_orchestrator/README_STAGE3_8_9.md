# Stage 3.8.9 — Forensic Query, Evidence Bundle & Reconstruction API

This stage adds three read-only Mission APIs over the Stage 3.8.7 verified diagnostics and the existing durable records. It does not add a repository table, migration, Governance authority, dispatch, execution, or automatic repair. Runtime control is `stage3.8.9-forensic-query-evidence-bundle-reconstruction-api`; repository migration remains **53**.

| API | Result |
| --- | --- |
| `GET /api/missions/{mission_id}/forensic-evidence-bundle` | Source-bound `MissionEvidenceBundle`: canonical Mission identity/envelope, state and transitions, planning, governance, routing/delegation, execution, outcome/evidence, and replanning records; event ledger, normalized events, causal graph, decision trace, timeline, live projection, and integrity findings. |
| `GET /api/missions/{mission_id}/forensic-reconstruction` | Verified event-ledger ordered timeline and graph, current state and state history, active plan, execution/outcome/replan records, and diagnostic findings. |
| `GET /api/missions/{mission_id}/forensic-query?scope=events&ref={id}` | Forensic slices by `events`, `tasks`, `execution`, `decisions`, `evidence`, `lineage`, or `integrity`. `ref` is optional and matches exact event, task, attempt, result, or task-key identifiers; unknown parameters and duplicate `scope` are rejected. |
| `GET /api/observability/forensic-contract` | Schema, status, authority, and persistence contract. |

The service verifies the canonical Mission envelope and event chain, recomputes normalized events from durable events, re-runs Stage 3.8.7 diagnostics, reconstructs the decision source bindings and live projection from the same record inventory, verifies result and evidence-binding contracts, and checks current state against its transition history. It reads the records and observability sources again to detect ordinary concurrent drift. A verified result has `bundle.status=VERIFIED`; a failure returns `WITHHELD` with a reason code and diagnostics while withholding records and reconstruction. A corrupt canonical envelope still fails closed; an unknown Mission returns 404. The APIs do not query the external Governance authority.

The bundle includes existing record payloads, so its readers need the same trusted access as other Mission record APIs. The SHA-256 digest binds the returned content but is **not** an external signature or independent checkpoint. Existing Stage 3.6.3 evidence binding verifies immutable references and manifest hashes; this stage does not fetch external evidence content or attest its authenticity. Repeated reads detect typical concurrent changes but do not create an atomic database snapshot. Removal of an internally consistent event tail cannot be proven without an independent checkpoint.

The ZIP is an overlay for the supplied Stage 3.8.8 source archive. It contains changed sources, the current-control regression rebasing, focused tests, this README, installation and acceptance scripts, and a SHA-256 manifest. It excludes deployment `data/`, credentials, caches, and migrations. Windows acceptance remains a separate host step after service restart.
