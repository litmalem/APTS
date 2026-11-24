param(
    [string]$MissionRoot = 'D:\mission_orchestrator'
)
$ErrorActionPreference = 'Stop'
$PatchRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $MissionRoot 'mission_orchestrator\api_service.py'))) {
    throw "Target folder does not look like a Mission Orchestrator checkout: $MissionRoot"
}
$timeLabel = (Get-Date).ToString('yyyyMMdd-HHmmss')
$backup = Join-Path $MissionRoot ("_backup_archive_p1_" + $timeLabel)
$files = @(
    'mission_orchestrator\repository.py',
    'mission_orchestrator\service.py',
    'mission_orchestrator\api_service.py',
    'mission_orchestrator\archive_mission.py',
    'mission_web\app.js',
    'mission_web\app.css',
    'tests\test_archive_feature_p1.py',
    'tests\test_archive_http_p1.py'
)
Write-Host 'IMPORTANT: Stop Mission API and APTS Control Center before installing.'
foreach ($rel in $files) {
    $src = Join-Path $PatchRoot $rel
    $dest = Join-Path $MissionRoot $rel
    if (-not (Test-Path $src)) { throw "Missing patch source: $src" }
    if (Test-Path $dest) {
        $backupDest = Join-Path $backup $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $backupDest -Parent) | Out-Null
        Copy-Item -LiteralPath $dest -Destination $backupDest -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
    Copy-Item -LiteralPath $src -Destination $dest -Force
    Write-Host "Patched $rel"
}
Write-Host "Source backup: $backup"
Write-Host 'No database contents, existing .env, or evidence files were copied or replaced.'
Write-Host 'Configure MISSION_ARCHIVE_ADMIN_TOKEN BEFORE starting the Mission API.'
