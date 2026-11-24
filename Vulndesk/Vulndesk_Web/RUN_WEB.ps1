param([string]$VulndeskRoot = "D:\Vulndesk", [int]$Port = 8801, [switch]$Demo)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$webArguments = @("server.py", "--vulndesk-root", $VulndeskRoot, "--port", "$Port")
if ($Demo) { $webArguments += "--demo" }
& python @webArguments
exit $LASTEXITCODE
