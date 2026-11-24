# Patch Notes — Stage 3.8.1 Acceptance Hotfix 1

Fixes the Windows compile step in `STAGE3_8_1_ACCEPTANCE.ps1`.

Old:
`python -m py_compile mission_orchestrator/*.py run/*.py`

New:
`python -m compileall -q mission_orchestrator run tests`

The Stage 3.8.1 runtime contract is unchanged. This hotfix modifies only the acceptance harness.
