# Adaptive CTI Source Monitoring

## Goal
Make external CTI freshness monitoring autonomous without bypassing the existing
CTI mission and GSS governance path.

## Implemented
- `cti_services/source_change_detector.py`
  - NVD CVE: one-result `lastModStartDate` / `lastModEndDate` probe.
  - NVD CPE: one-result `lastModStartDate` / `lastModEndDate` probe.
  - MITRE ATT&CK: TAXII `added_after` one-object probe.
  - MITRE CWE: `/cwe/version` SHA-256 fingerprint.
  - Generic HTTPS fallback: conditional HTTP metadata probe.
- `Vulndesk_Web/adaptive_scheduler.py`
  - Per-source due scheduling.
  - Exponential backoff on consecutive no-change probes.
  - Reset to minimum interval when a change is detected.
  - Deterministic +/-5% jitter.
  - Honors source circuit-breaker retry state.
  - Persists probe/next-check state and updates `cti_source_state.change_signal`.
  - Optional auto-update through the existing governed CTI mission route.
- NVD CPE synchronization now uses a native modified-date range rather than
  repeating bounded first-page refreshes.
- Web source management exposes adaptive monitor and auto-update settings/status.
- Migration: `sql_update_cti_harmonized/09_adaptive_source_monitoring.sql`.

## Governance invariant
The adaptive scheduler never invokes `SourceSyncConnector` directly. If
`auto_update=true`, it creates a normal CTI mission through Vulndesk Web's
`start_mission`, preserving external authoritative GSS authorization and scope
revalidation.

## Deployment
1. Apply migration `09_adaptive_source_monitoring.sql` to the Vulndesk database.
2. Start Vulndesk Web normally.
3. In **API Eksternal -> Ubah**, enable adaptive monitoring.
4. For fully autonomous synchronization, enable auto-update and provide a valid
   `auto_scope_contract_id`, or set `CTI_AUTONOMOUS_SCOPE_CONTRACT_ID`.

## Validation
- Python syntax compilation: PASS.
- JavaScript syntax (`node --check`): PASS.
- Regression + new adaptive tests: 60 passed, 31 subtests passed.
- Browser Playwright suite was not executed in the build container because the
  optional `playwright` Node package is not installed there.
