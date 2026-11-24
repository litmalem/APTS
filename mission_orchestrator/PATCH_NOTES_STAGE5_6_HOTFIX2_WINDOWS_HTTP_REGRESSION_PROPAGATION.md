# PATCH NOTES — Stage 5.6 HOTFIX2

## Windows HTTP Regression Propagation

### Trigger

After HOTFIX1 verification passed, `STAGE5_6_ACCEPTANCE.ps1` failed in qualification with two transient Windows loopback aborts:

- `test_stage5_2_reconnaissance_agent.py::test_21_http_execution_dispatch_remains_rejected_for_stage52`
- `test_stage5_5_attack_path_planning_agent.py::test_24_http_execution_dispatch_remains_rejected_for_stage55`

Both failed with `ConnectionAbortedError: [WinError 10053]` before the expected HTTP 409 response could be consumed.

### Root cause

HOTFIX1 used `tests._localhost_http.urlopen_local_with_retry` only in Stage 4.10 and Stage 5.6 tests. Historical Stage 5.1–5.5 modules still called `urllib.request.urlopen` directly against rapidly created/destroyed localhost `ThreadingHTTPServer` instances.

### Change

Propagate the existing transport-only helper to all Stage 5.1–5.5 `_get()` and `_post()` test clients.

### Security / semantic invariant

No production runtime or execution behavior changes. `HTTPError` remains non-retryable, so the expected fail-closed `409` response stays authoritative.

### Validation

- failing pair: 2 passed
- Stage 5.2 + 5.5: 52 passed
- Stage 5.1 + 5.3 + 5.4: 78 passed
- Stage 5.6: 28 passed
- Stage 5.1–5.5 collected: 130 tests
