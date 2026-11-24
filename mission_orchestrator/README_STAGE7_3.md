# Stage 7.3 — LAB session broker

**Status:** implemented · transport-agnostic (no embedded network stack) · additive
**Acceptance:** `python3 tests/test_stage7_3_session_broker.py` → 9/9 PASS

## What this adds
`pentest_subsystem/session_broker.py` — owns session/credential *state and policy*
for Controlled Active Exploitation; actuation stays at the Stage 6-AE gateway (7.4).

- **`SessionBroker(roe, transport=...)`** — `provision_lab_credential(role)`,
  `authenticate(cred, target)`, `get_token`, `session_facts`, `session_evidence`,
  `revoke`, `teardown`.
- **Composes Stage 7.1**: `authenticate` runs `evaluate_active_exploitation_eligibility`
  (login = a `CONTROLLED_ACTIVE_EXPLOITATION` POST). INELIGIBLE → refused; a class in
  `human_approval_required_for` → needs an approval token.
- **Emits Stage 7.2 facts**: `session:authenticated` (+ `session:admin`) — exactly the
  predicates the exploit primitives REQUIRE, so a broker session unlocks the planned chain.
- **Transport-agnostic & fail-closed**: no transport bound → cannot authenticate.
  `LoopbackHttpTransport` (host-side) refuses any non-loopback host before any request.

## Safety properties (proven by tests)
- LAB throwaway accounts only (`aptslab+<rand>@lab.local`); never a real credential.
- Raw secrets are ephemeral: plaintext lives only in a transient pending buffer the
  `authenticate` call consumes and deletes. Session + audit records hold the token and
  `token_sha256`, never the password (`raw_secret_persisted: false`).
- Fail-closed on: no transport, `credential_usage_allowed=false`, non-loopback target.
- `teardown()` clears all sessions (no-persistence).

## Why hermetic tests
The VM running these tests cannot reach the user's `127.0.0.1:3000`; a fake transport
stands in for the gateway's HTTP. End-to-end auth against the live Juice Shop happens
at the Stage 6-AE gateway on the Windows host (7.4), using `LoopbackHttpTransport`.

## Next
Stage 7.4 — `active_exploitation_execution.py` (Stage 6-AE gateway): binds broker
sessions + exploit primitives, performs loopback-only actuation for read-active
challenges, and confirms solves via the challenge oracle.
