# Testing Aster

Prerequisites: PostgreSQL with pgvector, Python 3.12, Node 24+, pnpm, and installed dependencies.
Start Docker Desktop and run `scripts/setup.ps1` first. Provider keys are not required for deterministic tests.

## Standard verification

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'apps/api'
uv run ruff check apps/api tests/e2e
uv run mypy apps/api/nexus
uv run pytest -q
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm exec playwright install chromium
$env:NEXUS_E2E_PRODUCTION = 'true'
pnpm exec playwright test tests/e2e/ui-refinement.spec.ts
```

`scripts/check.ps1` runs the extended pipeline, including full production browser, queue-only and
supervised recovery batches. It builds in `.next-e2e` to avoid disturbing the normal app build.
For a smaller failure-focused pass, use `scripts/check-focused-edges.ps1`.

Backend tests create/reset `nexus_test`; browser tests use `nexus_e2e`. These names must never point
to valuable user data. The database role must be able to create disposable databases. Provider fakes
are limited to tests; application retrieval, transactions, checkpoints and ownership checks remain real.
Do not run independent browser batches concurrently because they reset the same disposable database.

## Coverage

The suite covers authentication, session expiry, ownership, project/personal boundaries, persistent
conversations, parsers, upload limits, hybrid retrieval, source links, approvals, stale versions,
cancellation, worker recovery, memory, streaming, PDF viewing, responsive layouts and themes.
Citation tests include grouped document references, web URLs, repair failures, fresh retrieval on
selected-document follow-ups and unauthorized source access.

The UI regression uses synthetic source responses for visual checks. Real-database graph tests
separately verify source ownership and persistence. Screenshot and trace outputs are ignored by Git.

## Optional real-provider checks

Real requests consume provider quota. Add keys privately to `.env`, use an account with billing
disabled, and stop on a real quota failure. Run these separately from deterministic tests:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'apps/api'
uv run python scripts/live_smoke.py
```

This smoke suite creates a disposable `nexus_live_smoke` database and cleans it up. Read the script
before running; it refuses to overwrite an existing smoke database. Additional diagnostic scripts
under `scripts/prepublication_*` support bounded performance and recovery measurements. They are
retained because test and safety fixtures depend on them; generated ledgers belong in ignored artifacts.

## Limits of the evidence

Before publishing, run `uv run python scripts/check_repository.py`. It scans publishable files
and historical Git blobs for configured secrets and common API-key patterns, reports only paths,
and checks ignore rules. This is a useful automated check, not a guarantee that no sensitive data
exists. The GitHub workflow repeats deterministic backend/frontend checks using an isolated CI database.

The verified product scope is local desktop use. Public deployment, physical mobile devices and
Safari are not verified. Controlled load tests do not establish external-provider capacity. Test passes
do not guarantee arbitrary AI answers are factually correct. Raw local reports are intentionally not
part of the public repository.
