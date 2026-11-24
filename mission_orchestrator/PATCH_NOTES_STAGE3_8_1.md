# Patch Notes — Stage 3.8.1

Introduces the canonical Mission root observability trace identity as a deterministic read-only projection over the existing immutable Mission envelope. No migration 054 is added and repository migration level remains 53.

Files added:
- `mission_orchestrator/observability_trace.py`
- `tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py`
- `README_STAGE3_8_1.md`
- `STAGE3_8_1_ACCEPTANCE.ps1`

Files updated:
- `mission_orchestrator/service.py`
- `mission_orchestrator/api_service.py`
- historical regression tests rebased to active runtime `3.8.1` while retaining Stage-3.7 predecessor assertions.
