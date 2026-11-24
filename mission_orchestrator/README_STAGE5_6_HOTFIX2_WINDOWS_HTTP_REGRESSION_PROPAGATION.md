# Stage 5.6 HOTFIX2 — Windows HTTP Regression Propagation

## Purpose

HOTFIX1 stabilized the Stage 4.10 and Stage 5.6 localhost HTTP clients, but final Stage 5.6 acceptance exposed the same Windows loopback transport failure in historical Stage 5 predecessor tests.

Observed failure class:

- `ConnectionAbortedError: [WinError 10053]`
- short-lived `ThreadingHTTPServer` on `127.0.0.1`
- contract under test remains `POST /api/execution/dispatches -> HTTP 409`

HOTFIX2 propagates the existing narrow localhost transport retry helper to Stage 5.1 through Stage 5.5 test HTTP clients.

## Scope

Modified regression harness only:

- `tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py`
- `tests/test_stage5_2_reconnaissance_agent.py`
- `tests/test_stage5_3_enumeration_agent.py`
- `tests/test_stage5_4_vulnerability_hypothesis_agent.py`
- `tests/test_stage5_5_attack_path_planning_agent.py`

The helper `tests/_localhost_http.py` is included in the patch for idempotent installation.

## Retry semantics

`urlopen_local_with_retry()` retries only transient localhost transport failures:

- `ConnectionAbortedError`
- `ConnectionResetError`
- `RemoteDisconnected`

`HTTPError` is re-raised immediately. Therefore fail-closed HTTP contract assertions such as `409 Conflict` are not retried, hidden, or converted to success.

## Authority and runtime boundaries unchanged

HOTFIX2 does not modify:

- Stage 5.6 runtime implementation;
- migration 13;
- Exploit Action Proposal;
- Validation Task;
- Scope/RoE or governance semantics;
- Stage 6 controlled-execution authority;
- target/network behavior;
- production HTTP server implementation.

## Local verification performed on patch workspace

- Previously failing Stage 5.2 + Stage 5.5 HTTP 409 pair: `2 passed`
- Full Stage 5.2 + Stage 5.5 modules: `52 passed`
- Full Stage 5.1 + Stage 5.3 + Stage 5.4 modules: `78 passed`
- Focused Stage 5.6: `28 passed`
- Patched Stage 5.1–5.5 inventory: `130 tests`

The authoritative final acceptance remains `STAGE5_6_ACCEPTANCE.ps1` on the Windows deployment, including the full 1957-test historical regression.

## Install

Overlay this patch at the repository root, then run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE5_6_HOTFIX2_VERIFY.ps1
.\STAGE5_6_ACCEPTANCE.ps1
```

Do not advance to Stage 5.7 until Stage 5.6 acceptance reports the full historical regression PASS.
