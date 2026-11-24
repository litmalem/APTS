# Stage 7.4 — Stage 6-AE gateway (read-active active-exploitation)

**Status:** implemented · ACTUATES (read-active class only) · transport-agnostic · additive
**Acceptance:** `python3 tests/test_stage7_4_active_exploitation_gateway.py` → 8/8 PASS

## What this adds
`pentest_subsystem/active_exploitation_execution.py` — the first component that
actuates. `ActiveExploitationGateway.run_chain(...)` binds Stage 7.3 broker
sessions + Stage 7.2 primitives and, per step: guards (Stage 7.1), actuates via an
injected loopback transport, and confirms solves via `ChallengeOracle`
(GET /api/Challenges `solved` delta).

- **Only `CONTROLLED_ACTIVE_EXPLOITATION` actuates here**; STATE_MUTATION → DEFERRED 7.6,
  DESTRUCTIVE → DEFERRED 7.7.
- **Solves (hermetic harness):** View Basket (IDOR), Admin Section, Web3 Sandbox, Easter Egg.
- **Controls:** loopback-only, RoE blast-radius request budget (counted transport halts),
  kill switch (`halt()`), session-precondition checks, no authorization minting.
- **Evidence:** integrity-sealed run record; steps store `request_sha256`/`response_sha256`,
  never raw victim bodies.

## Why hermetic
The test VM cannot reach `127.0.0.1:3000`; a fake Juice Shop backs both transport and
oracle. Live actuation runs on the Windows host via `session_broker.LoopbackHttpTransport`
+ a real `GET /api/Challenges` fetcher, driven from the Control Center.

## Live-verified trigger (20 Nov 2026, real Juice Shop)
`basketAccessChallenge` (View Basket) solved live via the browser against
`http://127.0.0.1:3000`:
```
POST /api/Users        -> 201   (throwaway LAB account)
POST /rest/user/login  -> 200   (token; own basket bid=6)
GET  /rest/basket/1    -> 200   (basket of UserId 1, not ours)  => SOLVED
```
Confirms the `auth-lab-user -> idor-read-basket` chain and the `GET /rest/basket/{id}`
primitive. Fix landed: the broker now captures `bid` from login, and the gateway
auto-derives a non-own basket id when no explicit `id` parameter is given.

## Next
Stage 7.5 — governance approval queue (Human Layer 8802) + single-use approval tokens +
emergency-stop, before enabling STATE_MUTATION in 7.6.

## Live results — 20 Nov 2026 (real Juice Shop, loopback)
Driven against `http://127.0.0.1:3000`; confirmed via `GET /api/Challenges` delta.

| Target | Result | Verified trigger | Delivery |
|---|---|---|---|
| View Basket (87) | ✅ SOLVED | `GET /rest/basket/{id≠own bid}` + auth | HTTP |
| Easter Egg (23) | ✅ SOLVED | `GET /ftp/eastere.gg%2500.md` (poison null-byte) | HTTP |
| Web3 Sandbox (12) | ✅ SOLVED | SPA navigation to `/#/web3-sandbox` | SPA_NAV |
| Admin Section (5) | ⬜ open | needs an **admin session** (separate escalation) + SPA | SPA_NAV |

Side effect: the Easter Egg null-byte request also solved **Poison Null Byte** (105).

### Key finding (for the dissertation)
Juice Shop solve-detection is NOT uniform. Two delivery classes emerged:
- **HTTP** — server-side `solveIf` in an API handler; the HTTP gateway solves these.
- **SPA_NAV** — detected only when the Angular route loads; a backend GET does NOT
  trigger it. These need a browser-driven primitive.

The HTTP gateway now tags SPA_NAV steps `REQUIRES_BROWSER_TRANSPORT` (fail-closed,
no false solve) and defers them to Stage 7.4b.

## Stage 7.4b (design) — browser-driven primitive
Add a `delivery: "SPA_NAV"` branch to the gateway backed by an injected **browser
transport** (built-in browser / Chrome automation) instead of raw HTTP:
- same RoE guard, loopback allowlist, blast-radius, kill switch, and challenge oracle;
- actuation = navigate the Angular route (optionally with the broker's JWT injected
  into `localStorage`/headers), wait for load, then re-snapshot the oracle;
- Admin Section additionally needs `session:admin`, which depends on a privilege-
  escalation primitive (SQLi login / JWT forge / mass-assignment) — a separate track.
