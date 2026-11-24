# Patch Notes — Stage 3.5.1 Canonical Execution Dispatch Contract & Identity

## Added

- `mission_orchestrator/execution_dispatch.py`
  - canonical `xdispatch-*` identity;
  - immutable dispatch contract and domain-separated SHA-256 verification;
  - canonical request validation/fingerprinting;
  - exact Mission/Plan/ownership provenance binding;
  - explicit no-dispatch/no-execution semantics;
  - static contract definition.
- `migrations/027_stage3_5_1_canonical_execution_dispatch_contract_identity.sql`
  - durable `mission_execution_dispatch_contracts` store;
  - uniqueness for dispatch identity, idempotency key, and active Plan task binding;
  - foreign-key provenance to Plan/task/delivery/delegation/route/delegation-authorization records.
- Mission event `MISSION_EXECUTION_DISPATCH_CONTRACT_MATERIALIZED`.
- HTTP endpoints for dispatch-contract create/history/get/definition.
- repository CRUD and repository-model projection for execution-dispatch contracts.
- repository integrity verification for persisted execution-dispatch provenance and event cardinality.
- execution-dispatch conflict/not-found/guard error types and API mappings.
- `tests/test_stage3_5_1_canonical_execution_dispatch_contract_identity.py` with 19 focused tests.
- Stage-3.5.1 README, install guide, patch manifest, acceptance harness, regression evidence, and SHA-256 inventory.

## Changed

- active control -> `stage3.5.1-canonical-execution-dispatch-contract-identity`;
- HTTP server identity -> `APTSMissionOrchestrator/3.5.1`;
- repository migration level -> `27`;
- `supported_controls` appends Stage 3.5.1 after Stage 3.4.10;
- historical regression assertions that intentionally track the active control, server identity, repository migration level, store inventory, or current supported-control window are rebased to Stage 3.5.1;
- Stage-3.4.4 through Stage-3.4.9 historical supported-control assertions were corrected so the Stage-3.4 window still terminates at Stage 3.4.10 while Stage 3.5.1 remains the active successor.

## Preserved

Stage 3.5.1 does not add runtime execution authority. The following remain false:

```text
runtime endpoint resolution
runtime health probing
resource assignment
new Governance query during xdispatch materialization
execution authorization/grant
dispatch attempt
actual task dispatch
external network I/O
target-action dispatch
target actuation
ownership-as-execution-authority
delegation-authorization reuse as execution grant
```

Pre-dispatch Governance revalidation remains mandatory for a later execution stage.

## Persistence

```text
repository_migration_level = 27
new_store = mission_execution_dispatch_contracts
new_event = MISSION_EXECUTION_DISPATCH_CONTRACT_MATERIALIZED
```

## Verification during package construction

```text
python -m compileall -q mission_orchestrator tests     PASS
pytest collection                                      798 tests
Stage 3.1                                               111 passed
Stage 3.2                                               156 passed
Stage 3.3                                               239 passed
Stage 3.4                                               273 passed
Stage 3.5.1 focused                                      19 passed
Total partitioned regression                            798 passed
```

The target host must still run `STAGE3_5_1_ACCEPTANCE.ps1` after installation and runtime activation.
