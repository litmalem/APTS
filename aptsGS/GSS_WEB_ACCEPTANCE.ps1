param([switch]$Database)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$pythonPath = if (Test-Path '.\.venv\Scripts\python.exe') { '.\.venv\Scripts\python.exe' } else { 'python' }
if ($Database) {
    & $pythonPath '.\scripts\web_console_acceptance.py' --database
} else {
    & $pythonPath '.\scripts\web_console_acceptance.py'
}
if ($LASTEXITCODE -ne 0) { throw 'GSS Web acceptance gagal. Periksa output pengujian.' }
