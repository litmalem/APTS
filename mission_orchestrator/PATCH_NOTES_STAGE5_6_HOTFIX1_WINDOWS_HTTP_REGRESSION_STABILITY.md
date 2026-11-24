# Patch Notes — Stage 5.6 HOTFIX1 — Windows HTTP Regression Stability

## Scope

**Regression-harness stability only.** No Stage 5.6 production runtime, contract, repository,
migration, orchestration, governance, exploitation-proposal, validation-task, execution,
evidence, or authorization semantics are changed.

## Trigger

The deployment-host `STAGE5_6_ACCEPTANCE.ps1` run completed all focused and predecessor
qualification gates successfully, then the 1957-test full historical regression reported two
Windows localhost transport failures:

- `tests/test_stage4_10_pentest_foundation_acceptance_gate.py::test_10_execution_intake_remains_fail_closed_at_stage410`
- `tests/test_stage5_6_exploitation_agent.py::test_24_http_execution_dispatch_is_rejected_by_stage56`

Both failed before an HTTP status could be read with:

`ConnectionAbortedError: [WinError 10053]`

The affected endpoint is the negative execution boundary:

`POST /api/execution/dispatches`

This endpoint must remain fail-closed with HTTP 409. The same acceptance run had already
proved the live Stage-5.6 controlled-execution boundary and all focused/critical suites passed,
so the failure is isolated to short-lived localhost `ThreadingHTTPServer` transport churn on
Windows rather than a Stage-5.6 semantic regression.

## Change

The existing shared helper `tests/_localhost_http.py` is reused by:

- `tests/test_stage4_10_pentest_foundation_acceptance_gate.py`
- `tests/test_stage5_6_exploitation_agent.py`

Their local `_get()` / `_post()` helpers now call `urlopen_local_with_retry()` instead of raw
`urllib.request.urlopen()`.

The retry helper is deliberately narrow:

- retries only `ConnectionAbortedError`, `ConnectionResetError`, and `RemoteDisconnected`;
- maximum three attempts;
- short increasing delay between attempts;
- **does not retry `HTTPError`**.

Therefore HTTP 409 remains an authoritative semantic failure response and cannot be converted
into a success path by the hotfix.

## Authority boundary preserved

Stage 5.6 remains proposal-only:

- no validation execution;
- no exploitation execution;
- no `ExecutionRequest` creation;
- no `ActionResult` creation;
- no target execution evidence creation;
- no confirmed finding creation;
- no direct tool invocation;
- no external target network I/O;
- no target actuation;
- no authorization minting.

Controlled execution remains Stage 6 authority.

## Validation in patch environment

- Stage 4.10 + Stage 5.6 test modules: **43 passed**.
- Previously failing pair: repeated successfully for **8 consecutive completed iterations** in the patch environment before the external command runner time limit stopped the repetition command; no semantic/test failure occurred.
- No test is added or removed; canonical inventory remains **1957**.

The deployment host must rerun `STAGE5_6_ACCEPTANCE.ps1`; its full historical regression
remains the final acceptance authority.
