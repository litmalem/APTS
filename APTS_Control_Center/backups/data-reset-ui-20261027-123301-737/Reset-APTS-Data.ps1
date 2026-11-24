param([string]$MissionRoot='D:\mission_orchestrator',[string]$GssRoot='D:\aptsGS',[string]$WtpRoot='D:\WebTechnologyProfiler')
$ErrorActionPreference='Stop'
$python=Join-Path $GssRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python='python' }
& $python (Join-Path $PSScriptRoot 'reset_apts.py') --mission-root $MissionRoot --gss-root $GssRoot --wtp-root $WtpRoot
if ($LASTEXITCODE -ne 0) { throw 'Reset gagal. Periksa pesan dan folder backup.' }
