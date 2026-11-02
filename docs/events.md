# Durable event protocol

`POST /conversations/{thread}/runs` returns 202 with canonical run ID and conversation ID.
`GET /runs/{run}/events?cursor=N` is an authenticated fetch SSE stream. The cursor is the last processed sequence.
Each event is committed before delivery and uses this envelope:

```json
{"id":1,"seq":1,"run_id":"uuid","thread_id":"uuid","type":"run.started","payload":{"resumed":false}}
```

SSE frames contain `id`, `event`, JSON `data`, and a blank terminator. Idle streams send comment heartbeats.
Sequences increase per run. Reconnecting with the cursor replays only subsequent events. Duplicate IDs are ignored
by the browser parser, which incrementally decodes UTF-8, split frames, CRLF and multiline data.

| Type | Payload |
|---|---|
| run.started | resumed boolean |
| message.delta | text string |
| tool.started | name, call_id |
| tool.completed | name, call_id, nullable error |
| source.added | authorized source ID/document ID/filename/page/section/excerpt/score, or provider URL annotation |
| memory.used | items of id/title |
| approval.required | proposal_ids |
| action.completed | proposal_id, status, saved outcomes or error |
| run.completed | proposal_ids (empty) |
| run.failed | sanitized actionable error |
| run.canceled | requested or terminal cancellation metadata |

The frontend uses event notifications to refresh canonical projections, throttled during deltas;
it does not concatenate replayed events onto an already loaded transcript. This avoids duplicate final messages.
The status endpoint and transcript remain authoritative after missed terminal events or browser reload.
Navigating away closes the stream without canceling durable work. Stop invokes the explicit cancel endpoint.
Partial output is marked interrupted after cancellation/failure. Already committed actions remain real results.
Tool status contains operation names, never private model reasoning.
