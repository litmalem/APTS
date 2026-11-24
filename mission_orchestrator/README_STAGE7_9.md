# Stage 7.9 — CAE learning loop (closes the REFUTED-label gap)

**Status:** implemented · advisory (never relaxes RoE) · additive
**Acceptance:** `python3 tests/test_stage7_9_cae_learning.py` → 5/5 PASS

## The gap it closes
The pre-CAE pipeline could not train its P3 classifier: all results were CONFIRMED /
PARTIALLY_CONFIRMED, so `fit()` saw a single class and refused — the model stayed
`PRIOR_UNTRAINED` / `NEURO_SYMBOLIC_NOT_JUSTIFIED`. The Stage-6-AE gateway now emits
genuine two-class outcomes:

| CAE step outcome | Learning label |
|---|---|
| EXPLOITED | CONFIRMED |
| ACTUATED / FAILED | **REFUTED** (the missing negative) |
| BLOCKED / REVIEW_REQUIRED / DEFERRED / REQUIRES_BROWSER_TRANSPORT / HALTED / SESSION_ESTABLISHED | not a result — never labelled |

## What this adds
`pentest_subsystem/cae_learning.py`:
- `observations_from_run(run)` — labelled observations from a sealed CAE run.
- `CaeLearningStore` — append-only dedup; **Beta-Bernoulli reliability posteriors**
  per arm (primitive); a **two-class dataset**; `can_train()` (both classes + sample
  floor); `train()` — a deterministic pure-Python logistic regression yielding
  `NEURO_SYMBOLIC_JUSTIFIED_TRAINED` when trainable, else `PRIOR_UNTRAINED` (reproducing
  the old limitation on single-class data). Integrity-sealed, advisory only.

Demonstrated before/after: single-class data → PRIOR_UNTRAINED; CAE two-class data →
TRAINED. This is the empirical justification the "neuro-symbolic" label previously lacked.

## Next
Stage 7.10 — consolidated validation + dissertation report (coverage, live evidence,
governance/containment, learning), then commit.
