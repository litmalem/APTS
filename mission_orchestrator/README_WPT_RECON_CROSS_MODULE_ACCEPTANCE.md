# WPT to Recon cross-module acceptance

Run from the Mission repository root:

```powershell
python -m pytest -q tests\test_wpt_to_recon_cross_module_acceptance.py
```

The acceptance test exercises the Mission HTTP intake routes, Mission's
append-only WPT intake/result/outbox stores, sealed Stage 6 result validation,
and the real Recon receiver/repository. It covers bearer authentication, target rejection at the authority-source seam
(the test double binds the request to the task target), intake idempotency,
Stage 6-to-result binding,
parent/action/target binding at the Recon receiver, durable handoff status,
ACK failure followed by restart/retry, and replay without duplicate Recon runs.

The Stage 6 evidence ledger is a deterministic fixture. WPT profiles in this
package are still registered as `REGISTERED_NOT_EXECUTABLE`; the test therefore
proves the module contracts and handoff behavior without making network
requests. Passing this test does not claim that the production WPT Stage 6
adapter is enabled or that a real scan can yet be dispatched.

Adjacent negative contract tests remain in
`tests/test_stage6_wpt_governed_intake.py` and
`tests/test_stage5_2_recon_iteration.py`. Run them together with:

```powershell
python -m pytest -q tests\test_wpt_to_recon_cross_module_acceptance.py tests\test_stage6_wpt_governed_intake.py tests\test_stage5_2_recon_iteration.py
```


## Mission RUNNING -> Pentest task -> WPT intake

For plans containing a `*-pentest-orchestration` task, autonomous Mission
activation now remains in `PLANNING` until that exact planned task ID is present
as `pentest_tasks.upstream_task_id` for the same Mission. This preserves the
state required by the governed routing/delegation handoff worker; it does not
create a Pentest task, grant execution permission, or perform target I/O. A
missing task is retried by the existing worker after GSS delegation and Stage
4.3 inputs become valid. Set `APTS_REQUIRE_PENTEST_ORCHESTRATION_BEFORE_RUNNING=0`
only to restore the previous lifecycle behavior.

`APTS_AUTONOMOUS_WPT_INTAKE=1` now queues the exact immutable Recon URL in WPT
while Mission is `PLANNING`, `REPLANNING`, or `RUNNING`, as soon as a planned
Pentest orchestration task exists. WPT records this as `AWAITING_PENTEST_TASK`;
it is only a visible, idempotent prequeue and cannot start a scan. After the
normal Mission authority source confirms the Pentest task is `RUNNING` with one
active orchestration, Mission's governed v2 delivery promotes the same WPT row
to `AWAITING_STAGE6`. Stage 6 remains the only scan execution boundary.

The Mission/GSS policy must still explicitly authorize `TASK_DELEGATION /
delegate_planned_task` for `PENTEST:pentest.recon`, separately from the
target-specific `TARGET_RECON` permission. The prequeue does not add GSS
permissions. Revisions to a scope after route creation require routing/handoff
to be replayed against the new scope version.

For the outbound Mission -> WPT inbox, set `APTS_WPT_INBOX_URL` (default local example:
`http://127.0.0.1:8791`) and `APTS_WPT_INBOX_TOKEN`. Set the same random token
(32+ characters) as `WTP_CLIENT_TOKEN` in the WPT process. These are distinct
from `APTS_WTP_DISPATCH_URL` / `APTS_WTP_DISPATCH_TOKEN`, which serve the
opposite WPT -> Mission direction. Restart both processes after changing
variables and check WPT `/api/health` for `mission_inbox_configured: true`.
