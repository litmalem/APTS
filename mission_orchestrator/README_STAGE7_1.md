# Stage 7.1 — Controlled Active Exploitation (CAE) contract

**Status:** implemented · zero-I/O · additive (no Stage 4–6 contract mutated)
**Acceptance:** `python3 tests/test_stage7_1_active_exploit_contract.py` → 9/9 PASS

## What this adds
Foundation for the CAE research track (lets APTS eventually *solve* Juice Shop
challenges) **without** loosening the existing read-only Stage 6 validator.

- `pentest_subsystem/active_exploit_contract.py` (new, stdlib-only):
  - **Action-class vocabulary** (graded blast radius): `CONTROLLED_ACTIVE_EXPLOITATION`
    → `CONTROLLED_STATE_MUTATION` → `CONTROLLED_DESTRUCTIVE`.
  - **RoE extension schema** (`normalize_active_exploit_roe`) with fail-closed
    defaults: `active_exploitation_allowed`, `allowed_http_methods`,
    `allowed_auth_modes`, `payload_catalog_allowlist`, `credential_usage_allowed`,
    `destructive_actions_allowed`, `human_approval_required_for`,
    `target_allowlist`, `blast_radius`, `environment`.
  - **Capability spec** `active_exploitation` (safety_class `HIGH_RISK_ACTIVE`,
    autonomy_level 3, tool `pentest.tool.active_exploit_engine`), integrity-sealed.
  - **Fail-closed eligibility guard** `evaluate_active_exploitation_eligibility()`
    → `ELIGIBLE | REVIEW_REQUIRED | INELIGIBLE`, integrity-sealed, mints no
    authorization and performs no I/O.
- `tests/test_stage7_1_active_exploit_contract.py` (new): loads the module by path
  (bypasses the heavy package `__init__`), 9 assertions.

## Why additive (no edits to governance/boundary/capability contracts)
- `boundary_contract.normalize_pentest_boundary_payload` already accepts `roe`
  as a free-form object → new RoE fields need no boundary change.
- The existing Stage-4.8 `evaluate_scope_roe` already enforces action-class
  allow/prohibit, credential, destructive, and `human_approval_required_for`.
  CAE is a **composable** second guard the future Stage 6-AE gateway ANDs with it.
- Not mutating the frozen Stage-4.7 capability registry keeps every Stage 4–6
  contract hash (and its acceptance gates) stable. Wiring the capability into the
  main registry (version bump + hash cascade) is a deliberate later step.

## Guard semantics (fail-closed)
ELIGIBLE only if ALL: `environment=LAB` ∧ loopback target ∈ `target_allowlist` ∧
`active_exploitation_allowed=true` ∧ class allowed & not prohibited ∧ method in
`allowed_http_methods` and within the class family ∧ destructive⇒`destructive_actions_allowed`
∧ credential⇒`credential_usage_allowed`+auth mode ∧ positive `blast_radius` caps.
Classes in `human_approval_required_for` without an approval token → REVIEW_REQUIRED.

## Next
Stage 7.2 — exploit-primitive library with STRIPS `precondition/effect` (wires into
`symbolic_planner.py`, turning `VALIDATION_PRIORITISATION_ONLY` into real chains).
