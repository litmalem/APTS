# Stage 7 — Admin escalation primitive (`escalate-admin-sqli`)

**Status:** implemented · additive
**Acceptance:** `python3 tests/test_stage7_4c_admin_escalation.py` → 4/4 PASS

## What this adds
`escalate-admin-sqli` — a SQL-injection login primitive that posts
`{"email":"' OR 1=1--","password":"x"}` to `/rest/user/login` and obtains the first
user (admin) JWT. **Live-verified 20 Nov 2026:** returns `admin@juice-sh.op`,
`role: admin`, and solves **Login Admin** as a side effect.

- **Broker:** `authenticate_sqli(target)` — guarded by Stage 7.1, requires RoE
  `allowed_auth_modes` to include `SQLI_LOGIN_LAB_ONLY`; produces an **admin session**
  (`session:authenticated` + `session:admin`), never storing the payload as a credential.
- **Gateway:** recognises `escalate-admin-sqli`, runs the SQLi login, confirms the
  Login Admin solve via the oracle, and hands the admin session to downstream steps.
- **Rewired enablers:** Admin Section and Five-Star Feedback now chain from
  `escalate-admin-sqli` (the real admin path), not the fake self-registered admin:
  - `adminSectionChallenge` → `escalate-admin-sqli → forced-browse-admin` (SPA via 7.4b browser transport)
  - `feedbackChallenge` → `escalate-admin-sqli → destroy-5star-feedback` (DESTRUCTIVE, double-approval)

## Runner
`python run_cae_live.py --browser` now also attempts Admin Section (SQLi admin →
localStorage token injection → navigate `/#/administration`). Five-Star Feedback is
not auto-run (it must delete *all* 5-star feedback — enumerate-and-delete, future).

## Note
This is the documented OWASP Juice Shop "Login Admin" technique on an intentionally
vulnerable lab target, loopback-only and RoE-gated — an enabler for the admin-scoped
BAC challenges, not a general-purpose attack tool.
