# Patch Notes — Stage 3.7.7

## Added

- Canonical `replan_commit.py` contract and request normalization.
- Deterministic `rpcaop-*` Governance operation identity for response-loss recovery.
- Durable `mission_replan_commits` persistence model and migration 051.
- Authoritative commit-time Governance revalidation using `AUTHORIZE_REPLAN_COMMIT`.
- Atomic successor Plan append + active-head CAS + commit persistence.
- `MISSION_REPLAN_COMMIT_AUTHORIZED_SUCCESSOR_PLAN_MATERIALIZED` event lineage.
- Replan commit API POST/GET/history/definition endpoints.
- Repository reconstruction and persistence-manifest support for replan commits.
- 22 focused Stage-3.7.7 tests.

## Changed

- Runtime control advanced from Stage 3.7.6 to Stage 3.7.7.
- Repository migration level advanced from 50 to 51.
- API server identity advanced to `APTSMissionOrchestrator/3.7.7`.
- Plan-version contract verification now permits adaptive Stage-3.7 successor materialization from `RUNNING`, `WAITING_EVIDENCE`, or `WAITING_APPROVAL` only when the replan lineage origin is the Stage-3.7 authoritative commit path; legacy Stage-3.3.7 replan verification still requires `REPLANNING`.
- Historical acceptance/regression fixtures were rebased to the new runtime head and migration inventory while preserving stage-specific historical migration assertions.

## Preserved boundaries

- No historical Plan artifact mutation.
- No Mission lifecycle state transition.
- No routing or delegation.
- No execution dispatch or execution-attempt creation.
- No target action dispatch or external actuation.
- No caller-controlled successor Plan or Governance decision.

## Test status

- Compile: PASS.
- Collection: 1304 tests.
- Focused Stage 3.7.7: 22 PASS.
- Full uninterrupted regression: not completed in the build workspace because of runtime timeout; target-host acceptance script performs it.
