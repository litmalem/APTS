# Stage 7.7 — CONTROLLED_DESTRUCTIVE (double-approval)

**Status:** implemented · opt-in actuation · additive
**Acceptance:** `python3 tests/test_stage7_7_destructive.py` → 5/5 PASS

## What this adds
The gateway now actuates `CONTROLLED_DESTRUCTIVE` (DELETE), **opt-in** via
`enable_classes` and requiring RoE `destructive_actions_allowed: true`.

- **Double-approval (segregation of duties):** `REQUIRED_APPROVALS[DESTRUCTIVE] = 2`.
  The gateway consumes two single-use tokens bound to the action and requires **two
  distinct approvers**. One token → `REVIEW_REQUIRED`; two from the same approver →
  `BLOCKED SEGREGATION_OF_DUTIES`; valid distinct pair → actuates.
- **Solves Five-Star Feedback** via the admin chain
  `auth-lab-admin → destroy-5star-feedback` (`DELETE /api/Feedbacks/{id}`).
- DESTRUCTIVE is irreversible: no auto-rollback; the double-approval is the control.

## Backward compatible
Default `enable_classes = {ACTIVE_EXPLOITATION}`, single-approval classes unchanged,
so Stages 7.4–7.6 behaviour and tests are untouched.

## Stage 7 — execution-class ladder complete
| Class | Stage | Approval | Rollback |
|---|---|---|---|
| CONTROLLED_ACTIVE_EXPLOITATION | 7.4 | none (unless configured) | — |
| CONTROLLED_STATE_MUTATION | 7.6 | single token | reversible-first auto-rollback |
| CONTROLLED_DESTRUCTIVE | 7.7 | two distinct approvers | none (irreversible) |

## Next
Stage 7.8 — containment probes (`APTS-AL-028`) for the CAE plane; then 7.4b browser
transport (Admin/Web3) and the host runner for end-to-end live solves.
