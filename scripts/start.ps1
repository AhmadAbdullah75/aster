param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$NexusPython = (& python -c 'import sys; print(sys._base_executable)').Trim()
$root = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $root
try {
  if (-not (Test-Path -LiteralPath '.env')) { throw 'Run scripts/setup.ps1 first.' }
  foreach ($port in @(3000,8000)) {
    $socket = [Net.Sockets.TcpClient]::new()
    try { $socket.Connect('127.0.0.1',$port); $occupied=$true } catch { $occupied=$false } finally { $socket.Dispose() }
    if ($occupied) { throw "Port $port is already in use. Stop existing native services with scripts/stop.ps1 or stop the Compose web/API before starting again." }
  }
  docker compose up -d postgres --wait
  if ($LASTEXITCODE -ne 0) { throw 'Docker unavailable. Start Docker Desktop, or use native commands in README with an existing PostgreSQL database.' }
  $env:PYTHONPATH = Join-Path $root 'apps/api'
  & $NexusPython -m uv run alembic upgrade head
  if ($LASTEXITCODE -ne 0) { throw 'Application migration failed' }
  & $NexusPython -m uv run python -m nexus.migrate_graph
  if ($LASTEXITCODE -ne 0) { throw 'Graph migration failed' }
  if (-not $SkipBuild) {
    pnpm build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
  }
  $logDir = Join-Path $root '.data/logs'
  New-Item -ItemType Directory -Path $logDir -Force | Out-Null
  $records = @()
  foreach ($service in @('api','worker','web')) {
    $process = Start-Process -FilePath 'pwsh' -ArgumentList @('-NoProfile','-File',('"' + (Join-Path $PSScriptRoot 'service.ps1') + '"'),'-Service',$service) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "$service.out.log") -RedirectStandardError (Join-Path $logDir "$service.err.log") -PassThru
    $records += @{ id=$process.Id; service=$service; start=$process.StartTime.ToUniversalTime().ToString('o') }
  }
  $records | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root '.data/processes.json')
  $ready = $false
  for ($attempt=0; $attempt -lt 40; $attempt++) {
    foreach ($record in $records) { if (-not (Get-Process -Id $record.id -ErrorAction SilentlyContinue)) { throw "The $($record.service) service exited. Inspect .data/logs." } }
    try { $health=Invoke-RestMethod 'http://127.0.0.1:8000/health/ready'; $web=Invoke-WebRequest 'http://127.0.0.1:3000' -TimeoutSec 2; if ($health.database -and $web.StatusCode -eq 200) { $ready=$true; break } } catch {}
    Start-Sleep -Seconds 1
  }
  if (-not $ready) { throw 'Services did not become ready. Inspect .data/logs.' }
  Write-Output 'Aster is running at http://127.0.0.1:3000. API docs: http://127.0.0.1:8000/docs'
} finally { Pop-Location }
