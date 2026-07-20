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

# Authenticate to GHCR in a throwaway Docker config dir so the token is not left
# in /root/.docker/config.json (docker login warns about unencrypted storage there).
_ghcr_owned_cfg=0
_ghcr_cfg=""

ghcr_login() {
  local user="" token=""
  if [[ -n "${GHCR_TOKEN:-}" ]]; then
    user="${GHCR_USER:-github}"
    token="$GHCR_TOKEN"
  elif [[ -f /opt/reel/.ghcr_token ]]; then
    user="$(cat /opt/reel/.ghcr_user 2>/dev/null || echo github)"
    # shellcheck disable=SC2002
    token="$(cat /opt/reel/.ghcr_token)"
  else
    return 0
  fi
  if [[ -z "${DOCKER_CONFIG:-}" ]]; then
    _ghcr_cfg="$(mktemp -d)"
    chmod 700 "$_ghcr_cfg"
    export DOCKER_CONFIG="$_ghcr_cfg"
    _ghcr_owned_cfg=1
  fi
  echo "$token" | docker login ghcr.io -u "$user" --password-stdin
}

ghcr_logout() {
  if [[ "$_ghcr_owned_cfg" -eq 1 && -n "$_ghcr_cfg" ]]; then
    docker logout ghcr.io 2>/dev/null || true
    rm -rf "$_ghcr_cfg"
    unset DOCKER_CONFIG
  fi
}

trap ghcr_logout EXIT
ghcr_login

docker compose -f "$COMPOSE_FILE" pull
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
docker image prune -f
ghcr_logout
trap - EXIT
