param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.1.9 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Post-Json([string]$Uri, $Body) {
    $json = $Body | ConvertTo-Json -Depth 50 -Compress
    return Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body $json
}

Write-Host "=============================================================================="
Write-Host "Stage 3.1.9 - Mission Event & Lineage Foundation Acceptance"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[1] Full regression"
$pytestOutput = & python -m pytest -q 2>&1
$pytestOutput | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) { Fail "Regression suite failed" }
if (($pytestOutput -join "`n") -notmatch "101 passed") { Fail "Expected current regression result '101 passed'" }
Pass "Stage 3.1.1 through 3.1.9 regression"

Write-Host "`n[2] Stage-3.1.9 health / authority boundary"
try {
    $health = Invoke-RestMethod "$MissionBaseUrl/health"
} catch {
    Fail "Mission Orchestrator health unavailable: $($_.Exception.Message)"
}
if ($health.control_version -ne "stage3.1.9-mission-event-lineage-foundation") { Fail "Unexpected control_version: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne 8) { Fail "Repository migration level must be 8" }
if ($health.mission_event_schema_version -ne "apts-mission-event-v1") { Fail "Mission event schema mismatch" }
if ($health.mission_lineage_schema_version -ne "apts-mission-lineage-v1") { Fail "Mission lineage schema mismatch" }
if ($health.mission_event_mode -ne "DURABLE_APPEND_ONLY_HASH_CHAIN") { Fail "Mission event mode mismatch" }
if ($health.mission_lineage_mode -ne "MISSION_ROOT_TRACE_BUSINESS_CAUSATION_LOCAL_PARENT_CHAIN") { Fail "Mission lineage mode mismatch" }
if ($health.mission_event_audit_hooks_enabled -ne $true) { Fail "Mission event audit hooks are not enabled" }
if ($health.mission_event_external_delivery_enabled -ne $false) { Fail "Stage 3.1.9 must not enable external event delivery" }
if ($health.mission_event_external_authority_queries -ne $false) { Fail "Event lineage reads must not query external authorities" }
if ($health.mission_event_historical_backfill_mode -ne "NO_SYNTHETIC_HISTORICAL_EVENTS") { Fail "Historical backfill mode mismatch" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.dispatch_enabled -ne $false -or $health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) {
    Fail "Stage 3.1.9 must not enable target execution authority"
}
Pass "Event/lineage foundation active; Governance and target execution boundaries preserved"

$token = (Get-Date -Format "yyyyMMddHHmmss") + "-" + ([guid]::NewGuid().ToString("N").Substring(0,8))
$missionPayload = @{
    idempotency_key = "stage319-mission-$token"
    source_system = "STAGE319_ACCEPTANCE"
    created_by = "stage3.1.9-acceptance"
    mission_kind = "AUTONOMOUS_PENTEST"
    objective = @{ type = "SECURITY_VALIDATION"; target_ref = "event-lineage-lab" }
    success_criteria = @(@{ metric = "lineage_valid"; expected = $true })
    budgets = @{ time_seconds = 1800 }
    required_subsystems = @("CTI", "PENTEST")
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.9" }
}

Write-Host "`n[3] Mission registration emits one canonical root event"
try {
    $created = Post-Json "$MissionBaseUrl/api/missions" $missionPayload
} catch {
    Fail "Mission creation failed: $($_.Exception.Message)"
}
if ($created.idempotent_replay -ne $false) { Fail "First mission create unexpectedly replayed" }
$missionId = [string]$created.canonical_identity.mission_id
$correlationId = [string]$created.canonical_identity.correlation_id
$envelopeId = [string]$created.canonical_identity.envelope_id
try {
    $eventView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
} catch {
    Fail "Mission events endpoint failed after registration: $($_.Exception.Message)"
}
$events = @($eventView.events)
if ($events.Count -ne 1) { Fail "Expected exactly 1 registration event, got $($events.Count)" }
$root = $events[0]
$requiredFields = @("event_id","mission_id","trace_id","correlation_id","causation_id","parent_event_id","source_component","event_type","state_version","plan_version","policy_version","occurred_at")
$presentFields = @($root.PSObject.Properties.Name)
foreach ($field in $requiredFields) {
    if ($presentFields -notcontains $field) { Fail "Root event missing required field '$field'" }
}
if ($root.event_type -ne "MISSION_REGISTERED") { Fail "First event must be MISSION_REGISTERED" }
if ($root.event_id -ne $root.trace_id) { Fail "Root event trace_id must equal event_id" }
if ($root.mission_id -ne $missionId) { Fail "Root event mission_id mismatch" }
if ($root.correlation_id -ne $correlationId) { Fail "Root event correlation_id mismatch" }
if ($root.causation_id -ne $envelopeId) { Fail "Root event causation_id must reference envelope_id" }
if ($null -ne $root.parent_event_id) { Fail "Root event parent_event_id must be null" }
if ($null -ne $root.previous_event_sha256) { Fail "Root event previous_event_sha256 must be null" }
if ($root.source_component -ne "APTS-MO01") { Fail "Unexpected source_component: $($root.source_component)" }
if ([int]$root.state_version -ne 1) { Fail "Registration event must observe state_version=1" }
if ([string]$root.canonical_sha256 -notmatch '^[0-9a-f]{64}$') { Fail "Root event canonical_sha256 is invalid" }
if ($eventView.integrity_status -ne "PASS") { Fail "Root event ledger integrity did not PASS" }
Pass "Canonical MISSION_REGISTERED root event persisted with required lineage fields"

Write-Host "`n[4] Idempotent mission replay does not duplicate the event"
try {
    $replay = Post-Json "$MissionBaseUrl/api/missions" $missionPayload
    $afterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
} catch {
    Fail "Mission replay/event read failed: $($_.Exception.Message)"
}
if ($replay.idempotent_replay -ne $true) { Fail "Second identical create must be an idempotent replay" }
if ([int]$afterReplay.event_count -ne 1) { Fail "Idempotent replay duplicated Mission event history" }
Pass "Event replay gate preserved one canonical registration event"

Write-Host "`n[5] State mutation appends a parent/hash-chained event"
$transitionPayload = @{
    expected_state_version = 1
    to_state = "PIP_BOUND"
    actor = "stage3.1.9-acceptance"
    reason_code = "STAGE319_LINEAGE_PROBE"
    reason = "Create second canonical event"
    evidence_refs = @()
    metadata = @{ acceptance = "stage3.1.9" }
}
try {
    $transition = Post-Json "$MissionBaseUrl/api/missions/$missionId/state/transitions" $transitionPayload
    $eventView2 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
} catch {
    Fail "State transition or event append failed: $($_.Exception.Message)"
}
if ($transition.mission_state.state -ne "PIP_BOUND" -or [int]$transition.mission_state.state_version -ne 2) {
    Fail "Canonical state transition did not produce PIP_BOUND/v2"
}
$events2 = @($eventView2.events)
if ($events2.Count -ne 2) { Fail "Expected 2 events after state transition, got $($events2.Count)" }
$second = $events2[1]
if ($second.event_type -ne "MISSION_STATE_TRANSITIONED") { Fail "Second event must be MISSION_STATE_TRANSITIONED" }
if ($second.trace_id -ne $root.event_id) { Fail "Second event did not inherit root trace_id" }
if ($second.correlation_id -ne $correlationId) { Fail "Second event correlation_id diverged" }
if ($second.parent_event_id -ne $root.event_id) { Fail "Second event parent_event_id is not root event" }
if ($second.previous_event_sha256 -ne $root.canonical_sha256) { Fail "Second event hash-chain predecessor mismatch" }
if ([int]$second.state_version -ne 2) { Fail "State-transition event must observe state_version=2" }
if ([string]$second.canonical_sha256 -notmatch '^[0-9a-f]{64}$') { Fail "Second event canonical_sha256 is invalid" }
if ($eventView2.integrity_status -ne "PASS") { Fail "Two-event ledger integrity did not PASS" }
Pass "State event appended with stable trace/correlation and immediate local parent/hash chain"

Write-Host "`n[6] Read-only lineage projection"
try {
    $lineage = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/lineage"
} catch {
    Fail "Mission lineage endpoint failed: $($_.Exception.Message)"
}
if ($lineage.projection_schema_version -ne "apts-mission-lineage-v1") { Fail "Lineage projection schema mismatch" }
if ([int]$lineage.event_count -ne 2 -or [int]$lineage.causal_edge_count -ne 1) { Fail "Unexpected lineage event/edge counts" }
if ($lineage.root_event_id -ne $root.event_id) { Fail "Lineage root_event_id mismatch" }
if ($lineage.identity.trace_id -ne $root.event_id) { Fail "Lineage trace_id mismatch" }
if ($lineage.identity.correlation_id -ne $correlationId) { Fail "Lineage correlation_id mismatch" }
if ($lineage.integrity_status -ne "PASS") { Fail "Lineage integrity did not PASS" }
if ($lineage.external_authority_query_performed -ne $false) { Fail "Lineage projection queried external authority" }
if ($lineage.target_action_dispatch_enabled -ne $false -or $lineage.target_actuation -ne $false) { Fail "Lineage projection changed target execution boundary" }
$edge = @($lineage.causal_edges)[0]
if ($edge.parent_event_id -ne $root.event_id -or $edge.child_event_id -ne $second.event_id) { Fail "Local causal edge mismatch" }
Pass "Mission lineage reconstructed locally with one verified parent edge and zero authority query"

Write-Host "`n[7] Single-event API verifies ledger integrity"
try {
    $single = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events/$($second.event_id)"
} catch {
    Fail "Single event endpoint failed: $($_.Exception.Message)"
}
if ($single.event.event_id -ne $second.event_id -or $single.event.event_type -ne "MISSION_STATE_TRANSITIONED") { Fail "Single event response mismatch" }
if ($single.integrity_status -ne "PASS") { Fail "Single event read did not report integrity PASS" }
Pass "Single-event read returns the canonical event only after ledger verification"

Write-Host "`n[8] Stage-3.1.7 repository reconstruction includes Stage-3.1.9 event store"
try {
    $repository = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
} catch {
    Fail "Mission repository projection failed: $($_.Exception.Message)"
}
if ($repository.integrity_status -ne "PASS") { Fail "Repository integrity did not PASS" }
if ([int]$repository.record_counts.mission_events -ne 2) { Fail "Repository mission_events count must be 2" }
$manifestEvents = @($repository.persistence_manifest.mission_event_store)
if ($manifestEvents.Count -ne 2) { Fail "Persistence manifest mission_event_store must contain 2 events" }
$eventIntegrityCheck = @($repository.integrity_checks | Where-Object { $_.check -eq "mission_event_append_only_hash_chain" })
if ($eventIntegrityCheck.Count -ne 1 -or $eventIntegrityCheck[0].status -ne "PASS") { Fail "Repository event hash-chain integrity check did not PASS" }
Pass "Durable repository manifest/counts include the verified append-only Mission event ledger"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.1.9 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
