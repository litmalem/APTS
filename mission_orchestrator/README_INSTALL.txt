Mission Orchestrator — Post-Approval Reconciliation Patch

INSTALLATION
1. Stop the Mission Orchestrator service.
2. Make a backup copy of these existing files in your Mission folder:
   - mission_orchestrator/service.py
   - mission_orchestrator/api_service.py
   - mission_orchestrator/governance_binding.py
   - tests/test_stage3_1_4_governance_authorization_binding.py
3. Extract this ZIP into the root of your existing Mission Orchestrator folder.
   Preserve the folder paths and choose Replace files when prompted.
4. Run Python compilation and your normal Mission Orchestrator regression suite.
5. Restart the service.

The patch adds the reconciliation endpoint documented in
PATCH_NOTES_POST_APPROVAL_RECONCILIATION.md. It is an overlay for the existing
Mission project, not a complete standalone Mission distribution.
