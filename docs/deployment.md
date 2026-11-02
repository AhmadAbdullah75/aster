# Local containers and production notes

`docker compose --profile full up --build -d` starts PostgreSQL/pgvector, API, worker, web.
Default native services use 3000 (web), 8000 (API localhost), 5434 (PostgreSQL localhost).
Container API is internal; web proxies to `http://api:8000`. Database is `postgres:5432`.
Do not run native and container web services on the same host port simultaneously.

Before production:

- Use HTTPS and COOKIE_SECURE=true; set APP_ORIGIN to the exact deployed origin.
- Store provider/session/database secrets in deployment secret management; never in an image or public variable.
- Mount persistent blob and PostgreSQL volumes. Back up both consistently; test restoration including checkpoint/store schemas.
- Run Alembic and graph library migrations before starting workers. Pin and review dependency upgrades and lockfiles.
- Reverse proxy `/api` without SSE buffering (`proxy_buffering off`, adequate idle/read timeout).
- Run at least one worker; database leases coordinate multiple worker processes. One local worker serializes chat runs,
  while ingestion runs in a background coroutine. Increase worker processes if measured demand requires it.
- Configure body limits at ingress as well as application limits. Restrict database ingress, API docs and registration
  according to deployment needs. Use a dedicated non-superuser runtime role after migrations.
- Preserve sanitized logs and audit events under an explicit retention policy. Monitor failed jobs, expired leases and quotas.

No cloud resources, remote repository, publication, or production deployment is created by this project setup.
