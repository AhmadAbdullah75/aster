param([ValidatePattern('^[a-zA-Z0-9-]+$')][string]$RunId = 'focused-edge-01', [switch]$RecoveryOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$output = "artifacts/prepublication/$RunId"
if (Test-Path -LiteralPath $output) { throw 'Use a fresh RunId to preserve evidence.' }
New-Item -ItemType Directory -Path $output | Out-Null
$env:PYTHONPATH = Join-Path (Get-Location) 'apps/api'
$env:NEXUS_LIVE_PREPUBLICATION = 'false'
$env:NEXUS_E2E_PRODUCTION = 'true'
$env:NEXUS_E2E_PRODUCTION_DIR = '.next-e2e'
Remove-Item Env:NEXUS_E2E_QUEUE_ONLY -ErrorAction SilentlyContinue
Remove-Item Env:NEXUS_E2E_SUPERVISE -ErrorAction SilentlyContinue
if (-not $RecoveryOnly) {
python -m uv run pytest -q apps/api/tests/test_prepublication_auth.py apps/api/tests/test_prepublication_security.py apps/api/tests/test_prepublication_documents.py apps/api/tests/test_prepublication_approval_safety.py apps/api/tests/test_prepublication_project_defaults.py apps/api/tests/test_prepublication_provider.py
if ($LASTEXITCODE -ne 0) { throw 'Focused backend checks failed' }
node node_modules/@playwright/test/cli.js test tests/e2e/prepublication-auth.spec.ts tests/e2e/prepublication-documents.spec.ts tests/e2e/prepublication-approval.spec.ts tests/e2e/prepublication-approval-lifecycle.spec.ts tests/e2e/prepublication-stream-recovery.spec.ts tests/e2e/prepublication-projects.spec.ts tests/e2e/prepublication-provider.spec.ts tests/e2e/prepublication-upload-cancel.spec.ts --grep 'SES-|LOG-10|UPL-04|UPL-12|UPL-15|PRS parser|APR-08|APR-09|APS-07|APS-09|APS-12|STR-02|STR-07|PRJ-01|PRJ-11|PRV-03|LIM-17|UPL-17' --output "$output/browser-traces"
if ($LASTEXITCODE -ne 0) { throw 'Focused browser checks failed' }
$env:NEXUS_E2E_QUEUE_ONLY = 'true'
node node_modules/@playwright/test/cli.js test tests/e2e/prepublication-stop.spec.ts tests/e2e/prepublication-composer.spec.ts tests/e2e/prepublication-scope.spec.ts --output "$output/queue-traces"
if ($LASTEXITCODE -ne 0) { throw 'Focused cancellation and input boundary checks failed' }
}
$env:NEXUS_E2E_QUEUE_ONLY = 'true'
$env:NEXUS_E2E_SUPERVISE = 'true'
node node_modules/@playwright/test/cli.js test tests/e2e/prepublication-ops.spec.ts --grep 'WRK-04|WRK-05|WRK-01|WRK-08|WRK-09' --output "$output/recovery-traces"
if ($LASTEXITCODE -ne 0) { throw 'Focused restart checks failed' }
Write-Output 'Focused edge regression completed successfully. Reused earlier full-suite results; no full-suite or hour-load signoff implied.'

