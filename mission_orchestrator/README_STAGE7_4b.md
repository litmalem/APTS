# Stage 7.4b — browser transport (SPA_NAV)

**Status:** implemented · browser transport is injectable · additive
**Acceptance:** `python3 tests/test_stage7_4b_browser_transport.py` → 5/5 PASS

## What this adds
Some challenges (Web3 Sandbox, Admin Section) are frontend-detected: they solve only
when the Angular route loads the lazy module (no single HTTP call to replicate — the
module filename is build-hashed). Stage 7.4b lets the gateway actuate these via an
injected **browser transport**.

- `ActiveExploitationGateway(..., browser_transport=fn)`. For a `SPA_NAV` primitive the
  gateway runs the Stage 7.1 guard + session-precondition checks, calls the browser
  transport to navigate the route, then confirms the solve via the challenge oracle.
  No transport bound → `REQUIRES_BROWSER_TRANSPORT` (unchanged). A transport error →
  `BROWSER_TRANSPORT_ERROR` (fail-closed, no false solve).
- `browser_transport.py` — `SeleniumBrowserTransport` reference impl for the host
  (`pip install selenium` + Chrome/Chromedriver): loads the app origin, injects the
  broker JWT into localStorage when provided (so `/#/administration` renders), then
  navigates the route.

## Verified (hermetic)
Web3 solves via the browser transport; Admin requires an admin session
(`NEEDS_ADMIN_SESSION` otherwise); loopback guard holds for SPA too.

## Live note
- **Web3 Sandbox:** `python run_cae_live.py --browser` (host, with Selenium).
- **Admin Section:** also needs an admin session — depends on a separate privilege-
  escalation primitive (SQLi login / JWT forge / mass-assignment), not yet built.
