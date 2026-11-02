# Aster

Aster connects conversation, project knowledge and reviewable actions in one personal AI workspace.
It is built with Next.js/React/TypeScript, FastAPI/Python, LangGraph and PostgreSQL with pgvector.
Internal package and database identifiers retain `nexus` for compatibility with existing local data.

## Scope model

Personal conversations have separate transcripts but share the authenticated user's personal
tasks, notes and memories. Each project has its own conversations, documents, tasks, notes and
project memories. Authorization is enforced by the server, not by model-provided identifiers.
Deleting a project removes its project-owned resources while preserving unrelated personal data.

## Document workflow

Uploads are parsed and indexed by a background worker. Users select documents and ask questions
in Auto or Documents mode. Retrieval combines vector similarity and full-text ranking. Summary
requests use bounded coverage retrieval and disclose incomplete coverage. Source links resolve
to authorized chunks, with PDF page navigation when available.

Citation references are validated against each run's retrieved evidence. Exact short references
and grouped references are normalized to source IDs or returned web URLs. Unknown references
are repaired once; unresolved document references produce labelled excerpts rather than invented links.

## Actions and memory

The model proposes task, note and memory mutations. Users can edit, exclude, approve or reject
items before any write. Approved mutations run transactionally and tolerate repeated execution.
Resolved review cards disappear from chat, while resources and decision records persist.
Direct form saves are intentional user actions and do not require a second approval.

Memory can retain useful preferences and profile facts after review. It can be disabled or deleted.
Deleting a memory does not erase its original chat message. Preferences can be applied in the
current response before durable storage is approved.

## Persistence and recovery

Conversation projections keep the visible transcript independently of LangGraph checkpoints.
Workers claim jobs with leases and advisory locks. Waiting approvals survive restarts. Interrupted
generation retains partial output and requires an explicit retry rather than promising token-level resume.

## Practical limits

The supported/verified release scope is local desktop operation. Web information may be stale or
incomplete, free API quotas apply, OCR is unavailable, and account management is local-password only.
Do not infer deployment readiness or guaranteed factual accuracy from local test results.

See [architecture](architecture.md), [security](security.md), [testing](testing.md), and
[deployment considerations](deployment.md) for details.
