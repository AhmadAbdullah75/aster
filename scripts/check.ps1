param([ValidatePattern('^[a-zA-Z0-9-]+$')][string]$RunId = ('check-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff')))
$ErrorActionPreference = 'Stop'
$NexusPython = (& python -c 'import sys; print(sys._base_executable)').Trim()
$root = Split-Path -Parent $PSScriptRoot
$NexusPreviousQueueOnly = $env:NEXUS_E2E_QUEUE_ONLY
$NexusPreviousLiveChecks = $env:NEXUS_LIVE_PREPUBLICATION
$NexusPreviousSupervisor = $env:NEXUS_E2E_SUPERVISE
$NexusPreviousNextDirectory = $env:NEXUS_NEXT_DIR
$NexusPreviousProductionDirectory = $env:NEXUS_E2E_PRODUCTION_DIR
$NexusPreviousProduction = $env:NEXUS_E2E_PRODUCTION
$NexusPreviousLowMemory = $env:NEXUS_LOW_MEMORY_BUILD
Push-Location -LiteralPath $root
try {
  $NexusTraceRoot = "artifacts/prepublication/$RunId"
  if (Test-Path -LiteralPath $NexusTraceRoot) { throw 'This verification artifact directory already exists; choose a new RunId to preserve earlier evidence.' }
  New-Item -ItemType Directory -Path $NexusTraceRoot -ErrorAction Stop | Out-Null
  $env:NEXUS_LIVE_PREPUBLICATION = 'false'
  # Rebuilding verification assets must not invalidate the running native app.
  $env:NEXUS_NEXT_DIR = '.next-e2e'
  $env:NEXUS_E2E_PRODUCTION_DIR = '.next-e2e'
  $env:NEXUS_LOW_MEMORY_BUILD = 'true'
  Remove-Item Env:NEXUS_E2E_SUPERVISE -ErrorAction SilentlyContinue
  Remove-Item Env:NEXUS_E2E_QUEUE_ONLY -ErrorAction SilentlyContinue
  $env:PYTHONPATH = Join-Path $root 'apps/api'
  & $NexusPython -m uv run ruff check apps/api tests/e2e
  if ($LASTEXITCODE -ne 0) { throw 'Ruff failed' }
  & $NexusPython -m unittest discover -s tests/safety -v
  if ($LASTEXITCODE -ne 0) { throw 'Resource guard tests failed' }
  & $NexusPython -m uv run mypy apps/api/nexus
  if ($LASTEXITCODE -ne 0) { throw 'Python types failed' }
  & $NexusPython -m uv run pytest -q
  if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
  foreach ($check in @('lint','typecheck','test','build','e2e')) {
    if ($check -eq 'e2e') {
      $env:NEXUS_E2E_PRODUCTION = 'true'
      pnpm $check --output "$NexusTraceRoot/browser-traces"
    } elseif ($check -eq 'test') { pnpm $check --maxWorkers=1 }
    else { pnpm $check }
    if ($LASTEXITCODE -ne 0) { throw "$check failed" }
  }
  # These cases need the real run-creation API enabled without any provider access.
  # The flag is consumed only by the isolated nexus_e2e server, never by the app.
  $env:NEXUS_E2E_QUEUE_ONLY = 'true'
  pnpm exec playwright test tests/e2e/prepublication-composer.spec.ts tests/e2e/prepublication-stop.spec.ts tests/e2e/prepublication-scope.spec.ts --output "$NexusTraceRoot/queue-traces"
  if ($LASTEXITCODE -ne 0) { throw 'Queue-only browser boundary tests failed' }
  $env:NEXUS_E2E_SUPERVISE = 'true'
  pnpm exec playwright test tests/e2e/prepublication-ops.spec.ts --output "$NexusTraceRoot/ops-traces"
  if ($LASTEXITCODE -ne 0) { throw 'Isolated process-recovery browser tests failed' }
  Remove-Item Env:NEXUS_E2E_SUPERVISE
  Remove-Item Env:NEXUS_E2E_QUEUE_ONLY
  Write-Output 'All deterministic verification commands passed. Live provider suite is separate.'
} finally {
  if ($null -eq $NexusPreviousQueueOnly) { Remove-Item Env:NEXUS_E2E_QUEUE_ONLY -ErrorAction SilentlyContinue } else { $env:NEXUS_E2E_QUEUE_ONLY = $NexusPreviousQueueOnly }
  if ($null -eq $NexusPreviousLiveChecks) { Remove-Item Env:NEXUS_LIVE_PREPUBLICATION -ErrorAction SilentlyContinue } else { $env:NEXUS_LIVE_PREPUBLICATION = $NexusPreviousLiveChecks }
  if ($null -eq $NexusPreviousSupervisor) { Remove-Item Env:NEXUS_E2E_SUPERVISE -ErrorAction SilentlyContinue } else { $env:NEXUS_E2E_SUPERVISE = $NexusPreviousSupervisor }
  if ($null -eq $NexusPreviousNextDirectory) { Remove-Item Env:NEXUS_NEXT_DIR -ErrorAction SilentlyContinue } else { $env:NEXUS_NEXT_DIR = $NexusPreviousNextDirectory }
  if ($null -eq $NexusPreviousProductionDirectory) { Remove-Item Env:NEXUS_E2E_PRODUCTION_DIR -ErrorAction SilentlyContinue } else { $env:NEXUS_E2E_PRODUCTION_DIR = $NexusPreviousProductionDirectory }
  if ($null -eq $NexusPreviousProduction) { Remove-Item Env:NEXUS_E2E_PRODUCTION -ErrorAction SilentlyContinue } else { $env:NEXUS_E2E_PRODUCTION = $NexusPreviousProduction }
  if ($null -eq $NexusPreviousLowMemory) { Remove-Item Env:NEXUS_LOW_MEMORY_BUILD -ErrorAction SilentlyContinue } else { $env:NEXUS_LOW_MEMORY_BUILD = $NexusPreviousLowMemory }
  Pop-Location
}
