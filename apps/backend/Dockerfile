# syntax=docker/dockerfile:1
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps/agents ./apps/agents
COPY apps/backend ./apps/backend
RUN uv sync --frozen --package backend \
  && useradd --create-home appuser \
  && mkdir -p /data/lightrag \
  && chown -R appuser:appuser /app /data/lightrag
USER appuser
ENV PATH="/app/.venv/bin:$PATH" \
    UV_NO_SYNC=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"
# Call the venv uvicorn directly so runtime does not re-sync as appuser.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "apps/backend/src", "--workers", "1"]
