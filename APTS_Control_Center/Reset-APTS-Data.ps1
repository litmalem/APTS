param([string]$MissionRoot='D:\APTS\mission_orchestrator',[string]$GssRoot='D:\APTS\aptsGS',[string]$WtpRoot='D:\APTS\WebTechnologyProfiler',[string]$VulndeskRoot='D:\APTS\vulndesk')
$ErrorActionPreference='Stop'
$gssPython=Join-Path $GssRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $gssPython)) { $gssPython='python' }
$vulndeskPython=Join-Path $VulndeskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $vulndeskPython)) { $vulndeskPython=$gssPython }
& $gssPython (Join-Path $PSScriptRoot 'reset_apts.py') --mission-root $MissionRoot --gss-root $GssRoot --wtp-root $WtpRoot --vulndesk-root $VulndeskRoot --vulndesk-python $vulndeskPython --service-port 8765 --service-port 8770 --service-port 8780 --service-port 8790 --service-port 8791 --service-port 8792 --service-port 8801 --service-port 8802
if ($LASTEXITCODE -ne 0) { throw 'Reset gagal. Periksa pesan dan folder backup.' }
