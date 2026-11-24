param(
    [string]$MissionRoot = 'D:\mission_orchestrator',
    [string]$ControlCenterRoot = 'D:\APTS_Control_Center'
)
$ErrorActionPreference = 'Stop'
$roots = @{ Mission = $MissionRoot; ControlCenter = $ControlCenterRoot }
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw | ConvertFrom-Json
foreach ($root in $roots.Values) {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw "Folder tidak ditemukan: $root" }
}
# Validate the complete payload before replacing any installed source.
foreach ($entry in $manifest.files) {
    $source = Join-Path (Join-Path $PSScriptRoot $entry.project) $entry.path
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLower() -ne $entry.sha256) {
        throw "Checksum paket tidak cocok: $source"
    }
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
foreach ($entry in $manifest.files) {
    $root = $roots[$entry.project]
    $source = Join-Path (Join-Path $PSScriptRoot $entry.project) $entry.path
    $target = Join-Path $root $entry.path
    if (Test-Path -LiteralPath $target) {
        $backup = Join-Path (Join-Path $root "backups\mission-web-link-$stamp") $entry.path
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
        Copy-Item -LiteralPath $target -Destination $backup -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $source -Destination $target -Force
    Write-Host "Diperbarui: $target"
}
Write-Host 'Selesai. Mulai ulang START_UI.bat, nyalakan Mission, lalu muat ulang halaman Control Center.'
