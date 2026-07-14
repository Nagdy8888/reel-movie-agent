#!/usr/bin/env bash
# Pull the latest backend image and restart the prod stack.
set -euo pipefail
cd /opt/reel

# Optional GHCR login for private packages (token file owned by deploy user).
if [[ -f /opt/reel/.ghcr_token ]]; then
  # shellcheck disable=SC2002
  cat /opt/reel/.ghcr_token | docker login ghcr.io -u "$(cat /opt/reel/.ghcr_user 2>/dev/null || echo github)" --password-stdin
fi

docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker image prune -f
