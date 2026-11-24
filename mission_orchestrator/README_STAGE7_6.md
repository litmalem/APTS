# Stage 7.6 — CONTROLLED_STATE_MUTATION (approval-gated, reversible-first)

**Status:** implemented · opt-in actuation · additive
**Acceptance:** `python3 tests/test_stage7_6_state_mutation.py` → 6/6 PASS

## What this adds
The Stage 6-AE gateway now actuates `CONTROLLED_STATE_MUTATION` (POST/PUT/PATCH),
**opt-in** via `enable_classes` (default stays `{ACTIVE_EXPLOITATION}`, so Stage 7.4
behaviour and tests are unchanged — mutation is still DEFERRED unless explicitly enabled).

- **Approval-gated (Stage 7.5):** every mutation step is `REVIEW_REQUIRED` and actuates
  only after the ApprovalBroker consumes a matching single-use token. Reused/expired/
  wrong-binding token → `BLOCKED APPROVAL_INVALID`.
- **Request bodies:** `parameters[primitive_id]["body"]` is sent as JSON.
- **Reversible-first auto-rollback:** a reversible primitive declares a `rollback`
  (inverse request + `id_from`); after the solve is recorded the gateway issues the undo
  and records `rollback.status = ROLLED_BACK`. Rollback requests count against blast-radius.
- **Non-reversible flagged:** primitives marked `reversible: false` (SSRF, CSRF, product
  tamper, review edit) record `NOT_REVERSIBLE_MANUAL_REVIEW` — no silent undo.

## Primitives enabled (Broken Access Control, mutation class)
| Primitive | Challenge | Reversible | Rollback |
|---|---|---|---|
| idor-write-basket | Manipulate Basket | yes | `DELETE /api/BasketItems/{id}` |
| param-tamper-feedback | Forged Feedback | yes | `DELETE /api/Feedbacks/{id}` |
| idor-write-review | Forged Review | no | manual review |
| idor-write-product | Product Tampering | no | manual review |
| ssrf-profile-image | SSRF | no | manual review |
| csrf-change-username | CSRF | no | manual review |

## Boundaries
Still loopback-only, kill-switch + emergency-stop, integrity-sealed, hashes-only
evidence. DESTRUCTIVE remains DEFERRED to Stage 7.7 (double-approval).

## Next
Stage 7.7 — `CONTROLLED_DESTRUCTIVE` (DELETE) with double-approval; solves Five-Star Feedback.
