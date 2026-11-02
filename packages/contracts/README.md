# API contracts

From the repository root:

```powershell
python -m uv run python scripts/contracts.py
pnpm exec openapi-typescript packages/contracts/openapi.json -o packages/contracts/schema.d.ts
```

The generated contract contains concrete request schemas from FastAPI. `apps/web/src/lib/types.ts`
describes application projections and `docs/events.md` specifies the durable event envelope.
Regenerate after changing routes/schemas. No API key is read into or emitted by this generator.
