# VulnDesk — Stage 1 Closure Fixes

Date: 2026-08-14

This patch closes the two runtime defects found while validating Stage 1 GovernanceClient integration with aptsGSS.

## Fix 1 — `allow_degraded_acquisition=false` was ignored on governance non-ALLOW

### Previous behavior
When CTI-A02 received `DENY`, `REVIEW`, or fail-closed `DENY` from the governance boundary, the orchestrator always assigned:

- `cti_acquisition_freshness_agent = DEGRADED_ALLOWED`
- `PIPELINE_ADVANCE(reason=SOURCE_ACQUISITION_POLICY_DENIED)`

This happened even when the mission payload explicitly set:

```json
"allow_degraded_acquisition": false
```

As a result, downstream components such as `asset_profiling_cpe_resolution_service` could still run.

### Corrected behavior
`cti_services/cti_subsystem_orchestrator.py` now checks `allow_degraded_acquisition` for governance non-ALLOW decisions:

- `true`  -> preserves existing degraded-mode behavior.
- `false` -> sets CTI-A02 state to `FAILED`, records the policy decision, calls `_fail_mission(...)`, and does **not** advance the DAG.

The failure message preserves the governance reason code, including `GOVERNANCE_UNAVAILABLE_FAIL_CLOSED` for aptsGSS outages.

## Fix 2 — ISO-8601 timestamps were written directly to MariaDB `DATETIME`

### Previous behavior
`AssetProfilingCpeResolutionService` kept runtime timestamps in correct UTC ISO-8601 form, for example:

```text
2026-08-14T01:49:34.385403Z
```

but sent the same string directly to MariaDB `DATETIME` columns such as:

- `cti_asset_profiles.observed_at`
- `cti_cpe_resolution_claims.decision_time`

This caused MariaDB error 1292 (`Incorrect datetime value`).

### Corrected behavior
`cti_services/common.py` now provides `to_db_datetime(...)`.

The helper:

1. accepts Python `datetime` or ISO/SQL timestamp strings;
2. accepts the trailing `Z` UTC representation;
3. converts timezone-aware values to UTC;
4. strips timezone information only at the database boundary;
5. returns a native Python `datetime` suitable for PyMySQL/MariaDB `DATETIME`.

Runtime/event objects remain ISO-8601 strings; only persistence parameters are normalized.

`cti_services/asset_profiling_cpe_resolution_service.py` now uses this helper for both `observed_at` and `decision_time`.

## Database migration

No SQL schema migration is required.

## Files changed

- `cti_services/cti_subsystem_orchestrator.py`
- `cti_services/common.py`
- `cti_services/asset_profiling_cpe_resolution_service.py`
- `tests/test_stage1_closure_fixes.py` (new regression tests)

## Validation performed

Relevant unit/regression tests:

```text
22 tests passed
```

The test set includes:

- GovernanceClient contract tests.
- Existing event-driven CTI runtime tests.
- Harmonized architecture tests.
- New regression: policy DENY + `allow_degraded_acquisition=false` stops mission.
- New regression: governance outage + `allow_degraded_acquisition=false` stops mission.
- New regression: SourceSyncConnector is never called on the two blocked paths.
- New regression: ISO `Z` timestamp -> MariaDB-safe native `datetime`.
- New regression: `observed_at` and `decision_time` persistence parameters are DB-safe.

A full `unittest discover` run also reached 22 successful tests but could not import `tests/test_nvd_bulk_upsert.py` in the patch build environment because the environment did not have the optional `pymysql` module installed. This is an environment dependency limitation, not a failure of the changed code.

## Recommended Windows installation

1. Stop VulnDesk API/GUI/service manager instances.
2. Back up the three existing files listed above.
3. Copy the patched files into the same relative locations under `D:\vulndesk`.
4. Keep the existing local `.env`; this patch does not require environment-variable changes.
5. Start the API:

```powershell
cd D:\vulndesk
.\.venv\Scripts\activate
python .\run\run_vulndesk_api.py
```

6. Re-run the fail-closed mission with:

```json
"allow_degraded_acquisition": false
```

Expected behavior:

- aptsGSS unavailable -> `GOVERNANCE_UNAVAILABLE_FAIL_CLOSED`
- CTI-A02 -> `FAILED`
- mission -> `FAILED`
- no `PIPELINE_ADVANCE` into asset profiling
- no `CTI-INF04` / SourceSyncConnector events
- no `cti_asset_profiles.observed_at` error because asset profiling is not reached in this scenario

7. Re-run an ALLOW mission with aptsGSS available. Asset profiling should now persist `observed_at` without MariaDB error 1292.
