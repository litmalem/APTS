# Patch D3 — PIP Assembly Persistence Hardening

Control version: `hybrid-event-driven-2.3-pip-persistence-hardening`

## Problem closed

A clean D1/D2 mission reached `pip_assembly_validation_service` and then failed with:

```text
dict can not be used as parameter
```

The PIP persistence boundary used a broad SQL parameter mapping:

```python
{
    **artifact,
    "artifact_json": ...,
    "validation_summary_json": ...,
}
```

`artifact` contains nested dictionaries and `validation_results` contains `list[dict]`. PyMySQL eagerly escapes every value in a named-parameter mapping, even values whose keys are not referenced by the statement. A nested dictionary therefore reached the SQL driver as a scalar parameter.

## D3 changes

- Replaced `**artifact` with an explicit PIP SQL parameter contract.
- Only SQL-referenced scalar values cross the persistence boundary.
- `artifact` is serialized with `canonical_json()` into `artifact_json`.
- `validation_results` is serialized with `to_json()` into `validation_summary_json`.
- Each quality-gate `details` object is explicitly serialized into `details_json`.
- Publication keeps `immutable=1` and `execution_authorized=0` as database literals; PIP remains a decision-support artifact, never an execution command.
- Added D3 regression tests that deliberately use nested dictionaries and `list[dict]` and fail if a structured object reaches the SQL parameter mapping.

## No database migration required

The existing tables already match the persistence contract:

- `cti_pip_artifacts`
- `cti_pip_validation_results`

D3 changes application persistence semantics only.

## Expected E2E result

After D3, a mission that reaches CTI-S06 should persist the PIP artifact and quality-gate rows without the PyMySQL dictionary-parameter error. The expected terminal path is:

```text
PIP Assembly & Validation -> COMPLETED
PIP Artifact -> persisted, immutable=1, execution_authorized=0
MISSION -> COMPLETED or QUALITY_REVIEW depending on hard-gate results
```
