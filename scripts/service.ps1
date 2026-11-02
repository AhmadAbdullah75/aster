param([ValidateSet('api','worker','web')][string]$Service)
$ErrorActionPreference = 'Stop'
$NexusPython = (& python -c 'import sys; print(sys._base_executable)').Trim()
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$env:PYTHONPATH = Join-Path $root 'apps/api'
if ($Service -eq 'api') { & $NexusPython -m uv run python -m nexus.server }
elseif ($Service -eq 'worker') { & $NexusPython -m uv run python -m nexus.worker }
else { pnpm --dir apps/web start }
exit $LASTEXITCODE
