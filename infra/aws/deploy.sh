#!/usr/bin/env bash
# Pull the latest backend + LightRAG Postgres images and restart the prod stack.
set -euo pipefail
cd /opt/reel

ENV_FILE=/opt/reel/.env
COMPOSE_FILE=docker-compose.prod.yml

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE is missing. Copy the production .env to the host first." >&2
  exit 1
fi

# Export for Compose interpolation (${RAG_PG_*} in docker-compose.prod.yml).
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

required=(RAG_PG_USER RAG_PG_PASSWORD RAG_PG_DATABASE OPENAI_API_KEY SUPABASE_URL SUPABASE_DB_URL)
missing=()
for key in "${required[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    missing+=("$key")
  fi
done
if ((${#missing[@]})); then
  echo "ERROR: /opt/reel/.env is missing required keys: ${missing[*]}" >&2
  echo "Add the LightRAG RAG_PG_* block (and secrets) then re-run deploy.sh." >&2
  exit 1
fi

# Optional GHCR login for private packages (token file owned by deploy user).
if [[ -f /opt/reel/.ghcr_token ]]; then
  # shellcheck disable=SC2002
  cat /opt/reel/.ghcr_token | docker login ghcr.io -u "$(cat /opt/reel/.ghcr_user 2>/dev/null || echo github)" --password-stdin
fi

docker compose -f "$COMPOSE_FILE" pull
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
docker image prune -f
