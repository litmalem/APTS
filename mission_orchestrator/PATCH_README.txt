APTS — Stage 3.4.5/3.4.6 Delegation Policy Alignment Patch
================================================================
Source snapshot: Mission(20261012-224106).zip
Target root: D:\mission_orchestrator

Problem:
The canonical Stage 3.4.4 test chooses CTI:cti.read.context, but the
Stage 3.1.4 fixture and runtime scope limited delegation to
PENTEST:pentest.recon. The fake Governance client returned ALLOW for an
unlisted CTI route, and the Stage 3.4.5 guard correctly rejected it.

Changes:
1. governance_binding.py: allow a logical handoff to CTI:cti.read.context
   ONLY if the CTI_SOURCE_READ capability is explicitly bound to the
   canonical mission scope, its component matches the CTI registry prefix,
   and its registry side-effect classification is READ_ONLY_ANALYSIS.
   PENTEST:pentest.recon remains eligible. pentest.validate, exploitation,
   and all other capabilities stay default-deny.
2. service.py: on ALLOW, require GSS allowed_capabilities to EXACTLY equal
   the authoritative, immutable scope's delegation allowlist AND contain
   the selected route. Preserve execution_authorized=False and target_actuation=False.
3. delegation_authorization.py: verify authorization contains the selected
   subsystem/capability in the signed attestation, independent of whether
   it is CTI read or Pentest recon.
4. FakeGovernanceClient: evaluate TASK_DELEGATION based on the published
   scope action_constraints, never grant a request solely because there
   is no emergency stop.
5. Stage345 tests: opt in to CTI_SOURCE_READ explicitly; retain old
   Stage314 baseline; test unbound CTI DENY and forged ALLOW mismatch.

Install in PowerShell (back up the project first):
  cd D:\mission_orchestrator
  Expand-Archive -LiteralPath 'PATH_TO\APTS_Stage345_346_Governance_Delegation_Patch.zip' -DestinationPath . -Force

Run tests:
  .\.venv\Scripts\python.exe -m pytest -q `
    tests/test_stage3_1_4_governance_authorization_binding.py `
    tests/test_stage3_4_5_governance_bound_delegation_authorization.py `
    tests/test_stage3_4_6_canonical_delegation_contract_handoff_envelope.py

Important: This patch does NOT change stored immutable scopes or approvals;
existing missions requiring CTI delegation need an explicitly revised scope
and binding under Governance authority. This does not authorize execution,
network actuation, or Pentest validation.
