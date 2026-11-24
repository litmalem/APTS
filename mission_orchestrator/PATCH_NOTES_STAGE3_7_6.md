# Patch Notes — Stage 3.7.6

Stage 3.7.6 introduces the canonical Replan Candidate Validation & Delta Feasibility Gate.

Major changes:

- runtime head advanced from Stage 3.7.5 to Stage 3.7.6;
- repository migration advanced from 49 to 50;
- added `mission_orchestrator/replan_validation.py`;
- added durable `mission_replan_decisions` repository store;
- added migration `050_stage3_7_6_replan_candidate_validation_delta_feasibility_gate.sql`;
- added `MISSION_REPLAN_DECISION_RECORDED` Mission event;
- added deterministic candidate reproduction and feasibility checks;
- added active-Plan-head and Mission-version drift guards;
- added idempotent, single-decision-per-candidate persistence semantics;
- added validation API GET/POST surfaces;
- added 25 focused Stage-3.7.6 tests;
- rebased historical current-head assertions to the Stage-3.7.6 runtime/migration head without changing historical stage semantics.

Authority remains deliberately bounded: a positive decision means `VALIDATED_FOR_COMMIT`, not committed. Stage 3.7.6 creates no successor Plan, performs no supersession/state transition, and issues no routing, dispatch, execution, or target actuation.
