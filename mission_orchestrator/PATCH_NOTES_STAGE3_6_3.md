# Patch Notes — Stage 3.6.3 Evidence Binding Verification

Stage 3.6.3 adds a fail-closed verification layer between task completion eligibility and later acceptance/completion semantics. The implementation creates immutable `ebind-*` records that prove internal consistency of the evidence/artifact reference manifests already captured by Stage 3.5.7 and propagated through Stages 3.6.1 and 3.6.2.

The patch adds migration 038 and `mission_task_evidence_binding_verifications`, extends repository reconstruction/integrity checking, registers `MISSION_TASK_EVIDENCE_BINDING_VERIFIED`, exposes POST/GET/definition APIs, advances runtime identity to `stage3.6.3-evidence-binding-verification`, and adds 20 focused tests.

The stage intentionally does not fetch external evidence content, recompute content digests from external bytes, attest content authenticity, evaluate acceptance criteria, commit task completion, release dependencies, progress the Plan, complete the Mission, query Governance/runtime, redispatch, or actuate a target. Those remain later-stage authorities.
