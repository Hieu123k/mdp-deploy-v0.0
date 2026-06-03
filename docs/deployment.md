# Deployment

This document describes cloud server preparation for Avenue Manufacturing Data Platform. It does not cover managed Kubernetes, managed databases, or production Oracle/JDE sync jobs.

## Architecture

The production Docker Compose stack runs these services on one Linux server:

- `reverse-proxy`: Caddy, the only public service, exposing ports `80` and `443`.
- `frontend`: Next.js App Router app served internally on port `3000`.
- `backend`: FastAPI app served internally on port `8000`.
- `postgres`: PostgreSQL 16 with a persistent named volume.
- `pgadmin`: optional admin profile, disabled by default.

PostgreSQL, backend, and frontend are not exposed directly to the public host. Public traffic reaches the application through Caddy.

## Server Prerequisites

- Linux server
- Docker
- Docker Compose
- Git
- Domain DNS record pointing to the server
- Firewall allowing inbound `80` and `443`
- SSH access restricted to trusted users or networks

## Environment Setup

Create a production environment file from the template:

```bash
cp .env.production.example .env.production
```

Edit `.env.production` and replace every placeholder:

- `POSTGRES_PASSWORD`
- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `CONNECTION_SECRET_KEY`
- `CORS_ORIGINS`
- `NEXT_PUBLIC_API_URL`
- `PGADMIN_DEFAULT_PASSWORD`

Use long, random values for `JWT_SECRET_KEY` and `CONNECTION_SECRET_KEY`. Production startup fails if these values are missing, too short, or still using demo defaults.

Production example:

```env
APP_ENV=production
CORS_ORIGINS=["https://your-domain.example.com"]
NEXT_PUBLIC_API_URL=
```

Do not commit `.env.production`.

## Reverse Proxy

The production stack uses `deploy/Caddyfile`.

Current pattern:

- Frontend: `https://your-domain.example.com`
- API through Caddy: `https://your-domain.example.com/api`
- Swagger docs through the public API prefix: `https://your-domain.example.com/api/docs`
- OpenAPI through the public API prefix: `https://your-domain.example.com/api/openapi.json`

The Caddy `handle_path /api/*` rule strips `/api` before forwarding to the backend. This allows the current FastAPI routes, such as `/auth/login` and `/outbound/{model_name}`, to keep working without a backend route prefix refactor. In production, leave `NEXT_PUBLIC_API_URL` empty so the Next.js frontend calls same-origin `/api/*`.

The FastAPI backend routes remain mounted at root internally. Frontend pages and components must use canonical backend paths through `frontend/src/lib/api.ts`; the API helper is responsible for turning `/data-models` into `/api/data-models` in production or `http://localhost:8000/data-models` in local direct mode.

Before deployment, replace `your-domain.example.com` in `deploy/Caddyfile` with the real domain.

## Run Production Stack

From the repository root:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Check services:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production ps
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
```

Run database migrations:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec backend alembic upgrade head
```

Optional pgAdmin profile, bound only to server localhost:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production --profile admin up -d pgadmin
```

## Large JDE / Oracle Migrations

Do not run long Oracle/JDE full-load migrations inside the FastAPI API container.

For large initial loads, use ora2pg or another external bulk loader outside the web request path. Load data into PostgreSQL staging tables such as `mdp_staging.stg_jde_supplier`, then register the work in `Migration Jobs`, record the external run result, and validate the target table from MDP.

Future production deployments may add a dedicated worker container to invoke ora2pg safely outside FastAPI request handlers. Until then, run ora2pg externally and use MDP for tracking, validation, Type B mapping, governed APIs, and audit visibility.

See [migration-jobs.md](migration-jobs.md).

## Backup

Create a timestamped PostgreSQL dump under `backups/`:

```bash
./scripts/backup_postgres.sh
```

Example output:

```text
backups/mdp_20260530_153000.dump
```

Backup files are ignored by git.

## Restore

Restore from a dump file:

```bash
./scripts/restore_postgres.sh backups/<file>.dump
```

Restore may overwrite data in the target database. Confirm you are using the correct server and backup file before running it.

## Security Notes

- Do not expose PostgreSQL publicly.
- Do not expose backend or frontend container ports publicly.
- Do not expose pgAdmin publicly.
- Use HTTPS through Caddy.
- Use strong production secrets.
- Rotate the default admin password immediately after first login.
- Restrict SSH access.
- Keep the server and Docker patched.
- Store real secrets outside git.
- Review firewall rules before opening the service to users.

## Post-Deployment Smoke Test

After deployment:

1. Open the UI at the production domain.
2. Log in as the default admin, then change the password.
3. Seed procurement demo data from `Demo Data`.
4. Create or verify the Type B `supplier` model.
5. Create or verify the Type B `purchase_order_summary` model.
6. Query both models from `Data Browser`.
7. Create an outbound API key scoped to those models.
8. Query `/api/outbound/supplier/SUP-1001` with `X-API-Key`.
9. Open `Transactions` and confirm successful and failed requests are logged.

## Local Development

Local development remains unchanged:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f backend
docker compose down
```

Local defaults are for demos only. They are rejected when `APP_ENV=production`.
