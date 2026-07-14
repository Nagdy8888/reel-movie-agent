# syntax=docker/dockerfile:1
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
# Copy the workspace so uv can resolve the `agents` member.
COPY pyproject.toml uv.lock ./
COPY apps/agents ./apps/agents
COPY apps/backend ./apps/backend
# Sync the workspace (root owns `[dependency-groups] dev`, including langgraph-cli).
RUN uv sync --frozen --group dev
# Non-root user (security requirement); owns /app so uv can write its cache.
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
WORKDIR /app/apps/agents
EXPOSE 2024
# NOTE: `langgraph dev` is the in-memory Studio/dev server. For production, deploy
# via LangGraph Platform (or `langgraph up`) with the Postgres checkpointer/store.
CMD ["uv", "run", "langgraph", "dev", "--host", "0.0.0.0", "--port", "2024", "--no-browser"]
