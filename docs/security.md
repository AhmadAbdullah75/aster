# Security boundaries

Sessions are 48-byte random opaque tokens, stored as SHA-256 hashes keyed by the local session secret.
Cookies are HttpOnly, SameSite=Lax, path=/, expiring and revocable; set COOKIE_SECURE=true behind HTTPS.
Passwords use Argon2id. Login and expensive requests use database-backed rate buckets.
Cookie-authenticated mutations must carry the configured Origin, including registration/login.
When APP_ORIGIN is a loopback address, localhost, 127.0.0.1 and [::1] aliases are accepted
only with the configured scheme and port. Deployed origins remain exact; missing origins,
other ports and lookalike hosts are rejected. Browser cookies remain scoped to their host,
so switching between localhost and 127.0.0.1 requires signing in on the other address.

All resource/tool/database retrieval paths derive identity from the session or server-created worker runtime.
Thread IDs do not authorize access. Projection endpoints and source/preview routes check ownership.
No unrestricted code execution or URL fetching exists. Calculator syntax is parsed using an allowlisted AST.

Uploads have generated blob paths outside public assets. Filenames are sanitized; type, UTF-8, PDF and DOCX
structure are checked. Extraction, decompression, chunks, files and account storage are bounded.
Document text and search/tool output are untrusted data. Domain services enforce ownership and approval
regardless of provider instructions. Raw Markdown HTML is escaped, executable link protocols are removed,
remote Markdown images are not fetched, and code is displayed as text.

The PDF preview renders pages through the pinned Mozilla PDF.js package in a same-origin worker.
PDF JavaScript, forms and interactive annotations are not executed. Worker, CMaps and standard fonts
are bundled locally; external viewers/CDNs and WebAssembly evaluation are not required. Image dimensions
and rendering resolution are bounded. Original downloads require the same document ownership check.

Approval payloads are schema validated, scoped to the original target/project/version, bounded to 20 items,
expiring after seven days, and consumed once. Transactions prevent duplicate writes after checkpoint replay.
Edits or deletes with stale versions fail 409. Project deletion cascades and cleans blobs/checkpoints/project memories.

The CSP disallows object embedding, cross-origin frames, forms and connections; deployment uses only same-origin
browser API traffic. Secrets are excluded from source control and Docker build context. Error responses/logs
never include raw provider exceptions or keys. No security audit or production certification is claimed.

Production still requires host/network access controls, HTTPS, database least privilege, backups, monitoring,
and an operator-appropriate review of registration policy and data retention. See deployment notes.
