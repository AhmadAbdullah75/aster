$ErrorActionPreference = 'Stop'
$watchRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $watchRoot
$watchRecordPath = Join-Path $watchRoot 'artifacts/prepublication/quota-watch-process.json'
$watchState = Get-Content -LiteralPath 'artifacts/prepublication/results.json' -Raw | ConvertFrom-Json
if ($watchState.halt -or $watchState.external_blocker -or (Test-Path -LiteralPath 'artifacts/prepublication/quota-stop.json') -or (Test-Path -LiteralPath 'artifacts/prepublication/quota-watch.stop')) {
  throw 'An existing quota or external stop flag prevents watcher renewal. Resolve that recorded stop first.'
}
if (Test-Path -LiteralPath $watchRecordPath) {
  $watchRecord = Get-Content -LiteralPath $watchRecordPath -Raw | ConvertFrom-Json
  $watchOldProcess = Get-Process -Id $watchRecord.WatcherPID -ErrorAction SilentlyContinue
  if ($watchOldProcess) {
    $watchOldInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($watchRecord.WatcherPID)"
    $watchOldStart = if ($watchRecord.Started -is [DateTime]) { $watchRecord.Started.ToUniversalTime() } else { [DateTimeOffset]::Parse([string]$watchRecord.Started).UtcDateTime }
    if (-not $watchOldInfo.CommandLine.Contains('prepublication_quota_watch.py') -or [Math]::Abs(($watchOldProcess.StartTime.ToUniversalTime() - $watchOldStart).TotalSeconds) -gt 2) {
      throw 'Existing watcher identity does not match its record; no process stopped.'
    }
    Stop-Process -Id $watchRecord.WatcherPID
  }
}
$watchPython = (& python -c 'import sys; print(sys._base_executable)').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Python is unavailable in this terminal.' }
$watchStamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff')
$watchNewProcess = Start-Process -FilePath $watchPython -ArgumentList @('-u','scripts/prepublication_quota_watch.py') -WorkingDirectory $watchRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $watchRoot ".data/logs/quota-watch-$watchStamp.out.log") -RedirectStandardError (Join-Path $watchRoot ".data/logs/quota-watch-$watchStamp.err.log") -PassThru
@{ WatcherPID=$watchNewProcess.Id; Started=$watchNewProcess.StartTime.ToUniversalTime().ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $watchRecordPath
Write-Output "Quota watcher started (PID $($watchNewProcess.Id)); no API calls or key changes were made."
