param()
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskOutput = Join-Path $taskRoot 'experiments\zrc_mace_round1'
$taskRunner = Join-Path $PSScriptRoot 'run_zrc_md_campaign.py'
$taskConda = 'C:\Users\admin\anaconda3\Scripts\conda.exe'
if (Test-Path -LiteralPath (Join-Path $taskOutput 'STOP')) {
    throw 'A STOP marker is present. Preserve the requested stop until the user resumes.'
}
$taskExisting = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
    $_.CommandLine -match 'run_zrc_md_campaign\.py["\s]+run(?:\s|$)'
})
if ($taskExisting.Count -gt 0) {
    [pscustomobject]@{ status = 'already_running'; process_ids = @($taskExisting.ProcessId) } | ConvertTo-Json
    exit 0
}
New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
$taskStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$taskStdout = Join-Path $taskOutput "worker-$taskStamp.stdout.log"
$taskStderr = Join-Path $taskOutput "worker-$taskStamp.stderr.log"
$taskArguments = @('run', '--no-capture-output', '-n', 'base', 'python', '-u', ('"' + $taskRunner + '"'), 'run')
$taskProcess = Start-Process -FilePath $taskConda -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput $taskStdout -RedirectStandardError $taskStderr -PassThru
$taskRecord = [pscustomobject]@{
    status = 'launched'
    launcher_pid = $taskProcess.Id
    launched_utc = (Get-Date).ToUniversalTime().ToString('o')
    stdout = $taskStdout
    stderr = $taskStderr
    runner = $taskRunner
    note = 'Inspect runtime.json and summary.json for the actual worker and completion.'
}
$taskRecord | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskOutput 'last-launch.json') -Encoding utf8
$taskRecord | ConvertTo-Json
