# Patch Notes — Stage 4.7 HOTFIX1

## Scope

**Regression-harness stability only.** No Pentest Subsystem runtime, capability registry,
tool contract, lifecycle, governance, authorization, execution, or target-actuation semantics
are changed.

## Trigger

Windows deployment-host acceptance passed:

- Stage 4.7 runtime activation;
- canonical registry persistence;
- capability contract completeness;
- logical/non-callable tool boundaries;
- exploitation controlled-execution deferral;
- execution-intake fail-closed preflight;
- 27 focused Stage 4.7 tests;
- 149 Stage 4.1 → 4.7 regression tests.

The subsequent critical predecessor regression failed only in historical Stage 4.3 loopback
HTTP test `test_17_http_stage43_health_contract_create_get_list_and_execution_negative_boundary`
with:

`ConnectionAbortedError: [WinError 10053]`

This occurred before an HTTP status was received from a short-lived localhost
`ThreadingHTTPServer` instance. It is therefore a transport-level Windows loopback abort, not
a change to the Stage 4.3 or Stage 4.7 fail-closed contract.

## Change

Added `tests/_localhost_http.py` with `urlopen_local_with_retry()`.

The helper retries **only** transient localhost transport failures:

- `ConnectionAbortedError`;
- `ConnectionResetError`;
- `RemoteDisconnected`.

It deliberately **does not retry `HTTPError`**. Therefore negative-boundary assertions remain
authoritative: HTTP 409 is still required and is never converted into a success path.

Historical Stage 4.1–4.5 loopback regression tests now use this narrow transport helper for
local HTTP calls. Stage 4.6 and Stage 4.7 already had equivalent narrow retry behavior.

## Security / authority invariants preserved

- `POST /api/execution/dispatches` remains fail-closed.
- Stage 4.7 remains registry + tool-contract only.
- No capability selection is enabled.
- No logical tool becomes callable.
- No binary, shell, credential, raw target access, network actuation, or execution path is added.
- Exploitation remains deferred to governed Stage 6 controlled execution.

## Validation in patch environment

- Stage 4.1 → 4.7 regression: **149 passed**.
- Critical Stage 3 + Stage 4 predecessor regression: **208 passed**.
- Previously failing Stage 4.3 HTTP test repeated: **5/5 passed**.
- Canonical inventory remains **1724 tests**.

The full 1724-test historical suite remains the deployment-host final acceptance authority via
`STAGE4_7_ACCEPTANCE.ps1`.
