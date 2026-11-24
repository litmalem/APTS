# Patch Notes — Stage 5.1

## Full Agentic Pentest Workflow Orchestrator

Stage 5.1 promotes the Stage-4.6 local placeholder workflow into a durable **multi-agent Pentest control plane**. It implements contract-driven task understanding, deterministic decomposition, specialist-role assignment, progress aggregation, versioned replanning, and bounded terminate/escalate semantics without enabling specialist execution or target-side effects.

## Added

- `pentest_subsystem/orchestration/`
  - `orchestrator.py` — canonical Stage-5.1 contract, durable repository, service, orchestration lifecycle, progress/replan persistence
  - `task_graph.py` — deterministic seven-capability Agent Task Graph
  - `assignment.py` — canonical specialist-role ownership mapping
  - `progress.py` — specialist-bound progress observation and aggregation
  - `replanning.py` — versioned `RETRY_FAILED`, `REBUILD_REMAINING`, `ESCALATE`, and `TERMINATE`
  - `__init__.py` — public Stage-5.1 exports
- `pentest_migrations/008_stage5_1_full_agentic_pentest_workflow_orchestrator.sql`
  - orchestration state
  - plan revisions
  - progress records
  - replan records
- `tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py`
  - 24 focused tests
- `STAGE5_1_ACCEPTANCE.ps1`
  - runtime contract checks
  - negative execution boundary
  - focused and qualification regressions
  - full historical regression as deployment PASS/FAIL authority

## Changed

- `pentest_subsystem/api_service.py`
  - added `PentestSubsystemStage51Handler`
  - active server version advanced to `APTSPentestSubsystem/5.1`
  - added Stage-5.1 contract/orchestration/progress/replan/query routes
  - retained historical Stage-4.10 handler via `serve_stage410()`
- `pentest_subsystem/__init__.py`
  - package summary and Stage-5.1 exports
- `run/pentest_subsystem.py`
  - runtime description advanced to Stage 5.1

## Canonical Stage-5.1 pipeline

```text
Pentest Task / PIP-bound local task
        ↓
Task understanding from canonical contract
        ↓
Deterministic decomposition
        ↓
Agent Task Graph
        ↓
Specialist role assignment
        ↓
Observe progress
        ↓
Aggregate state
        ↓
Evaluate progress
        ↓
Replan / terminate / escalate
```

The seven canonical capability nodes are:

`reconnaissance → enumeration → vulnerability_analysis → attack_path_analysis → validation → exploitation → impact_analysis`.

## Authority boundary

Stage 5.1 **does not**:

- implement the Stage-5.2…5.7 specialist agents;
- grant specialist execution authority;
- invoke raw tools;
- provide raw target access;
- perform external network I/O;
- actuate targets;
- mint `PolicyDecision` authorization;
- replace the Stage-3 Global Mission Orchestrator.

Controlled execution remains Stage 6 authority.
