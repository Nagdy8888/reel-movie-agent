# Phase 9 — Deployment (EC2 + Caddy TLS, Vercel, CI)

## Objective

Ship it:

- **Backend + agent** → a single, cost-validated **AWS EC2** instance (initial candidate: `t3.micro`, 1 vCPU / 1 GB RAM) running the backend container behind **Caddy** (automatic HTTPS via Let's Encrypt).
- **Frontend** → **Vercel**.
- **Neo4j** → **Aura Free** (off-box). **Supabase** → managed (auth + Postgres checkpointer/store).
- **CI** → GitHub Actions: lint + typecheck + tests + build image + push + SSH deploy.
- **AWS cost guardrail** → remain on the **Free account plan**, use the new-customer **$100 promotional credit**, target no more than **$5 USD of gross AWS usage per month**, and keep out-of-pocket/card charges at **$0**.

## Prerequisites

- Phases 1–8 complete and passing locally.
- New AWS account with the initial **$100 promotional credit**, a billing-alert email address, a hostname pointing to the instance (custom domain, DuckDNS, or `sslip.io`), a GitHub repo, a Vercel account, an Aura Free DB, and a Supabase project.
- Verify that AWS Billing shows **Free account plan** before provisioning. If it shows **Paid account plan**, stop: budgets can alert, but they cannot guarantee that the saved card will not be charged.
- Record the AWS account creation date and credit expiry. The Free account plan ends after six months or when its credits are exhausted, whichever comes first; promotional credits expire 12 months after account creation.

## Steps

### 1. Managed data services

- **Neo4j Aura Free:** create a free instance; note `neo4j+s://<id>.databases.neo4j.io`, user, password. Run the Phase 3 ingestion scripts pointed at Aura (`NEO4J_URI=neo4j+s://...`) to load data + build the vector index there once.
- **Supabase:** use the existing **`Reel`** project (`project_id: "bkhmqtcxoxtrydumgwfd"`) — no new project needed. Enable RS256 JWT signing keys; set the Postgres connection string for `SUPABASE_DB_URL`. Use the Supabase MCP plugin (see `.cursor/rules/supabase-mcp.mdc`) to confirm the project (`list_projects`), verify the checkpointer/store tables exist (`list_tables`), and run `get_advisors` to check prod security (RLS, exposure) before go-live.

### 2. AWS credit and $5 monthly cost guardrail

Keep the account on the **Free account plan** and do not upgrade it to Paid. AWS does not charge the saved card for service usage while the account remains on the Free plan; instead, the plan ends and the account closes after six months or when the credits are exhausted, whichever happens first. Some AWS services and features are unavailable on this plan.

Before creating resources, configure these two alerts.

**Gross usage budget — `reel-monthly-5-usd`:**

- Budget amount: **$5 USD per month**, scoped to all AWS services used by this project.
- Cost basis: gross unblended usage **excluding credits and refunds**, so promotional credits do not hide the underlying resource cost.
- Early warning: email when the **forecasted** monthly cost exceeds **$4 (80%)**.
- Limit alert: email when the **actual** monthly cost exceeds **$5 (100%)**.
- Confirm the email subscription and test that the recipient is correct.

**Zero-charge warning:** Create an AWS Budgets **Zero spend budget** template using the same email address, to warn if spending exceeds Free Tier limits.

An AWS Budget is an alert, **not a hard spending cap**, and billing data can be delayed. Do not launch the EC2 stack until the AWS Pricing Calculator estimate for compute, EBS, public IPv4/Elastic IP, and expected data transfer is at or below $5/month. Credits pay eligible charges but do not make the resources free. If an always-on `t3.micro` plus networking exceeds the target, use a smaller/scheduled deployment or revise the hosting design before provisioning.

At $5/month, the project can use at most $30 during the six-month Free plan. Do not upgrade merely to consume the remaining promotional credit; preserving the $0 card-charge requirement is more important than using the full $100.

### 3. Harden the backend Dockerfile (already non-root + HEALTHCHECK)

Pin the base image by digest for prod, e.g. `FROM python:3.11-slim@sha256:...`. Confirm it runs as `appuser` and exposes `/health`.

### 4. Caddy reverse proxy — `infra/aws/Caddyfile`

```caddyfile
your-host.example.com {
    reverse_proxy backend:8000
    encode gzip
}
```

Caddy auto-provisions and renews Let's Encrypt certs for `your-host.example.com`.

### 5. Prod compose on the box — `infra/aws/docker-compose.prod.yml`

```yaml
services:
  backend:
    image: ghcr.io/<owner>/reel-backend:latest
    env_file: [/opt/reel/.env]      # prod .env on the instance (NOT in git)
    environment:
      APP_ENV: prod
    restart: unless-stopped
    expose: ["8000"]
    # 1 uvicorn worker (set in Dockerfile CMD) — RAM budget

  caddy:
    image: caddy:2
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on: [backend]

volumes:
  caddy_data:
  caddy_config:
```

Neo4j and Postgres are **not** on the box (Aura + Supabase). Set `--forwarded-allow-ips` on uvicorn (or configure `slowapi`) so client IPs are read from Caddy correctly.

### 6. EC2 provisioning — `infra/aws/cloud-init.yml`

After validating the complete monthly estimate against the $5 budget, launch the selected instance (`t3.micro` only if it fits) using Amazon Linux 2023 or Ubuntu LTS. Allocate + attach an **Elastic IP** only if its public IPv4 cost is included in the estimate. Security group: allow 22 (your IP), 80, 443. Cloud-init (user data) should:

```yaml
#cloud-config
package_update: true
runcmd:
  # 1) create a 2 GB swap file (critical on 1 GB RAM)
  - fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  - echo '/swapfile none swap sw 0 0' >> /etc/fstab
  # 2) install Docker + compose plugin
  - curl -fsSL https://get.docker.com | sh
  - usermod -aG docker ec2-user || usermod -aG docker ubuntu
  # 3) app dir
  - mkdir -p /opt/reel
```

Point DNS (A record) for your hostname at the Elastic IP.

### 7. Deploy script — `infra/aws/deploy.sh`

```bash
#!/usr/bin/env bash
# Pull the latest backend image and restart the prod stack.
set -euo pipefail
cd /opt/reel
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker image prune -f
```

Copy `docker-compose.prod.yml`, `Caddyfile`, and the prod `.env` to `/opt/reel` on the instance (the `.env` is provisioned manually/secret manager — never committed).

### 8. GitHub Actions CI — `.github/workflows/ci.yml`

```yaml
name: ci
on:
  push: { branches: [main] }
  pull_request:
jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pyright
      - run: uv run pytest -q

  deploy-backend:
    needs: quality
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with: { registry: ghcr.io, username: ${{ github.actor }}, password: ${{ secrets.GITHUB_TOKEN }} }
      - uses: docker/build-push-action@v6
        with:
          context: .
          file: apps/backend/Dockerfile
          push: true
          tags: ghcr.io/${{ github.repository_owner }}/reel-backend:latest
      - name: SSH deploy
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.EC2_HOST }}
          username: ${{ secrets.EC2_USER }}
          key: ${{ secrets.EC2_SSH_KEY }}
          script: bash /opt/reel/deploy.sh
```

Store `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY` as GitHub secrets.

### 9. Frontend on Vercel

- Import the repo in Vercel; set **Root Directory** = `apps/frontend`.
- Env vars: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL=https://your-host.example.com`.
- Add the Vercel domain to the backend's `CORS_ALLOW_ORIGINS` and to Supabase's allowed redirect URLs.

### 10. Verify production

- `https://your-host.example.com/health` returns 200 over HTTPS (valid cert).
- The Vercel frontend logs in via Supabase and streams a chat answer from the EC2 backend.
- LangSmith shows prod traces; `/ready` returns 200 (Aura + Supabase reachable).

## Environment variables (prod)

Prod `.env` on the box: `OPENAI_API_KEY`, `LANGSMITH_*`, `NEO4J_URI=neo4j+s://...` (+ user/pass), `SUPABASE_URL`, `SUPABASE_DB_URL`, `CORS_ALLOW_ORIGINS=https://<vercel-domain>`, `APP_ENV=prod`.

## Acceptance criteria

- [ ] CI is green (lint + format + pyright + pytest) before any deploy job runs.
- [ ] Backend image builds and pushes to GHCR on `main`.
- [ ] AWS Billing confirms the account is still on the **Free account plan**.
- [ ] The `$5/month` AWS Cost Budget excludes credits/refunds and sends forecasted `$4` plus actual `$5` email alerts.
- [ ] A **Zero spend budget** alert is active for the same verified email recipient.
- [ ] The AWS Pricing Calculator estimate includes EC2, EBS, public IPv4/Elastic IP, and data transfer and is no more than `$5/month`.
- [ ] EC2 has a 2 GB swap file and runs backend + Caddy via the prod compose.
- [ ] `https://<host>/health` serves 200 with a valid Let's Encrypt cert.
- [ ] Vercel frontend talks to the EC2 backend end-to-end (auth + streamed answer).
- [ ] Neo4j Aura + Supabase are used (nothing data-heavy on the 1 GB box).

## Do NOT

- Do NOT run Neo4j or Postgres on the `t3.micro` (RAM budget) — use Aura + Supabase.
- Do NOT commit the prod `.env` or SSH keys.
- Do NOT use more than 1 uvicorn worker on the EC2 box.
- Do NOT expose the backend directly on 8000 publicly — only via Caddy on 443.
- Do NOT treat the $100 promotional credit or an AWS Budget alert as a hard cost cap.
- Do NOT upgrade the AWS account to the Paid plan or join AWS Organizations; either can make the saved card chargeable.

## Relevant rules & skills

- Rules: `security` (prod env validation, headers), `fastapi-backend`.
- Skill: `verify-standards` (CI runs the same gate).
