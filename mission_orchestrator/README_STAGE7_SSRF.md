# Stage 7 — SSRF (profile image URL)

**Status:** implemented · live-verified 21 Nov 2026 · additive
**Acceptance:** `python3 tests/test_stage7_ssrf.py` → 2/2 PASS

## Verified vector (live)
```
POST /profile/image/url     (Cookie: token=<jwt>, form-encoded)
Body: imageUrl=http://localhost:3000/solve/challenges/server-side?key=tRy_H4rd3r_n0thIng_iS_Imp0ssibl3
```
The server fetches the internal /solve URL (SSRF) → solves `ssrfChallenge`. Two
gotchas found live: (1) the server-rendered `/profile` path authenticates via a
**`token` cookie**, not the Bearer header; (2) the `imageUrl` value must be
form-URL-encoded. A Bearer-only attempt returns 500 and does not solve.

## Integration
- **Library:** `ssrf-profile-image` gets `auth_via_cookie: true`.
- **Gateway `_render`:** when a primitive sets `auth_via_cookie`, it adds
  `Cookie: token=<session jwt>` alongside the Authorization header.
- **Runner:** `STATIC_PARAMS["ssrfChallenge"]` carries the form-encoded internal URL
  as `raw_body` (content-type `application/x-www-form-urlencoded`). Gated as
  STATE_MUTATION (single approval).

Note: the earlier bridge drop happened on a Bearer-only SSRF POST that hung the
request; the cookie-authenticated form POST completes cleanly.
