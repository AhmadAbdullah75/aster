$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$recordPath = Join-Path $root '.data/processes.json'
if (Test-Path -LiteralPath $recordPath) {
  foreach ($record in (Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json)) {
    $process = Get-Process -Id $record.id -ErrorAction SilentlyContinue
    $info = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.id)" -ErrorAction SilentlyContinue
    $recordTime = if ($record.start -is [DateTime]) { $record.start.ToUniversalTime() } else { [DateTimeOffset]::Parse([string]$record.start).UtcDateTime }
    if ($process -and $info.CommandLine -and $info.CommandLine.Contains((Join-Path $PSScriptRoot 'service.ps1')) -and ([Math]::Abs(($process.StartTime.ToUniversalTime() - $recordTime).TotalSeconds) -lt 2)) {
      # Stop the verified service wrapper and descendants; no unrelated process enumeration.
      & taskkill /PID $record.id /T /F | Out-Null
    }
  }
  Remove-Item -LiteralPath $recordPath
}
Write-Output 'Aster services stopped. PostgreSQL data is retained; docker compose stop postgres stops the database.'
