# Stage 7.2 — Exploit-primitive library (STRIPS planning_model)

**Status:** implemented · declarative only (no I/O) · additive
**Acceptance:** `python3 tests/test_stage7_2_exploit_primitive_library.py` → 6/6 PASS

## What this adds
`pentest_subsystem/exploit_primitive_library.py` — 13 exploit primitives, each with:
- a **`planning_model`** (`preconditions`/`effects`/`cost`) whose facts interlock so
  the EXISTING `symbolic_planner` builds real causal chains;
- the **CAE action class** from Stage 7.1, HTTP method, CWE/CAPEC/ATT&CK,
  a **success_predicate**, and the Juice Shop **`challenge_key`** it solves.

Enabler primitives (`auth-lab-user`, `auth-lab-admin`) PRODUCE `session:authenticated`
/ `session:admin`; exploit primitives REQUIRE them. Fed to
`symbolic_planner.compile_problem` → `plan`, this yields multi-step plans with
`model_basis == CTI_SYMBOLIC_CONTRACT` and non-empty `dependency_edges`.

## The gap it closes
The live run diagnosed the planner as `VALIDATION_PRIORITISATION_ONLY`
(`causal_dependency_edges: 0`, 19 `VALIDATION_ONLY` actions). With planning_model
contracts the planner now emits real chains, e.g.:

```
basketAccessChallenge (View Basket):
  Authenticate as LAB user [CTI_SYMBOLIC_CONTRACT]
    --session:authenticated-->
  View another user's basket (IDOR) [CTI_SYMBOLIC_CONTRACT]
  length=2  dependency_edges=1   (was 0)
```

## Coverage (11 Broken Access Control challenges)
adminSection, web3Sandbox, easterEgg, basketAccess(IDOR), basketManipulate,
forgedFeedback, forgedReview, changeProduct(Product Tampering), ssrf, csrf,
feedback(Five-Star, DESTRUCTIVE via admin chain). AI Debugging excluded (needs LLM API).

## Key API
- `primitives_for_challenge(key)` → ordered chain of primitive_ids (enablers first)
- `make_hypothesis_run(orch, asset_id, target, primitive_ids)` → compile_problem-ready
- `chain_for_challenge(key, orch, asset_id, target)` → full-chain hypothesis run
- `canonical_exploit_primitive_library()` → integrity-sealed catalog

## Boundaries
Declarative metadata only: no network I/O, no actuation, nothing executes. Primitives
only describe *how the Stage 6-AE gateway (7.4+) would act*, and feed the planner.

## Next
Stage 7.3 — `session_broker.py` (register/login LAB account, hold JWT), the first
component that turns a planned chain into a runnable session.
