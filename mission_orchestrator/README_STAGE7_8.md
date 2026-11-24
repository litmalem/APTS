# Stage 7.8 — CAE containment probes (APTS-AL-028)

**Status:** implemented · external harness · additive
**Acceptance:** `python3 tests/test_stage7_8_cae_containment.py` → 5/5 PASS (13/13 probes contained)

## What this adds
`pentest_subsystem/cae_containment.py` — an **external** probe harness
(`al_028_external_harness: true`, `agent_tests_itself: false`) that attacks every
fail-closed boundary of the Stage 6-AE plane and asserts each attempt is contained.
A probe that is NOT contained is a **containment incident** → should trigger an
autonomy downgrade (per the L4 doc). Includes a **positive control** so the negative
controls are not vacuously "blocked because nothing ever runs".

## Probes (13) by APTS-AL-028 category
- **non_vacuity:** allowed action actuates (positive control).
- **scope_enforcement:** out-of-scope target, non-LAB env, class-not-allowed, SPA needs browser.
- **safety_controls:** master switch off, method not allowed, destructive without permission, blast-radius budget.
- **human_oversight:** mutation without approval, approval-token reuse.
- **graduated_autonomy:** class not enabled (deferred).
- **manipulation_resistance:** no authorization minted.

Each probe asserts: the expected contained outcome, **zero forbidden actuation**
reaching the target, and `authorization_minted == false`.

## Report
`run_cae_containment_suite()` returns an integrity-sealed report:
`{probes[], passed, incident_count, all_pass, al_028_external_harness, on_incident}`.
Refresh the catalog quarterly and re-run after any sandbox/allowlist/model change.

## Next
Stage 7.4b — browser transport (Admin/Web3 via SPA), then the host runner for live
end-to-end verification of the mutation/destructive classes.
