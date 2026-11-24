Stage 3.1.8-H1 Acceptance Script Hotfix

Purpose:
- Fix Windows PowerShell 5.1 ParserError caused by the UTF-8 em dash in the original
  STAGE3_1_8_ACCEPTANCE.ps1.
- No Mission Orchestrator source code is changed.
- No database migration is changed.
- The acceptance script is encoded as plain ASCII for maximum Windows PowerShell 5.1 compatibility.

Install:
1. Copy STAGE3_1_8_ACCEPTANCE.ps1 to D:\mission_orchestrator\
2. Overwrite the existing acceptance script only.
3. Run:

   cd D:\mission_orchestrator
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
   .\STAGE3_1_8_ACCEPTANCE.ps1

Expected regression gate:
91 passed

Expected final result:
STAGE 3.1.8 ACCEPTANCE: PASS
