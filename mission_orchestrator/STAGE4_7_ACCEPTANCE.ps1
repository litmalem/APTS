param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedWorkflowControl = "stage4.6-pentest-workflow-orchestrator-skeleton"
$ExpectedControl = "stage4.7-capability-registry-tool-contract"
$ExpectedSchema = "apts-stage4.7-capability-registry-tool-contract-v1"
$ExpectedRegistrySchema = "apts-pentest-capability-registry-v1"
$ExpectedCapabilitySchema = "apts-pentest-capability-contract-v1"
$ExpectedToolSchema = "apts-pentest-tool-contract-v1"
$ExpectedMappingSchema = "apts-pentest-capability-tool-mapping-v1"
$ExpectedMissionMigration = 53
$ExpectedPentestMigration = 5
$ExpectedInventory = 1724
$ExpectedCapabilities = @(
    "reconnaissance",
    "enumeration",
    "vulnerability_analysis",
    "attack_path_analysis",
    "validation",
    "exploitation",
    "impact_analysis"
)
$ExpectedTools = @(
    "pentest.tool.passive_discovery",
    "pentest.tool.network_discovery",
    "pentest.tool.service_enumerator",
    "pentest.tool.vulnerability_analyzer",
    "pentest.tool.attack_path_analyzer",
    "pentest.tool.validation_probe",
    "pentest.tool.exploitation_adapter",
    "pentest.tool.impact_analyzer"
)

Write-Host "=============================================================================="
Write-Host "Stage 4.7 - Capability Registry & Tool Contract"
Write-Host "=============================================================================="

Write-Host "`n[0] Stage 3 predecessor preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator predecessor control mismatch: $($mo.control_version)" }
if ([int]$mo.mission_repository_migration_level -ne $ExpectedMissionMigration) { throw "Mission Orchestrator migration mismatch" }
if ($mo.stage3_9_10_stage_output -ne "GLOBAL_MISSION_ORCHESTRATOR") { throw "Stage 3 output mismatch" }
Write-Host "[PASS] Stage 3.9.10 remains closed"

Write-Host "`n[1] Stage 4.7 runtime activation preflight"
$health = Invoke-RestMethod "$PentestUrl/health"
if ($health.status -ne "ok") { throw "Pentest subsystem health is not ok" }
if ($health.subsystem_id -ne "PENTEST") { throw "Pentest subsystem identity mismatch" }
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest repository migration mismatch" }
if ($health.stage4_7_schema_version -ne $ExpectedSchema) { throw "Stage 4.7 control schema mismatch" }
if ($health.stage4_7_registry_schema_version -ne $ExpectedRegistrySchema) { throw "Stage 4.7 registry schema mismatch" }
if ($health.stage4_7_capability_schema_version -ne $ExpectedCapabilitySchema) { throw "Stage 4.7 capability schema mismatch" }
if ($health.stage4_7_tool_schema_version -ne $ExpectedToolSchema) { throw "Stage 4.7 tool schema mismatch" }
if ($health.stage4_7_mapping_schema_version -ne $ExpectedMappingSchema) { throw "Stage 4.7 mapping schema mismatch" }
if ($health.stage4_7_predecessor_control -ne $ExpectedWorkflowControl) { throw "Stage 4.7 predecessor mismatch" }
if ([int]$health.stage4_7_repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 4.7 migration metadata mismatch" }
if ([int]$health.stage4_7_capability_count -ne 7) { throw "Stage 4.7 capability count mismatch" }
if ([int]$health.stage4_7_tool_count -ne 8) { throw "Stage 4.7 tool count mismatch" }
if ([int]$health.stage4_7_mapping_count -ne 8) { throw "Stage 4.7 mapping count mismatch" }
if (-not $health.stage4_7_capability_registry_enabled) { throw "Capability registry is not enabled" }
if (-not $health.stage4_7_tool_contract_enabled) { throw "Tool contract is not enabled" }
if (-not $health.stage4_7_tool_capability_mapping_enabled) { throw "Capability-tool mapping is not enabled" }
if ($health.stage4_7_capability_selection_enabled) { throw "Stage 4.7 must not select capabilities yet" }
if ($health.stage4_7_full_reasoning_enabled -or $health.stage4_7_replanning_enabled) { throw "Stage 4.7 crossed Stage-5 agentic boundary" }
if ($health.stage4_7_execution_intake_enabled -or $health.stage4_7_tool_invocation_enabled) { throw "Stage 4.7 crossed execution boundary" }
if ($health.stage4_7_external_network_io_performed -or $health.stage4_7_target_actuation) { throw "Stage 4.7 performed prohibited target interaction" }
if ($health.stage4_7_authorization_minting_enabled) { throw "Stage 4.7 must not mint authorization" }
if ($health.stage4_7_next_stage -ne "4.8") { throw "Stage 4.7 next-stage mismatch" }
Write-Host "[PASS] Stage 4.7 active, migration 5, registry/tool contracts read-only"

Write-Host "`n[2] Stage 4.6 workflow predecessor remains canonical and active projection advances to Stage 4.7"
$workflow = Invoke-RestMethod "$PentestUrl/api/pentest/workflow-contract"
if ($workflow.control_version -ne $ExpectedWorkflowControl) { throw "Historical Stage 4.6 control mismatch" }
if ($workflow.active_control_version -ne $ExpectedControl) { throw "Active control projection mismatch" }
if (-not $workflow.capability_registry_enabled -or -not $workflow.tool_contract_enabled) { throw "Stage 4.7 registry/tool availability not projected through workflow route" }
if ($workflow.capability_selection_enabled -or $workflow.tool_invocation_enabled -or $workflow.target_actuation) { throw "Workflow route crossed Stage 4.7 safety boundary" }
if ($workflow.definition.capability_registry_enabled) { throw "Historical Stage 4.6 canonical definition was mutated" }
Write-Host "[PASS] Stage 4.6 remains immutable while Stage 4.7 is active"

Write-Host "`n[3] Canonical Stage 4.7 control contract"
$contract = Invoke-RestMethod "$PentestUrl/api/pentest/capability-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "Stage 4.7 contract route control mismatch" }
if ($contract.definition.schema_version -ne $ExpectedSchema) { throw "Stage 4.7 definition schema mismatch" }
if ($contract.definition.registry_schema_version -ne $ExpectedRegistrySchema) { throw "Stage 4.7 registry schema mismatch" }
if ($contract.definition.predecessor_control -ne $ExpectedWorkflowControl) { throw "Stage 4.7 predecessor mismatch" }
if ([int]$contract.definition.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 4.7 repository migration mismatch" }
if ([int]$contract.definition.capability_count -ne 7 -or [int]$contract.definition.tool_count -ne 8 -or [int]$contract.definition.mapping_count -ne 8) { throw "Stage 4.7 definition count mismatch" }
if (-not $contract.capability_registry_enabled -or -not $contract.tool_contract_enabled -or -not $contract.tool_capability_mapping_enabled) { throw "Stage 4.7 contract features not enabled" }
if ($contract.capability_selection_enabled -or $contract.execution_intake_enabled -or $contract.tool_invocation_enabled -or $contract.target_actuation) { throw "Stage 4.7 control contract crossed execution boundary" }
Write-Host "[PASS] Stage 4.7 control contract is canonical and non-executing"

Write-Host "`n[4] Persisted canonical registry"
$registryResponse = Invoke-RestMethod "$PentestUrl/api/pentest/capability-registry"
$registry = $registryResponse.registry
if ($registryResponse.source_of_truth -ne "PENTEST_SUBSYSTEM_DATABASE") { throw "registry source-of-truth mismatch" }
if ([int]$registry.counts.capabilities -ne 7 -or [int]$registry.counts.tools -ne 8 -or [int]$registry.counts.mappings -ne 8) { throw "registry persisted counts mismatch" }
$capIds = @($registry.capabilities | ForEach-Object { $_.identity.capability_id })
$toolIds = @($registry.tools | ForEach-Object { $_.identity.tool_id })
if (($capIds -join ",") -ne ($ExpectedCapabilities -join ",")) { throw "capability registry identity/order mismatch: $($capIds -join ',')" }
if (($toolIds -join ",") -ne ($ExpectedTools -join ",")) { throw "tool registry identity/order mismatch: $($toolIds -join ',')" }
if (-not $registry.semantics.registry_read_only) { throw "registry must be read-only" }
if ($registry.semantics.capability_selection_enabled -or $registry.semantics.tool_invocation_enabled -or $registry.semantics.target_actuation) { throw "registry semantics crossed runtime boundary" }
Write-Host "[PASS] canonical registry persisted with 7 capabilities / 8 logical tools / 8 mappings"

Write-Host "`n[5] Capability contract completeness"
$capabilityList = Invoke-RestMethod "$PentestUrl/api/pentest/capabilities"
if ([int]$capabilityList.count -ne 7) { throw "capability list count mismatch" }
foreach ($capability in @($capabilityList.capabilities)) {
    if (-not $capability.schemas.input_schema.schema_version) { throw "capability missing input schema: $($capability.identity.capability_id)" }
    if (-not $capability.schemas.output_schema.schema_version) { throw "capability missing output schema: $($capability.identity.capability_id)" }
    if (-not $capability.permission.requirement) { throw "capability missing permission requirement: $($capability.identity.capability_id)" }
    if (-not $capability.classification.safety_class) { throw "capability missing safety class: $($capability.identity.capability_id)" }
    if (@($capability.tools.requirements).Count -lt 1) { throw "capability missing tool requirement: $($capability.identity.capability_id)" }
    if ($capability.permission.registry_grants_permission) { throw "registry granted permission: $($capability.identity.capability_id)" }
    if ($capability.tools.tool_invocation_enabled) { throw "capability contract enabled tool invocation: $($capability.identity.capability_id)" }
}
Write-Host "[PASS] every capability declares input/output schema, permission, tool requirement, and safety class"

Write-Host "`n[6] Tool contracts remain logical and non-callable"
$toolList = Invoke-RestMethod "$PentestUrl/api/pentest/tools"
if ([int]$toolList.count -ne 8) { throw "tool list count mismatch" }
foreach ($tool in @($toolList.tools)) {
    if (-not $tool.runtime.logical_contract_only) { throw "tool is not logical-contract-only: $($tool.identity.tool_id)" }
    if ($tool.runtime.adapter_bound -or $tool.runtime.runtime_endpoint_bound -or $tool.runtime.binary_or_command_bound -or $tool.runtime.credential_binding_present -or $tool.runtime.invocation_enabled) { throw "tool obtained runtime binding: $($tool.identity.tool_id)" }
    if ($tool.semantics.direct_raw_target_access -or $tool.semantics.shell_access_exposed -or $tool.semantics.target_actuation) { throw "tool exposes prohibited raw execution surface: $($tool.identity.tool_id)" }
}
Write-Host "[PASS] logical tool registry exposes no binary, command, credential, shell, or raw target access"

Write-Host "`n[7] Enumeration capability-to-tool mapping"
$enumTools = Invoke-RestMethod "$PentestUrl/api/pentest/capabilities/enumeration/tools"
$enumToolIds = @($enumTools.tools | ForEach-Object { $_.identity.tool_id })
if (($enumToolIds -join ",") -ne "pentest.tool.network_discovery,pentest.tool.service_enumerator") { throw "enumeration tool mapping mismatch: $($enumToolIds -join ',')" }
if ($enumTools.tool_invocation_performed -or $enumTools.target_actuation) { throw "mapping query invoked a tool" }
Write-Host "[PASS] deterministic enumeration mapping resolved without invocation"

Write-Host "`n[8] High-risk exploitation contract remains deferred to controlled execution"
$exploit = Invoke-RestMethod "$PentestUrl/api/pentest/capabilities/exploitation"
if ($exploit.capability.classification.safety_class -ne "HIGH_RISK_CONTROLLED") { throw "exploitation safety class mismatch" }
if ($exploit.capability.permission.requirement -ne "EXPLICIT_GOVERNANCE_ALLOW_AND_STAGE6_EXECUTION_GATEWAY_REQUIRED") { throw "exploitation permission requirement mismatch" }
if ($exploit.tools[0].identity.tool_id -ne "pentest.tool.exploitation_adapter") { throw "exploitation logical tool mapping mismatch" }
if (-not $exploit.tools[0].runtime.stage6_authorized_adapter_required) { throw "exploitation tool does not require Stage 6 authorized adapter" }
if ($exploit.tools[0].runtime.binary_or_command_bound -or $exploit.tools[0].runtime.invocation_enabled) { throw "exploitation tool exposes executable binding" }
Write-Host "[PASS] exploitation is registered as a contract only, not an executable tool surface"

Write-Host "`n[9] Execution-intake negative boundary"
$dispatchRejected = $false
$errorCode = $null
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{"capability_id":"exploitation"}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) {
        $dispatchRejected = $true
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $body = $reader.ReadToEnd() | ConvertFrom-Json
            $errorCode = $body.error_code
            if (-not $body.capability_registry_enabled -or -not $body.tool_contract_enabled) { throw "dispatch rejection did not acknowledge Stage 4.7 registry/tool contract" }
            if ($body.capability_selection_enabled -or $body.execution_started -or $body.tool_invocation_performed -or $body.target_actuation) { throw "dispatch rejection crossed execution boundary" }
        } catch { }
    } else { throw }
}
if (-not $dispatchRejected) { throw "Stage 4.7 execution dispatch was not rejected with HTTP 409" }
if ($errorCode -and $errorCode -ne "STAGE4_7_EXECUTION_INTAKE_NOT_ENABLED") { throw "unexpected dispatch rejection code: $errorCode" }
Write-Host "[PASS] execution dispatch remains disabled and fail-closed"

Write-Host "`n[10] Python compilation"
python -m compileall -q mission_orchestrator pentest_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[11] Canonical test inventory"
$collect = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[12] Focused Stage 4.7 regression"
python -m pytest -q tests/test_stage4_7_capability_registry_tool_contract.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.7 focused regression failed" }

Write-Host "`n[13] Stage 4.1 -> 4.7 regression"
python -m pytest -q `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py `
  tests/test_stage4_4_pentest_lifecycle_state.py `
  tests/test_stage4_5_pentest_event_runtime_contract.py `
  tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py `
  tests/test_stage4_7_capability_registry_tool_contract.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.1-4.7 regression failed" }

Write-Host "`n[14] Critical Stage 3 + Stage 4 predecessor regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage3_4_1_canonical_subsystem_registry_capability_contract.py `
  tests/test_stage3_2_3_mission_pip_activation.py `
  tests/test_stage3_1_3_scope_roe_constraint_contract.py `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py `
  tests/test_stage4_4_pentest_lifecycle_state.py `
  tests/test_stage4_5_pentest_event_runtime_contract.py `
  tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py `
  tests/test_stage4_7_capability_registry_tool_contract.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.7 critical predecessor regression failed" }

Write-Host "`n[15] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 4.7 Capability Registry & Tool Contract"
Write-Host "control_version  : $ExpectedControl"
Write-Host "mission migration: $ExpectedMissionMigration"
Write-Host "pentest migration: $ExpectedPentestMigration"
Write-Host "inventory        : $ExpectedInventory"
Write-Host "predecessor      : Stage 4.6 Pentest Workflow Orchestrator Skeleton"
Write-Host "registry         : 7 capabilities / 8 logical tools / 8 mappings"
Write-Host "semantics        : registry + tool contracts only; no selection/invocation/target actuation"
Write-Host "next             : Stage 4.8 - Governance, Scope & Rules-of-Engagement Enforcement"
Write-Host "=============================================================================="
