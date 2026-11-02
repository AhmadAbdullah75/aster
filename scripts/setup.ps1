$ErrorActionPreference = 'Stop'
$NexusPython = (& python -c 'import sys; print(sys._base_executable)').Trim()
$root = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $root
try {
  python scripts/init_env.py
  & $NexusPython -m uv sync --locked
  if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }
  pnpm install --frozen-lockfile
  if ($LASTEXITCODE -ne 0) { throw 'pnpm install failed' }
  docker compose up -d postgres --wait
  if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop, or configure an existing PostgreSQL/pgvector database in .env.' }
  $env:PYTHONPATH = Join-Path $root 'apps/api'
  & $NexusPython -m uv run alembic upgrade head
  if ($LASTEXITCODE -ne 0) { throw 'Application migration failed' }
  & $NexusPython -m uv run python -m nexus.migrate_graph
  if ($LASTEXITCODE -ne 0) { throw 'Graph migration failed' }
} finally { Pop-Location }
