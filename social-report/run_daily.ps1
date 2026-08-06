$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $projectDir "logs"
$logFile = Join-Path $logDir ("daily-report-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Set-Location -LiteralPath $projectDir

try {
    & py -3.12 -u (Join-Path $projectDir "run_daily.py") *>> $logFile
    exit $LASTEXITCODE
}
catch {
    $_ | Out-String | Add-Content -LiteralPath $logFile -Encoding utf8
    exit 1
}
