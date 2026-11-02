# Aster

A personal AI workspace with conversations, project documents, tasks, notes and reviewable memory.
Built with Next.js, FastAPI, LangGraph, PostgreSQL and pgvector. Accounts use local passwords;
there is no email delivery, verification or OAuth service.

**Ask questions, connect private knowledge, and turn ideas into work you explicitly review.**

Aster's purpose is to keep an AI conversation connected to useful project resources without
letting the assistant silently mutate them. The browser is an interface over durable application
records, background jobs, graph checkpoints, and reviewable actions—not a temporary chat window.

[Architecture](#architecture) · [Installation](#start-on-windows) · [Configuration](#configuration-reference)
· [Usage](#use) · [Testing](#verify) · [Limitations](#examples-and-limitations)

## Features

- Persistent personal and project conversations with streamed responses.
- Private PDF, DOCX, TXT and Markdown retrieval with clickable citations.
- Tasks, notes and memory proposals reviewed before they are saved.
- Gemini chat/embeddings and optional Tavily or DuckDuckGo web search.
- Light/dark themes, local PDF preview, cancellation and durable background jobs.

Read the [project overview](docs/overview.md), [architecture](docs/architecture.md),
and [testing guide](docs/testing.md). This repository targets local desktop use;
public deployment and physical mobile-device validation are outside its verified scope.

## Architecture

```mermaid
flowchart TB
  subgraph Browser["Browser interface"]
    UI["Next.js App Router + React + TypeScript<br/>Chat, projects, documents, tasks, notes, memories, settings"]
    Render["Local PDF.js viewer<br/>Markdown, code highlighting, KaTeX"]
    UI --> Render
  end
  subgraph Web["Next.js server"]
    Proxy["Same-origin /api proxy<br/>Cookie forwarding and nonbuffered SSE"]
  end
  subgraph Backend["FastAPI application"]
    Auth["Local accounts and sessions<br/>Origin, ownership and version checks"]
    API["CRUD, uploads, runs, history<br/>Source access and approval decisions"]
    Events["Durable events<br/>Cursor replay and cancellation"]
    Auth --> API
    API --> Events
  end
  subgraph Worker["Python background worker"]
    Queue["Job claiming and leases<br/>Recovery and cancellation"]
    Graph["LangGraph StateGraph<br/>Context, model and authorized tools"]
    Ingest["Parsing, chunking<br/>Bounded embedding batches"]
    RAG["Hybrid retrieval<br/>Vector similarity plus full-text ranking"]
    Review["Persist proposal and interrupt<br/>User edits, includes/excludes, approves/rejects"]
    Execute["Resume after decision<br/>Transactional approved writes"]
    Queue --> Graph
    Queue --> Ingest
    Graph --> RAG
    Graph --> Review
    Review --> Execute
  end
  subgraph Storage["Persistent storage"]
    DB[("PostgreSQL + pgvector<br/>Accounts, resources, chunks, jobs, events, proposals")]
    State[("LangGraph PostgreSQL saver/store<br/>Checkpoints and long-term memory")]
    Blobs[("Private original document blobs")]
  end
  subgraph External["Configured external services"]
    Gemini["Gemini chat and embeddings"]
    Search["DDGS/DuckDuckGo or Tavily"]
  end
  UI -->|"requests and SSE"| Proxy
  Proxy --> Auth
  API <--> DB
  Events <--> DB
  API --> Blobs
  Queue <--> DB
  Ingest --> Blobs
  Ingest --> Gemini
  Ingest --> DB
  RAG <--> DB
  Graph <--> State
  Graph --> Gemini
  Graph --> Search
  Execute --> DB
  Execute --> State
  API -->|"review decision"| Execute
```

### Message and action lifecycle

1. FastAPI checks the authenticated owner and creates a durable run for a conversation.
2. A worker claims the run. A database constraint permits only one queued/running/waiting run per thread.
3. LangGraph combines conversation context, eligible memories, and authorized tool evidence.
4. Selected documents trigger fresh retrieval in Auto and Documents modes; Web mode explicitly starts web search.
5. Persisted text/tool events stream through the same-origin proxy; canonical history remains available after reconnecting.
6. A mutation proposal interrupts the graph. The user reviews it, and only approved included items are applied transactionally.

Tool progress describes operations, not private model reasoning. Resolved review cards disappear
from chat while saved resources and the assistant's confirmation remain. Direct form saves are
deliberate user actions and do not require a second approval.

### Retrieval, citations, and recovery

Chunks target approximately 700 tokens with 100-token overlap. Retrieval filters owner, project,
selected documents, readiness, and embedding model before fusing exact vector similarity with
PostgreSQL full-text ranking. Coverage retrieval visits sections within token/chunk/context limits.

Single and grouped source references map to exact retrieved chunk IDs or returned web URLs.
Invalid references receive one correction attempt. Unresolved document citations produce labelled
excerpts or a clear limitation instead of guessed links. Reference validity does not establish that
every model interpretation is factually correct.

Visible transcripts are separate from graph context, so context summarization does not remove
messages. Worker leases, advisory locks, and durable events support recovery. Waiting approvals
survive restart. Interrupted generation preserves partial output and requires explicit retry;
token-level continuation is not guaranteed.

### Components and repository layout

| Layer        | Technologies                                                                                   |
| ------------ | ---------------------------------------------------------------------------------------------- |
| Interface    | Next.js 16, React 19, TypeScript, Tailwind CSS, Radix UI, TanStack Query, React Hook Form, Zod |
| Rendering    | React Markdown, highlight.js, KaTeX, PDF.js                                                    |
| API/database | FastAPI, Pydantic, SQLAlchemy, psycopg, Alembic                                                |
| Agent        | LangGraph StateGraph, PostgreSQL checkpointer and store                                        |
| Retrieval    | pgvector, PostgreSQL full-text search, Gemini embeddings                                       |
| Verification | pytest, Ruff, mypy, Vitest, Testing Library, Playwright                                        |
| Tooling      | uv, pnpm, Docker Compose, GitHub Actions                                                       |

```text
apps/api/nexus/         API, graph, tools, actions, RAG, memory, worker
apps/api/migrations/    Alembic database migrations
apps/api/tests/         Backend and real-database graph regressions
apps/web/src/app/       Routes, streaming proxy, styles
apps/web/src/components/ Workspace, Markdown, PDF preview, UI primitives
apps/web/src/lib/       Browser API client, types, SSE parser
packages/contracts/    OpenAPI and generated TypeScript contracts
docs/                  Architecture, security, testing, synthetic examples
scripts/               Setup/start/stop and verification helpers
tests/e2e/             Browser tests and deterministic worker fixtures
tests/safety/          Resource/quota guard tests
.github/workflows/     CI backend/frontend checks
```

Internal package/database identifiers retain `nexus` for compatibility with existing installations.
The product is Aster. Exact dependency versions are pinned in `uv.lock` and `pnpm-lock.yaml`.

## Start on Windows

Prerequisites: Git, Python 3.12 (currently >=3.12,<3.13), Node 24+, pnpm 11.25.0,
PowerShell 7 (`pwsh`), and Docker Desktop running Linux containers.
Clone the repository into a folder of your choice and run commands from its root.

```powershell
python -m pip install uv
npm install --global pnpm@11.25.0
git clone https://github.com/AhmadAbdullah75/aster.git
Set-Location aster
pwsh -File scripts/setup.ps1
pwsh -File scripts/start.ps1
```

Open [Aster](http://127.0.0.1:3000). Register your own account.
Setup generates `.env` with random local database and session secrets, without printing them or overwriting an existing file.
For AI, create a free-tier key in [Google AI Studio](https://aistudio.google.com/api-keys), keep billing disabled, and add it **directly** to `GEMINI_API_KEY` in the root `.env`; never paste it into chat.
Then restart the API and worker. Without a key, accounts, projects, tasks, notes and memory management work;
chat and search are unavailable and ingestion reports a useful failure.

```powershell
pwsh -File scripts/stop.ps1
pwsh -File scripts/start.ps1 -SkipBuild
```

Stop preserves PostgreSQL and uploads. `docker compose stop postgres` stops the database too.
Logs: `.data/logs`. Data: Docker volume `nexus_nexus_pg`, blobs under `.data/blobs`.
Do not delete these to troubleshoot a service startup problem.

## Development / existing PostgreSQL

Docker is optional if an existing PostgreSQL 17+ database with the `vector` extension is available.
Set `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE` in `.env`.
Use the commands below in separate shells; this avoids the Docker-specific startup helper.
The database role needs schema migration permissions; tests also need permission to create isolated databases.

```powershell
$env:PYTHONPATH = (Join-Path $PWD 'apps/api')
python -m uv sync --locked
pnpm install --frozen-lockfile
python -m uv run alembic upgrade head
python -m uv run python -m nexus.migrate_graph
python -m uv run python -m nexus.server
# Second shell, with the same PYTHONPATH:
python -m uv run python -m nexus.worker
# Third shell:
pnpm dev
```

Windows must use `nexus.server`: it selects a psycopg-compatible selector event loop before Uvicorn starts.
The documented server binds the API to localhost. Development API docs: [FastAPI docs](http://127.0.0.1:8000/docs).
The browser always uses `/api/*`; the Next.js route streams the upstream response without buffering SSE.
All mutations require the configured `APP_ORIGIN`, default `http://127.0.0.1:3000`.
For a loopback configuration, localhost, 127.0.0.1 and [::1] aliases with the same scheme/port are accepted.
Cookies remain host-specific, so switching addresses requires signing in on the other host.

Linux/macOS can use the equivalent manual workflow:

```bash
git clone https://github.com/AhmadAbdullah75/aster.git
cd aster
python scripts/init_env.py
# Edit .env to configure your database and private provider key.
uv sync --locked
pnpm install --frozen-lockfile
docker compose up -d postgres --wait
export PYTHONPATH=apps/api
uv run alembic upgrade head
uv run python -m nexus.migrate_graph
uv run uvicorn nexus.main:app --host 127.0.0.1 --port 8000
```

Run `PYTHONPATH=apps/api uv run python -m nexus.worker` in a second shell and `pnpm dev`
in a third. An existing PostgreSQL/pgvector server can replace the Compose database.
Windows is the primary verified host; these portable commands and CI configuration are provided
for other environments.

## Verify

```powershell
pnpm exec playwright install chromium
pwsh -File scripts/check.ps1
# Separately, after adding a provider key:
python -m uv run python scripts/live_smoke.py
```

Deterministic tests use separate `nexus_test` and `nexus_e2e` databases on the configured server,
with synthetic users and provider fakes confined to test files. They truncate those test databases.
Do not point either name at user data. The live smoke creates and cleans a separate `nexus_live_smoke`
database and makes a small bounded set of real provider requests against your selected free-tier project. It never substitutes fakes.
See the [testing guide](docs/testing.md) for test scope and reproducible commands.

Individual checks, from the repository root:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'apps/api'
uv run ruff check apps/api tests/e2e
uv run mypy apps/api/nexus
uv run pytest -q
pnpm lint
pnpm typecheck
pnpm test
pnpm build
uv run python scripts/check_repository.py
```

The latest local cleanup verification passed 262 backend tests, 5 component tests and 28 distinct
browser checks, plus a final UI rerun. Lint, types and production build passed. These are observed
local results, not a guarantee for every environment. GitHub Actions runs backend lint/types/tests
and frontend lint/types/component tests/build against isolated PostgreSQL, without private keys.
Browser checks are separate from default CI. Never run independent browser batches concurrently:
they reset the same disposable database.

## Use

Create a project, upload [the synthetic proposal](docs/example-proposal.md), and wait for `ready`.
Start a project conversation, select Documents and the proposal, ask for an explanation with citations,
then ask for a two-week task plan. Review/edit/exclude proposed tasks before approving.
No assistant-originated change is applied before review. Direct form saves are deliberate user actions.

- PDF, DOCX, UTF-8 TXT and Markdown: 10 MiB/file, 200 MiB/account by default. The browser checks the configured file limit before upload; the API enforces it independently.
- PDFs open inside Aster with page navigation, zoom, accessible page text, and an original-file download. Mozilla PDF.js and its worker/fonts are served locally; no external viewer or CDN is required.
- PDF limit 500 pages; extraction limit two million characters; DOCX decompression is bounded.
- Scanned PDFs require OCR, which this version does not implement.
- Whole-document coverage is bounded; covered/total metadata identifies omissions and narrower follow-ups may be needed.
- Due dates are calendar dates in your configured timezone, initially Asia/Karachi; timestamps are UTC.
- Disable or delete memory in Memories/Settings. Forgetting durable memory keeps the visible transcript.
- Stop explicitly cancels work. Navigating away does not. Provider streams interrupted by a worker crash
  retain partial text and require an explicit new message, rather than promising token-level resumption.
- Deleting a project deletes its conversations, documents, tasks, notes and project-specific memories.

### Personal versus project scope

| Scope        | Behavior                                                                                                                                                             |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Conversation | Separate transcript/checkpoint; empty drafts persist only after the first sent message.                                                                              |
| Personal     | Different personal threads share personal tasks, notes, and eligible memories.                                                                                       |
| Project      | New resources default to the selected conversation project; other projects retain their own resources.                                                               |
| Memory       | Personal memories can be eligible across personal/project chats; project memories are eligible only in the matching project. Disabled/deleted memories are excluded. |

### Example workflow

Upload [GreenRoute](docs/examples/GreenRoute_RAG_Test.txt), wait for Ready, and select it:

```text
Using only the selected document, calculate expected daily passenger journeys at
75% occupancy. Show the calculation and cite the source assumptions.
```

Expected synthetic result: `2 × 12 × 8 × 0.75 = 144` journeys per day.

```text
Propose three tasks: prepare the README, capture screenshots, and record a demo.
Leave due dates blank. Show them for my approval before saving.
```

Edit the review, exclude an item, and approve the selected items. Verify the result in Tasks.
A scope warning does not automatically exclude an item: the review selection controls saving.

```text
Create a note titled "Portfolio checklist" containing README, screenshots, setup
instructions, and known limitations. Show it for approval before saving.
```

Task statuses are `todo`, `in_progress`, and `done`; priorities are `low`, `medium`, and `high`.
Direct New task/New note forms are also available.

```text
I prefer short but complete explanations. Please offer to remember this preference.
```

Direct useful facts/preferences can also trigger memory proposals without “remember,” but
recognition of every possible fact is not guaranteed. Review before saving. Manage memories
individually in Memories or disable reads/proposals in Settings.

Choose Web for explicit search; Auto can also invoke web tools. Use Settings → Appearance
or the top-right toggle for themes. System follows the device. The authentication toggle stores
a local choice; after sign-in, the account preference applies. Human messages are right-aligned
with metadata below their bubble; assistant replies are left-aligned.

## Model configuration

Chat defaults to `gemini-3.5-flash-lite`; embeddings use `gemini-embedding-2` at 1536 dimensions. Web search defaults to DDGS/DuckDuckGo. To use Tavily, set `WEB_BACKEND=tavily` and add `TAVILY_API_KEY` to `.env`. Use its free account with pay-as-you-go disabled; basic search is explicitly selected. `AI_PROVIDER=gemini` and `FREE_ONLY=true` disable the optional OpenAI adapter. No automatic provider fallback exists. Keep Google project billing disabled: server code cannot inspect account billing settings.
These are separately configurable. Names were checked against official documentation; account access is a live-test concern.
No automatic fallback model is used. Change embedding configuration and explicitly reindex existing documents;
queries exclude documents indexed under a different model. Do not mix dimensions in the same schema.
All secrets stay in server configuration; no key is sent in browser configuration.

## Configuration reference

Start from [.env.example](.env.example); never commit `.env`.

| Setting                                             | Purpose/default                                                                    |
| --------------------------------------------------- | ---------------------------------------------------------------------------------- |
| AI_PROVIDER / FREE_ONLY                             | Gemini with the free-only configuration allowlist by default.                      |
| GEMINI_API_KEY                                      | Private Gemini credential; initially empty.                                        |
| GEMINI_CHAT_MODEL                                   | gemini-3.5-flash-lite in the current configuration.                                |
| GEMINI_EMBEDDING_MODEL                              | gemini-embedding-2, explicitly at 1536 dimensions.                                 |
| WEB_BACKEND / TAVILY_API_KEY                        | ddgs by default; tavily selects basic search and requires its private key.         |
| DATABASE_URL                                        | PostgreSQL/psycopg connection; native bundled database uses loopback port 5434.    |
| POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB     | Compose database settings; setup generates the password.                           |
| SESSION_SECRET                                      | Private local session configuration generated by setup.                            |
| APP_ORIGIN                                          | http://127.0.0.1:3000; used for mutation-origin checks.                            |
| DATA_DIR                                            | .data natively, /data in containers.                                               |
| UPLOAD_LIMIT_MIB / USER_QUOTA_MIB                   | 10 MiB/file and 200 MiB/account by default.                                        |
| MAX_TOOL_CALLS / MAX_OUTPUT_TOKENS / CONTEXT_TOKENS | Tool-loop, generation and context limits.                                          |
| REQUEST_TIMEOUT_SECONDS / RUN_TIMEOUT_SECONDS       | Provider request and durable-run timeout controls.                                 |
| SESSION_DAYS / COOKIE_SECURE                        | Session duration and secure-cookie setting; HTTPS deployments need secure cookies. |

External catalogs, access, quotas and billing policies can change. FREE_ONLY is configuration
validation, not a guarantee about an external account's billing enrollment. Keep paid billing
and Tavily pay-as-you-go disabled for the intended free-only use.

## Docker deployment

```powershell
python scripts/init_env.py
# Edit .env to add your private provider key before using AI features.
docker compose --profile full up --build -d
docker compose --profile full stop
```

Stop native services first to release port 3000. Compose overrides the native database hostname/port
with `postgres:5432` and uses a shared blob volume. See [deployment](docs/deployment.md).
Native blobs and the full-container blob volume are distinct locations. Back up database and
uploads consistently when changing execution modes. Volume names depend on the Compose project
name; inspect your actual configuration instead of assuming a particular folder-derived name.

## API responsibilities

The browser uses `/api/*`; the proxy forwards to FastAPI. Direct API routes below omit that prefix.

| Area                 | Representative routes                                                           |
| -------------------- | ------------------------------------------------------------------------------- |
| Accounts             | /auth/register, /auth/login, /auth/logout, /me                                  |
| Resources            | /projects, /conversations, /tasks, /notes, /memories                            |
| Runs                 | POST /conversations/{id}/runs, /runs/{id}, /runs/{id}/events, /runs/{id}/cancel |
| Review               | /proposals/{id}, POST /proposals/{id}/decision                                  |
| Documents            | /documents, /documents/{id}/retry, /documents/{id}/preview, /sources/{id}       |
| Health/configuration | /health/live, /health/ready, /capabilities                                      |

Request/response shapes are in [OpenAPI](packages/contracts/openapi.json) and
[TypeScript contracts](packages/contracts/schema.d.ts). See [events](docs/events.md) for SSE replay.

## Troubleshooting and design

- Docker pipe unavailable: start Docker Desktop; wait for its Linux engine. An existing PostgreSQL connection is supported above.
- Provider unavailable/401/403/429: check `.env`, billing, quota and configured model access; restart API/worker after edits.
- Upload `failed`: read its error; fix credentials/format, then Retry indexing. Ready documents have an explicit Reindex action.
- Run interrupted: partial output is labeled; send another message. Existing committed approved actions remain visible.
- Stale edit/approval: reload the current item; do not overwrite another saved version.
- Port occupied: stop the service using its own terminal or `scripts/stop.ps1` for tracked processes.

[Architecture](docs/architecture.md) · [Event contract](docs/events.md) · [Security](docs/security.md)
· [Testing](docs/testing.md) · [Generated contracts](packages/contracts/README.md)

## Free-tier limits

The free-only configuration is selected from [Google’s pricing](https://ai.google.dev/gemini-api/docs/pricing).
Gemini 3.5 Flash-Lite lists free chat; account-specific rate limits apply. DDGS/DuckDuckGo search requires no paid service or second key and may be rate limited by the search engine. Gemini Embedding 2 lists free text embeddings.
Quota exhaustion is reported, with no automatic model/provider upgrade. Google says free-tier content
may be used to improve its products; avoid sensitive documents on a free account.
Groq alone does not cover the embedding requirement, so Gemini is the single-key default.

The optional OpenAI adapter requires an explicit configuration change with `FREE_ONLY=false`.

## Examples and limitations

Synthetic documents for trying citations, calculations and approval workflows:
[workshop](docs/examples/Aster_RAG_Test_Document.txt) and
[shuttle pilot](docs/examples/GreenRoute_RAG_Test.txt).

Web answers can rely on incomplete or outdated search results. Check current statistics,
schedules and other changing information against the linked sources. A valid citation
identifies retrieved evidence; it does not guarantee every interpretation is correct.
If document citations cannot be repaired, Aster returns labelled excerpts or a clear limitation.
Scanned-PDF OCR, OAuth, email verification and password-reset email are not implemented.

Local credentials, uploads, databases, build outputs and raw test recordings are excluded
from Git. Use `.env.example` for configuration; never commit your `.env`.

- Durable generation is not offline inference: chat text, retrieved passages and relevant memories
  go to the configured AI provider; document text goes for embeddings; search queries go to search providers.
- Cookie sessions, password hashing, ownership/origin checks and optimistic versions protect resource operations.
- Document/web/tool content is untrusted data, not permission to execute instructions or modify resources.
- Markdown, math and PDF rendering restrict executable features; viewer assets are served locally.
- Public deployment additionally requires HTTPS, appropriate cookie/origin settings, least-privilege
  database access, backups, monitoring and registration/data-retention review.
- The verified product scope is local desktop use. Public hosting, physical mobile devices and Safari
  are not fully verified. Local test passes do not constitute production certification.
- Initial vector retrieval is exact; larger installations require independent scale measurements.

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md). The repository secret
scanner reports paths/counts without printing keys, but it cannot prove absence of all sensitive data.

## License

[MIT](LICENSE). Dependency licenses remain applicable to their respective packages.
