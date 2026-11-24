# Stage 3.7.10 — Adapt/Replan Acceptance / Regression Gate

Stage 3.7.10 closes the Stage-3.7 adaptation/replanning lifecycle by adding an **external acceptance declaration and regression gate**, not a new operational replanning primitive. The runtime exposes the closure contract, while the target-host acceptance harness is the authoritative PASS/FAIL mechanism.

## Runtime identity

- `control_version`: `stage3.7.10-adapt-replan-acceptance-regression-gate`
- HTTP `server_version`: `APTSMissionOrchestrator/3.7.10`
- repository migration level: `53` (unchanged)
- new database migration: **none**
- new durable store: **none**
- closure schema: `apts-mission-stage3.7-adapt-replan-acceptance-gate-v1`
- closure mode: `FULL_REGRESSION_PLUS_CANONICAL_ADAPT_REPLAN_INTEGRATION_AND_LIVE_BOUNDARY_PROBES`
- baseline: `STAGE_3_7_1_THROUGH_3_7_9`
- runtime-change mode: `NO_NEW_ADAPT_REPLAN_AUTHORITY_RUNTIME_IO_PLAN_MUTATION_OR_TARGET_ACTUATION`

## Stage-3.7 chain being closed

The gate verifies the complete ordered control chain:

1. **3.7.1** — Canonical Adaptation/Replan Contract & Identity
2. **3.7.2** — Adaptation Trigger Detection & Classification
3. **3.7.3** — Replan Eligibility & Governance Gate
4. **3.7.4** — Canonical Replan Snapshot & Context Binding
5. **3.7.5** — Deterministic Replan Candidate Generation
6. **3.7.6** — Replan Candidate Validation & Delta Feasibility Gate
7. **3.7.7** — Authoritative Replan Commit Authorization & Successor Plan Materialization
8. **3.7.8** — Atomic Replan Commit, Supersession & Handoff
9. **3.7.9** — Adapt/Replan Lineage, Replay & Recovery
10. **3.7.10** — Adapt/Replan Acceptance / Regression Gate

Operationally, this is the closed trajectory:

`detect -> classify -> eligibility/governance -> snapshot -> deterministic candidate -> validate -> authoritative commit -> atomic supersession/handoff -> lineage/replay/recovery -> acceptance`

## Authority separation preserved

Stage 3.7.10 deliberately does **not** absorb authority from prior stages:

- Stage 3.7.1 materializes the canonical adaptation/replan episode; it does not classify or plan.
- Stage 3.7.2 classifies the trigger; it does not decide eligibility, invoke the planner, or supersede a Plan.
- Stage 3.7.3 performs fail-closed eligibility and external Governance authorization.
- Stage 3.7.4 binds the canonical durable planning context without external refresh.
- Stage 3.7.5 performs deterministic local candidate generation; it does not create the successor Plan.
- Stage 3.7.6 validates delta feasibility; it still does not create or supersede the successor Plan.
- **Stage 3.7.7 remains the authoritative successor-Plan commit/materialization control**, including Governance revalidation and active-head CAS.
- **Stage 3.7.8 remains the handoff authority**, proving the predecessor/successor supersession and declaring `HANDOFF_READY`.
- **Stage 3.7.9 remains read-only replay and durable recovery reconstruction**; it does not rerun planning, re-query Governance/runtime controls, redispatch, mutate the active Plan head, or actuate a target.
- **Stage 3.7.10 is declaration/acceptance only** and cannot self-certify PASS.

## Closure contract

`mission_orchestrator/adapt_replan_acceptance_gate.py` declares 17 mandatory gates covering compilation, exact test inventory, full regression, health/authority boundaries, all Stage-3.7 functional controls, end-to-end trajectory integration, restart reconstruction, repository/event integrity, and the final no-new-authority/no-I/O/no-mutation/no-actuation boundary.

The contract explicitly declares:

- `declared_only = True`
- `runtime_self_certification = False`
- `external_acceptance_execution_required = True`
- expected repository migration level `53`
- no new Stage-3.7 operational authority
- no new Governance/runtime/external-network/cancellation I/O
- no new routing/delegation/dispatch/execution attempt
- no new Mission lifecycle transition
- no new historical Plan mutation or active-head CAS
- no new target dispatch or target actuation
- no new LLM reinterpretation
- no new durable store or database migration

## Verification inventory

Build-workspace evidence for this implementation:

- Python compilation: PASS
- canonical collection: **1356 tests**
- Stage-3.7 collection: **200 tests**
- focused Stage 3.7.10 suite: **12/12 PASS**
- Stage 3.7.1–3.7.9 focused suites: **188/188 PASS when executed individually**
- Stage 3.7.1–3.7.10 focused total: **200 tests**
- historical closure suites Stage 3.4.10, 3.5.10, and 3.6.10: **12/12 PASS each** in the build workspace

A final full 1356-test regression PASS is **not claimed from the build sandbox**. The external target-host harness performs that authoritative run.

## Acceptance harness

After overlaying this package and restarting the runtime on the target host:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_7_10_ACCEPTANCE.ps1
```

The harness requires the active runtime to report Stage 3.7.10, migration level 53, the exact closure contract, and the complete Stage-3.7 control tail. It then performs Python compilation, exact 1356-test collection, full Stage 3.1–3.7.10 regression, exact 200-test Stage-3.7 chain regression, focused 3.7.10 and 3.7.9 proofs, source/migration/version checks, the Stage-3.7 authority matrix, and the final no-new-authority/no-I/O/no-mutation/no-actuation proof.

## Definition of closure

Stage 3.7 is formally closed only when the target-host harness ends with:

```text
STAGE 3.7.10 ACCEPTANCE: PASS
```

The runtime declaration by itself is not acceptance evidence.
