# Patch Notes — Stage 3.6.1

## Canonical Task Outcome Contract & Identity

Stage 3.6.1 introduces the first task-level post-execution primitive after closure of Stage 3.5. It materializes a durable `toutcome-*` identity from a verified terminal execution trajectory while preserving a strict boundary between **execution evidence**, **task-outcome identity**, and later **task acceptance/completion authority**.

### Added

- `mission_orchestrator/task_outcome.py`
  - canonical task-outcome contract builder/verifier;
  - `toutcome-*` identity;
  - canonical request normalization/fingerprinting;
  - immutable SHA-256 contract;
  - fail-closed authority boundary metadata.
- `migrations/036_stage3_6_1_canonical_task_outcome_contract_identity.sql`
  - new durable `mission_task_outcomes` store;
  - uniqueness across outcome identity, idempotency key, Plan task, terminal propagation, and recovery checkpoint.
- `tests/test_stage3_6_1_canonical_task_outcome_contract_identity.py`
  - 19 focused Stage-3.6.1 tests.
- Event type `MISSION_TASK_OUTCOME_MATERIALIZED`.
- REST API for materialization, history, individual outcome retrieval, and canonical definition.
- Repository persistence manifest and integrity verification for canonical task outcomes.

### Changed

- Runtime control head advances to:
  `stage3.6.1-canonical-task-outcome-contract-identity`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.6.1`.
- Repository migration level advances from 35 to 36.
- Historical regression assertions are rebased to recognize the new Stage-3.6.1 control head and migration level.

### Source prerequisites enforced

A task outcome can be materialized only from an integrity-valid, contiguous chain containing:

- active canonical `pver-*` Plan version;
- Stage-3.5.4 `xattempt-*` execution attempt;
- Stage-3.5.7 `xresult-*` terminal result capture;
- Stage-3.5.8 `xprop-*` verified outcome propagation;
- Stage-3.5.9 `xrecover-*` recovery checkpoint;
- current Mission state/version vector matching the terminal trajectory.

### Deliberately not implemented in Stage 3.6.1

- task-outcome acceptance;
- acceptance-criteria evaluation;
- task completion commit;
- task state transition;
- dependency release;
- readiness recalculation;
- Plan progression;
- Mission success completion;
- Governance query;
- runtime query/control I/O;
- redispatch or creation of another execution attempt;
- target action/actuation.

### Verification completed during package construction

```text
Canonical inventory        : 982 tests collected
Focused Stage 3.6.1        : 19 passed
Focused predecessor 3.5.10 : 12 passed
Python compilation          : PASS
```

A full 982-test sequential regression is intentionally left to the target-host acceptance harness and is not claimed by this package-construction run.
