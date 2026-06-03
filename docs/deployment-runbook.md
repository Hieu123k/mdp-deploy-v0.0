# Avenue MDP Deployment Runbook

This runbook describes how to deploy Avenue Manufacturing Data Platform to a Dev server and a Product server from a release candidate tag.

Release candidate tag:

```text
v0.2.0-jde-migration-rc1
```

## 1. Release Strategy

Deploy from the release candidate tag, not from a feature branch.

Rules:

- `main` is the stable baseline.
- Release candidate tags are used for repeatable deployment and rollback.
- Dev and Product deployments should use the same tag unless a controlled hotfix tag is created.
- Do not deploy directly from `feature/nextjs-frontend-migration` or any other feature branch.

The target release for this runbook is:

```text
v0.2.0-jde-migration-rc1
```

## 2. Repository Checkout

On the target server:

```bash
git clone https://github.com/hieudovn/manufacturing-data-platform.git
cd manufacturing-data-platform
git fetch --tags
git checkout v0.2.0-jde-migration-rc1
```

Confirm the checkout:

```bash
git status
git describe --tags --exact-match
```

Expected tag:

```text
v0.2.0-jde-migration-rc1
```

## 3. Server Prerequisites

Required for Dev and Product:

- Linux server, preferably Ubuntu LTS.
- Docker Engine.
- Docker Compose plugin.
- Git.
- DNS/domain or reachable server IP.
- Firewall rules allowing public HTTP/HTTPS traffic.
- Storage capacity for PostgreSQL data and staging tables.
- SSH access for deployment operators.

Additional Product requirements:

- ora2pg installed and tested on the Product server or on a dedicated migration server.
- Network access from ora2pg host to Oracle JDE DB.
- Network access from ora2pg host to PostgreSQL target.
- Product Oracle/JDE user should be read-only.
- Storage sized for real staging data, including large migrated tables, indexes, backups, and growth.

Firewall baseline:

- Allow inbound `80` and `443` to the server.
- Restrict inbound SSH to trusted operators or networks.
- Do not expose PostgreSQL `5432` publicly.
- Do not expose backend `8000` publicly.
- Do not expose frontend `3000` publicly.
- Do not expose pgAdmin publicly.

## 4. Dev Server Deployment

The Dev server does not require a real Oracle DB. Use seeded mock JDE staging data for the demo/UAT flow.

### 4.1 Checkout Release Tag

```bash
git clone https://github.com/hieudovn/manufacturing-data-platform.git
cd manufacturing-data-platform
git fetch --tags
git checkout v0.2.0-jde-migration-rc1
```

### 4.2 Configure Environment

```bash
cp .env.production.example .env.production
```

Edit `.env.production`:

- Set `APP_ENV=production`.
- Set strong `POSTGRES_PASSWORD`.
- Update `DATABASE_URL` with the same PostgreSQL password.
- Set long random `JWT_SECRET_KEY`.
- Set long random `CONNECTION_SECRET_KEY`.
- Configure `CORS_ORIGINS` for the Dev domain or IP.
- Configure `NEXT_PUBLIC_API_URL` according to the deployment pattern.
- Set pgAdmin credentials only if the admin profile is needed.

Example same-origin Caddy mode:

```env
APP_ENV=production
CORS_ORIGINS=["https://dev-mdp.example.com"]
NEXT_PUBLIC_API_URL=
```

Before running the stack, update `deploy/Caddyfile` with the Dev domain:

```text
dev-mdp.example.com {
    ...
}
```

### 4.3 Start Stack

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

### 4.4 Check Services

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production ps
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
```

Run migrations if needed:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec backend alembic upgrade head
```

### 4.5 Dev Smoke Test

In the Admin UI:

1. Log in as admin.
2. Change the default admin password.
3. Open `JDE Demo Flow` or `Demo Data`.
4. Seed demo procurement staging data.
5. Create a migration job from the JDE Supplier Master template.
6. Create an external run record.
7. Validate `mdp_staging.stg_jde_supplier`.
8. Create Type B `supplier` from template.
9. Preview supplier data.
10. Query `GET /outbound/supplier/SUP-1001` from Data Browser.
11. Open `Transactions` and confirm outbound audit logging.

Expected demo data:

- `mdp_staging.stg_jde_supplier` includes `SUP-1001`.
- `mdp_staging.vw_jde_purchase_order_summary` includes `PO-2026-0001`.

## 5. Product Server Deployment

The Product server uses real Oracle/JDE staging migration with ora2pg.

### 5.1 Checkout Release Tag

```bash
git clone https://github.com/hieudovn/manufacturing-data-platform.git
cd manufacturing-data-platform
git fetch --tags
git checkout v0.2.0-jde-migration-rc1
```

### 5.2 Configure Production Environment

```bash
cp .env.production.example .env.production
```

Edit `.env.production` for Product:

- Use `APP_ENV=production`.
- Use strong non-default secrets.
- Use the real Product domain in `CORS_ORIGINS`.
- Keep `NEXT_PUBLIC_API_URL` empty for same-origin Caddy `/api` mode unless a different routing pattern is intentionally used.
- Verify `DATABASE_URL` points to the internal Docker PostgreSQL service unless using a managed/external database.

Update `deploy/Caddyfile` with the Product domain.

### 5.3 Start Product Stack

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Check status:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production ps
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
```

Run migrations if needed:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec backend alembic upgrade head
```

### 5.4 Product Readiness Checks

Confirm:

- MDP UI opens through HTTPS.
- Backend health check works through Caddy.
- PostgreSQL volume has sufficient storage.
- ora2pg host can connect to Oracle JDE.
- ora2pg host can load into PostgreSQL target.
- ora2pg target schema is `mdp_staging`.
- Oracle/JDE user is read-only.
- Product backup plan is in place before pilot data load.

### 5.5 Product Migration Flow

1. Run ora2pg externally for the selected JDE table.
2. Load data into the PostgreSQL `mdp_staging` target table.
3. In MDP, create or open the matching Migration Job.
4. Record the real ora2pg run.
5. Validate the target staging table.
6. Review the Validation Report.
7. Create Type B model from real staging.
8. Query the outbound API.
9. Check transaction log.

Example:

```text
Oracle JDE PRODDTA.F4311
  -> ora2pg
  -> mdp_staging.stg_jde_po_line
  -> Migration Run record
  -> Target Validation Report
  -> Type B purchase_order_line model
  -> GET /outbound/purchase_order_line
```

## 6. Environment Variables

Production environment is read from `.env.production`.

Important variables:

- `APP_ENV`: set to `production` on Dev/Product deployments using `docker-compose.prod.yml`.
- `POSTGRES_DB`: PostgreSQL database name.
- `POSTGRES_USER`: PostgreSQL user.
- `POSTGRES_PASSWORD`: strong PostgreSQL password.
- `DATABASE_URL`: backend SQLAlchemy URL, usually `postgresql+psycopg://user:password@postgres:5432/db`.
- `JWT_SECRET_KEY`: long random JWT signing secret, at least 32 characters.
- `JWT_ALGORITHM`: usually `HS256`.
- `ACCESS_TOKEN_EXPIRE_MINUTES`: token lifetime.
- `CONNECTION_SECRET_KEY`: long random Fernet-compatible secret material used by the backend config to encrypt connection passwords.
- `CORS_ORIGINS`: JSON list of allowed frontend origins.
- `NEXT_PUBLIC_API_URL`: public API base used by the Next.js frontend.
- `PGADMIN_DEFAULT_EMAIL`: optional pgAdmin admin email.
- `PGADMIN_DEFAULT_PASSWORD`: optional pgAdmin admin password.

`NEXT_PUBLIC_API_URL` guidance:

- Local/dev direct frontend-to-backend mode can use `http://host:8000`.
- Production behind Caddy should usually leave `NEXT_PUBLIC_API_URL` empty.
- With an empty value, the frontend uses same-origin `/api`.
- Caddy strips `/api` and forwards to FastAPI root routes such as `/auth/login`, `/data-models`, and `/outbound/{model_name}`.

Do not commit `.env.production`.

## 7. Security Checklist

Before exposing the system:

- Change the default admin password.
- Use strong `JWT_SECRET_KEY`.
- Use strong `CONNECTION_SECRET_KEY`.
- Use strong PostgreSQL password.
- Do not expose PostgreSQL `5432` publicly.
- Do not expose backend `8000` publicly.
- Do not expose frontend `3000` publicly.
- Do not expose pgAdmin publicly.
- Use HTTPS through Caddy.
- Restrict SSH access.
- Limit API key scopes by direction and model.
- Set API key expiration where practical.
- Product Oracle user should be read-only.
- Keep server packages and Docker patched.
- Store secrets outside git.
- Back up PostgreSQL before Product pilot migration if data already exists.

## 8. Backup and Restore

### 8.1 Backup

Create a timestamped PostgreSQL dump:

```bash
./scripts/backup_postgres.sh
```

Expected output pattern:

```text
backups/mdp_YYYYMMDD_HHMMSS.dump
```

Before Product pilot, take a backup if existing data exists.

### 8.2 Restore

Restore from a dump file:

```bash
./scripts/restore_postgres.sh backups/<file>.dump
```

Restore can overwrite data. Confirm the target server, environment file, and backup file before running it.

## 9. Product Ora2pg Pilot Workflow

ora2pg performs the actual bulk migration. MDP does not run 30M+ row migrations inside FastAPI.

Recommended Product pilot sequence:

1. Confirm target staging table design with the DBA/JDE team.
2. Run ora2pg externally.
3. Confirm ora2pg completed successfully.
4. Confirm target table exists in `mdp_staging`.
5. Record Migration Run metadata in MDP.
6. Run target validation.
7. Review Validation Report with customer stakeholders.
8. Create Type B data model.
9. Query outbound API.
10. Confirm transaction log.

Example run metadata:

```json
{
  "run_type": "external_bulk",
  "trigger_type": "external",
  "status": "success",
  "source_row_count": 30000000,
  "target_row_count": 30000000,
  "rows_loaded": 30000000,
  "duration_seconds": 10800,
  "log_text": "ora2pg summary: 30M rows, 30GB table, completed successfully in 3-4h"
}
```

If the run took 4 hours, use:

```json
{
  "duration_seconds": 14400
}
```

Optional ora2pg metadata can be entered in the Migration Run UI:

- ora2pg config file
- ora2pg command
- ora2pg log file
- source table size GB
- target table size GB
- rows per second

Validation should confirm:

- target table exists
- target row count matches the source count copied from ora2pg logs
- primary key columns exist
- primary key null count is zero
- duplicate key count is zero
- watermark min/max is reasonable if configured

## 10. Post-Deployment Smoke Test Checklist

### 10.1 Dev Smoke Test

Use the mock JDE workflow:

- UI opens.
- Admin login works.
- Demo staging data seeds successfully.
- JDE Supplier migration job can be created from template.
- External run record can be created.
- `mdp_staging.stg_jde_supplier` validates successfully.
- Type B `supplier` can be created from template.
- Supplier preview shows `SUP-1001`.
- `GET /outbound/supplier/SUP-1001` returns supplier data.
- Transactions page shows outbound API activity.

### 10.2 Product Smoke Test

Use real migrated staging data:

- UI opens.
- Admin login works.
- Migration job exists for real JDE table.
- Real ora2pg run result is recorded.
- Validation Report shows target row count.
- Source and target row counts match if source count was provided.
- Type B model can be created from the real staging table or view.
- Outbound API returns expected real record.
- Transactions page shows outbound API activity.

## 11. Rollback

Rollback has two parts: application version and database state.

### 11.1 Application Rollback

Checkout the previous known-good tag:

```bash
git fetch --tags
git checkout <previous-tag>
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Check services:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production ps
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f backend
```

### 11.2 Database Rollback

If schema or data must roll back, restore the PostgreSQL backup taken before deployment or pilot migration:

```bash
./scripts/restore_postgres.sh backups/<file>.dump
```

Do not restore Product data without explicit approval from the deployment owner.

## 12. Troubleshooting

### Backend Fails On Startup Due To Production Secrets

Symptoms:

- Backend exits during startup.
- Logs mention invalid `JWT_SECRET_KEY`, `CONNECTION_SECRET_KEY`, `DATABASE_URL`, or `CORS_ORIGINS`.

Fix:

- Edit `.env.production`.
- Replace demo/default values.
- Use secrets longer than 32 characters.
- Confirm `CORS_ORIGINS` includes the deployed HTTPS origin.
- Restart the stack.

### Frontend Calls Wrong API URL

Symptoms:

- Login fails in browser.
- Network tab shows requests to the wrong host.
- Requests contain `/api/api`.

Fix:

- For production Caddy mode, leave `NEXT_PUBLIC_API_URL` empty.
- Rebuild frontend after changing `NEXT_PUBLIC_API_URL`.
- Confirm frontend code uses `frontend/src/lib/api.ts` helper and canonical backend paths.

### Caddy `/api` Routing Issue

Symptoms:

- UI opens but API calls return 404.
- `/api/docs` does not open Swagger.

Fix:

- Confirm `deploy/Caddyfile` domain is correct.
- Confirm Caddy has `handle_path /api/* { reverse_proxy backend:8000 }`.
- Confirm backend routes are still root routes internally, not prefixed with `/api`.
- Restart reverse proxy.

### PostgreSQL Volume Permissions Or Storage

Symptoms:

- PostgreSQL container fails to start.
- Migration or ora2pg load fails with disk errors.

Fix:

- Check disk space.
- Check Docker volume status.
- Confirm the server has enough capacity for staging tables, indexes, and backups.
- Avoid storing large backup dumps on the same full disk.

### Alembic Migration Failure

Symptoms:

- Backend works but DB schema is missing fields/tables.
- `alembic upgrade head` fails.

Fix:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec backend alembic current
docker compose -f docker-compose.prod.yml --env-file .env.production exec backend alembic heads
docker compose -f docker-compose.prod.yml --env-file .env.production exec backend alembic upgrade head
```

If Product data exists, take a backup before manual schema recovery.

### Ora2pg Target Table Not Found

Symptoms:

- Migration Run validation fails with target table missing.

Fix:

- Confirm ora2pg loaded into PostgreSQL.
- Confirm target schema is `mdp_staging`.
- Confirm target table name matches the Migration Job.
- Confirm table name casing. MDP expects lowercase snake_case PostgreSQL identifiers.
- Update Migration Job target metadata if the loaded table name differs.

### Validation Row Count Mismatch

Symptoms:

- Validation Report shows source-vs-target row count mismatch.

Fix:

- Confirm `source_row_count` was copied correctly from ora2pg logs.
- Run PostgreSQL `COUNT(*)` manually on target table if needed.
- Check ora2pg logs for skipped rows, failed rows, filters, partitions, or WHERE clauses.
- Confirm target table was not truncated/reloaded after the run record was created.
- Re-run target validation after correcting metadata or load issues.

### Product Oracle Connectivity

Symptoms:

- ora2pg cannot connect to Oracle JDE.

Fix:

- Confirm network route/firewall to Oracle listener.
- Confirm Oracle service name/SID.
- Confirm read-only Oracle credentials.
- Confirm required schemas such as `PRODDTA` are accessible.
- Run ora2pg connectivity checks outside MDP before recording a Migration Run.

