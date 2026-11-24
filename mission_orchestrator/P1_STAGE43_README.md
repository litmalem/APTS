# P1 — Stage 4.3 materialization from real CTI PIP

## Boundary
- Handoff/ownership is already in Pentest inbox, but is not execution authority.
- New request payload property `stage43_cti` accepts **only** `{pip_id, policy_decision_id}`.
- Mission downloads real CTI PIP using the configured CTI URL (default 127.0.0.1:8765).
- CTI PIP **must** have an exact mission & target binding, unmodified SHA-256,
  current all-pass hard gates, `ACTIONABLE` or `VALIDATION_READY` readiness,
  explicit confidence evidence, and be no older than one hour.
- One-hour expiry is a *local consumer policy*, not a CTI-issued expiration.
- A derived Pentest Stage-4.2 PIP carries the original CTI hash and a lossless
  copy of its intelligence. New SHA is a packaging hash, **not a source attestation**.
- GSS decision is retrieved by explicit `policy_decision_id` and must be existing
  `ALLOW` for `TARGET_RECON`, Pentest subject, exact URL, current scope; authoritative
  GSS revalidation occurs immediately before persistence.
- Existing recipient repository materializes Stage-4.3 task idempotently and
  ensures durable readback. No task is created on missing data or denial.
- Execution and target I/O remain disabled by this flow. Later runtime actions
  require their *own* governance authorization and sandbox control.

## Steps (Windows)

1. STOP Mission API before applying patch; copy data & scripts to backup.
2. Run `INSTALL_P1_STAGE43.ps1 -MissionRoot D:\mission_orchestrator -DryRun`.
3. Run installer without `-DryRun`, then restart Mission API and Pentest UI.
4. Run `CHECK_STAGE43_READINESS.ps1` to discover active Pentest handoff,
   CTI `latest_pip_id`, and existing GSS TARGET_RECON decisions.
5. If there is no existing TARGET_RECON decision, first configure and approve
   the proper LAB scope in GSS Human Layer, then request it explicitly using
   `REQUEST_STAGE43_TARGET_RECON_AUTH.ps1 -ScopeContractId <approved-scope-id>`.
   If GSS returns DENY or REVIEW, **stop**. Do not bypass policy.
6. Use the CTI `pip_id` and GSS **decision_id** with:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
cd D:\mission_orchestrator
.\RUN_STAGE43_CTI_MATERIALIZATION.ps1 `
  -PipId '<actual-cti-pip-id>' `
  -PolicyDecisionId '<actual-gss-allow-decision-id>'
```

7. Refresh `http://127.0.0.1:8790/pentest/`. Pentest task should appear
   under `pending_tasks`. Starting an orchestration is a separate user action.

## Fail-closed conditions
- PIP absent, rejected, PARTIAL, stale, lacking confidence evidence,
  hash mismatch, wrong mission/target, or wrong execution semantics.
- GSS decision absent, denied, wrong subject, wrong target, stale or not valid
  on authoritative revalidation.
- Multiple Mission targets (the bridge requires exactly one).
- Any mismatch between Mission and Pentest SQLite database paths.

## Compatibility
Legacy `stage43_inputs` (operator-supplied complete PIP and authorization reference)
remains supported for existing workflows. Supplying it together with `stage43_cti`
is rejected. No database migration and no live target invocation are added.

## Validation
Run `PYTHONPATH=. python -m pytest -q tests/test_p1_cti_stage43_materialization.py`.
Also run your normal full regression and integrated acceptance suites before
promotion to operational use.
