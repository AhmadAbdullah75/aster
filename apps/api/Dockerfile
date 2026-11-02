FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock alembic.ini ./
ENV PYTHONPATH=/app/apps/api
ENV UV_NO_DEV=1
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev
COPY apps/api ./apps/api
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "nexus.main:app", "--host", "0.0.0.0", "--port", "8000"]
