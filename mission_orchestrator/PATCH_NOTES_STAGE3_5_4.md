# Patch Notes — Stage 3.5.4

Stage 3.5.4 adds the durable idempotent dispatch-commit boundary between authoritative Stage-3.5.3 execution authorization and later target delivery/execution controls.

The patch introduces canonical `xattempt-*` execution-attempt identity and `xenv-*` immutable dispatch-envelope identity. The orchestrator revalidates the current Mission state/version vector, active Plan head, Stage-3.5.1 execution dispatch, Stage-3.5.2 PASSED eligibility evidence, and the **latest** Stage-3.5.3 `ALLOW` Governance revalidation before materializing a single durable initial attempt.

Idempotency is enforced at both service and repository levels. Replaying the same idempotency key with the same canonical request returns the same attempt/envelope and does not duplicate lineage evidence. Reusing the key with a different request fails with conflict. A different key cannot create a second initial attempt for the same `xdispatch-*` identity.

Engineering changes include migration level 30, durable `mission_execution_attempts` storage, canonical hashing/verification, transactional duplicate suppression, REST routes, lineage event `MISSION_EXECUTION_ATTEMPT_COMMITTED`, repository reconstruction/integrity coverage, Stage-3.5.4 health declarations, server/control version activation, compatibility assertion rebasing through Stage 3.4/3.5.3, and a 20-test focused Stage-3.5.4 suite.

Authority boundaries remain strict: Stage 3.5.4 consumes the latest Stage-3.5.3 authoritative decision but performs **no new Governance query**, no runtime endpoint resolution, no health probe, no resource assignment, no target delivery, no delivery acknowledgement, no execution start, no external target network I/O, no target action dispatch, and no target actuation. Delivery/execution-start semantics remain deferred to Stage 3.5.5.


## Verification

Final package verification completed successfully: Python compilation passed; canonical collection is exactly **856 tests**; full regression is **856/856 PASS in 552.39 s** with an independent prior **856/856 PASS in 539.12 s**; focused Stage-3.5.4 proof is **20/20 PASS in 30.07 s**. Target-host runtime acceptance is still performed with `STAGE3_5_4_ACCEPTANCE.ps1`.
