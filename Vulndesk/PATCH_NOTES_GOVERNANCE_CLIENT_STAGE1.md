# VulnDesk Stage 1 — External GovernanceClient

## Objective

Replace the CTI-A02 local source-acquisition ALLOW decision with an authoritative
request to the independent aptsGSS Governance & Safety Plane.

## Runtime invariant

CTI-A02 may propose a CTI source read, but CTI-INF04 SourceSyncConnector is executed
only when aptsGSS returns an explicit `ALLOW` from:

`POST /api/governance/authorization/evaluate`

If Governance is disabled, unreachable, times out, returns non-2xx, malformed JSON,
or an unsupported decision, VulnDesk denies source acquisition fail-closed.

## Files changed

- `config.py`
- `.env.example`
- `.env` (three non-secret Governance settings appended when absent)
- `cti_services/governance_client.py` (new)
- `cti_services/cti_subsystem_orchestrator.py`
- `cti_services/pentest_enrichment_api_service.py`
- `cti_services/__init__.py`
- `tests/test_governance_client.py` (new)
- `tests/test_cti_event_driven_runtime.py`
- `run/governance_stage1_probe.py` (new)

## aptsGSS changes

No aptsGSS source-code change is required for Stage 1 because the existing
`AuthorizationRequest` model and `/api/governance/authorization/evaluate` endpoint
already support `CTI_SOURCE_READ`, source scope checking, deterministic gate decisions,
risk assessment, policy/scope versioning, decision TTL, and decision hash.

## Environment

```env
GOVERNANCE_ENABLED=true
GOVERNANCE_BASE_URL=http://127.0.0.1:8770
GOVERNANCE_TIMEOUT_SECONDS=5
```

## Expected decision behavior

- `ALLOW` -> CTI-INF04 may execute the selected source sync.
- `DENY` -> CTI-INF04 is not called.
- `REVIEW` -> CTI-INF04 is not called.
- Governance unavailable/invalid -> synthetic local `DENY` with
  `GOVERNANCE_UNAVAILABLE_FAIL_CLOSED`; CTI-INF04 is not called.

Local `policy_context.source_acquisition_allowed=false` or `allowed_cti_sources`
may still impose a stricter local DENY, but local state can no longer grant an ALLOW.

## Validation

Relevant isolated tests:

```powershell
pytest -q tests\test_governance_client.py tests\test_cti_event_driven_runtime.py tests\test_cti_harmonized_architecture.py
```

Stage-1 probe after aptsGSS is running and a valid scope contract exists:

```powershell
python run\governance_stage1_probe.py `
  --mission-id mission-cti-stage1-001 `
  --scope-contract-id <scope-contract-id> `
  --source-id nvd-cve
```
