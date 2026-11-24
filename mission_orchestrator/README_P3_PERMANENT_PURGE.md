# P3 — Permanent Purge with Retention and Two-Person Approval

P3 adds an administrative purge workflow for a mission that is already archived. Purge physically removes the mission's rows from the Mission database in one transaction. A detached, hash-chained tombstone retains the mission ID, request and approval principals and reasons, retention period, policy attestations, and a digest/count manifest. The tombstone deliberately has no foreign key to the deleted mission.

## Controls

- Only archived terminal missions can be purged. A mission with child missions is rejected.
- Retention is checked both when the request is created and immediately before deletion. `MISSION_PURGE_MIN_RETENTION_DAYS` defaults to 365 days and accepts 30–36500 days.
- Request and approval use different secrets: `MISSION_PURGE_REQUEST_TOKEN` and `MISSION_PURGE_APPROVER_TOKEN`. Startup/runtime configuration must keep these distinct and restrict each to a different operator. The server derives the audit actors from `MISSION_PURGE_REQUESTOR_ACTOR` and `MISSION_PURGE_APPROVER_ACTOR`; those actor values must also differ.
- The approver must supply the returned challenge and explicitly attest `legal_hold_check: CLEAR` and `external_dependency_check: CLEAR`. This service does not query external GSS, CTI, or other system databases. The approver must perform those checks in the owning systems before attesting. Do not approve if a hold or dependency is unknown.
- Mission database foreign keys are honored. If a referencing row cannot be safely removed, the transaction fails and rolls back. Cross-system relationships are not deleted by Mission.
- SQLite and MySQL/MariaDB schema initialization creates the request and ledger tables. No production database or mission data is included in this patch.

## API workflow

Set the four secrets/actor environment values in the Mission service environment, then restart the service. Use distinct high-entropy request and approver secrets; keep them out of source control and shell history.

```powershell
$base = 'http://127.0.0.1:8780'
$missionId = 'mission-id-here'
$requestHeaders = @{ 'X-Mission-Purge-Request-Token' = $env:MISSION_PURGE_REQUEST_TOKEN }
$requestBody = @{
    reason = 'Retention elapsed; request permanent deletion under policy'
    idempotency_key = 'purge-request-unique-2026-001'
} | ConvertTo-Json
$request = Invoke-RestMethod -Method Post `
    -Uri "$base/api/missions/$missionId/purge-requests" `
    -Headers $requestHeaders -ContentType 'application/json' -Body $requestBody

# A different operator reviews the request and checks legal holds and other systems.
$approvalHeaders = @{ 'X-Mission-Purge-Approver-Token' = $env:MISSION_PURGE_APPROVER_TOKEN }
$approvalBody = @{
    request_id = $request.request_id
    challenge = $request.challenge
    approval_reason = 'Independent review completed under the retention policy'
    legal_hold_check = 'CLEAR'
    external_dependency_check = 'CLEAR'
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
    -Uri "$base/api/missions/$missionId/purge-approvals" `
    -Headers $approvalHeaders -ContentType 'application/json' -Body $approvalBody
```

The approval call performs the deletion; it is irreversible through this API. Back up the database and verify the request, retention eligibility, legal-hold review, and external dependency review before approval.

## Verification

Run `python -m unittest tests.test_purge_feature_p3 tests.test_restore_feature_p2 tests.test_archive_feature_p1 -v`. The local P3, P2, and P1 repository tests pass. HTTP listener tests require a host where loopback sockets are permitted; deployment-host acceptance is still required.
