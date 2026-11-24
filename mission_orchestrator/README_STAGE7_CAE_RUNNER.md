# Stage 7 CAE — live host runner

**Run on the Windows host** (the dev VM cannot reach loopback Juice Shop), with the
stack up and Juice Shop on `http://127.0.0.1:3000`.

```powershell
Set-Location D:\APTS\mission_orchestrator
python run_cae_live.py                      # read-active solves (safe, proven)
python run_cae_live.py --include-mutations  # also attempt state-mutation challenges
python run_cae_live.py --challenges basketAccessChallenge easterEggLevelOneChallenge
```
or `./START_STAGE7_CAE_LIVE.ps1`.

## What it does
Drives the Stage 7 CAE gateway (`LoopbackHttpTransport` + real `GET /api/Challenges`
oracle) against the live app, auto-approving mutation/destructive steps (the runner
stands in for the Human Layer :8802 in the lab). Prints per-step outcomes and the
scoreboard delta. Every step is RoE-guarded and loopback-only.

## Coverage (live-verified 20 Nov 2026)
Runner solves 5 Broken Access Control challenges end-to-end via the CAE gateway
(dynamic inputs resolved by read-only `prepare` probes):

| Challenge | Verified vector | Class |
|---|---|---|
| View Basket | `GET /rest/basket/{id != own bid}` | read-active |
| Easter Egg | `GET /ftp/eastere.gg%2500.md` (poison null-byte) | read-active |
| Forged Review | `PATCH /rest/products/reviews {id, message}` (edit any review) | mutation |
| Forged Feedback | `POST /api/Feedbacks {UserId:1, captchaId, captcha}` (captcha leaks answer) | mutation |
| Product Tampering | `PUT /api/Products/{O-Saft id} {description w/ owasp.slack.com href}` | mutation |
| Manipulate Basket | `POST /api/BasketItems` raw-body HPP: duplicate `BasketId` (own first, target second) | mutation |

**Not covered here:**
- `web3SandboxChallenge`, `adminSectionChallenge` — SPA_NAV (frontend-detected) → need
  Stage 7.4b browser transport; Admin also needs an admin session (separate escalation).
- `ssrfChallenge`, `csrfChallenge`, `feedbackChallenge` (Five-Star, admin + DELETE) —
  need SSRF target / cross-origin / admin escalation respectively.

## Why a separate runner (not the :8790 service)
The Stage 7 CAE modules are additive and NOT yet wired into the running pentest
service, which still runs the base non-exploiting pipeline (recon -> hypothesis ->
plan). This runner is how you exercise the CAE engine end-to-end against the live app
today; wiring it into the runtime as a governed capability is a later integration step.
