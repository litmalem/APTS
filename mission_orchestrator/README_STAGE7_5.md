# Stage 7.5 — Human approval queue + single-use tokens + emergency stop

**Status:** implemented · governance plane (no I/O) · additive
**Acceptance:** `python3 tests/test_stage7_5_approval_broker.py` → 11/11 PASS

## What this adds
`pentest_subsystem/approval_broker.py` — the L3 control gate.
- **`ApprovalBroker`**: `request_approval` (emits a card for the Human Layer :8802),
  `approve`/`deny`, `validate_and_consume`, `emergency_stop`, `record`.
- **Tokens are single-use, action-bound, time-bound.** A token is minted on approve
  and bound to `(action_class, primitive_id, target)`; `validate_and_consume` checks
  state=APPROVED, not expired, binding matches, then marks CONSUMED. Second use,
  wrong binding, expiry, or deny → `ApprovalError` (fail-closed).
- **Emergency stop** revokes every PENDING/APPROVED token at once and blocks new
  requests (kill switch for the approval plane).
- Records are integrity-sealed and store `token_sha256`, never the raw token.

## Gateway integration
`active_exploitation_execution.py`:
- A step whose class is in RoE `human_approval_required_for` now surfaces
  `REVIEW_REQUIRED` from the Stage 7.1 guard and is actuated **only** after the
  `ApprovalBroker` consumes a matching single-use token. No broker/token →
  `REVIEW_REQUIRED` (no actuation); bad/expired/reused token → `BLOCKED
  APPROVAL_INVALID`.
- `gateway.emergency_stop()` halts the run and revokes all approval tokens.

### Security fix caught by the tests
The gateway previously passed the raw token into the 7.1 guard, which treated a
*present* token as satisfying review — bypassing real consumption (a token could be
reused). Fixed: the guard is asked WITHOUT the token so REVIEW_REQUIRED surfaces,
and the ApprovalBroker performs the real single-use consume.

## Next
Stage 7.6 — enable `CONTROLLED_STATE_MUTATION` (POST/PUT/PATCH) with reversible-first
+ auto-rollback, gated by these approval tokens; solves Manipulate Basket, Forged
Feedback/Review, Product Tampering, SSRF, CSRF.
