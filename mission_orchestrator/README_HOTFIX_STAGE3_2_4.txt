Stage 3.2.4 Acceptance Harness Hotfix
====================================

Scope: acceptance script only. No Mission Orchestrator runtime source, database schema,
Governance authority, CTI integration, or target-execution behavior changes.

Root cause:
STAGE3_2_4_ACCEPTANCE.ps1 used a non-existent GET endpoint twice:
  /api/missions/{mission_id}/state/history

The canonical Stage 3.1.2 state-history endpoint is:
  /api/missions/{mission_id}/state/transitions

This hotfix replaces those two URLs in the Stage 3.2.4 acceptance script.
Expected Python regression remains: 166 passed.
Repository migration level remains: 8.
