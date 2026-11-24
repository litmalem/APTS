# Patch Notes — Stage 4.6 HOTFIX1

## Scope

**Regression-harness stability only.** No runtime, contract, repository, lifecycle, event,
workflow, governance, authorization, capability, tool, or execution semantics are changed.

## Trigger

On Windows deployment-host acceptance, the Stage 4.1→4.6 combined regression could
intermittently fail in:

`test_23_http_execution_dispatch_remains_fail_closed`

with a local transport exception such as:

`ConnectionAbortedError: [WinError 10053]`

The same acceptance run had already proved the live Stage-4.6 execution-intake boundary with
HTTP 409, and the focused Stage-4.6 suite passed. This isolates the failure to short-lived
localhost HTTP test-server transport churn rather than the Stage-4.6 fail-closed contract.

## Change

`tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py`

adds `_urlopen_local_with_retry()` for localhost-only test transport. It retries up to three
times only for transient connection abort/reset/disconnect errors.

It deliberately **does not retry `HTTPError`**. Therefore the authoritative semantic assertion
remains unchanged:

- `POST /api/execution/dispatches` must return HTTP 409;
- `error_code` must be `STAGE4_6_EXECUTION_INTAKE_NOT_ENABLED`;
- no execution/tool invocation/target actuation may occur.

The normal `_post_json()` helper also uses the same transport retry, reducing Windows-only
flakiness for the Stage-4.6 loopback test server without weakening HTTP contract assertions.

## Validation in patch environment

- Focused Stage 4.6: **26 passed**
- Stage 4.1 → 4.6 regression: **122 passed**
- Critical Stage 3 + Stage 4 predecessor regression: **181 passed**
- Repeated isolated `test_23`: **5/5 passed**

The canonical test inventory remains **1697** because no test is added or removed.

## Authority boundary

Stage 4.6 remains a non-executing orchestrator skeleton. Full reasoning/replanning,
capability selection, tool execution, external network I/O, and target actuation remain
disabled.
