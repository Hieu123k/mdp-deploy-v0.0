# Avenue Manufacturing Data Platform

Avenue Manufacturing Data Platform (Avenue MDP) is a Dockerized monorepo MVP foundation for configurable manufacturing data services. The current milestone includes FastAPI, Next.js, PostgreSQL 16, SQLAlchemy, Alembic, Docker Compose, pgAdmin, JWT authentication, user management, data model metadata CRUD, generated Type A storage tables, dynamic inbound/outbound APIs, transaction logging, API key authentication for external systems, external connection metadata management, migration job tracking for external bulk loaders such as ora2pg, JDE procurement migration templates, JDE Type B data model templates, and a guided JDE procurement demo flow.

## Architecture Summary

- `backend/`: Python FastAPI service running on port `8000`
- `frontend/`: Next.js App Router dashboard running on port `3000`
- `postgres`: PostgreSQL 16 database with a named Docker volume
- `pgadmin`: Optional database administration UI on port `5050`

The frontend supports login, a consolidated Admin UI, data model management, Type B mapping, DB browsing, outbound data browsing, API key management, transaction monitoring, connection management, demo data controls, and user viewing.

Authentication is implemented with bcrypt password hashing and JWT bearer tokens. A default admin user is seeded on backend startup when no users exist.

For a concise project context snapshot covering product vision, architecture, completed capabilities, design decisions, and roadmap, see [docs/project-context.md](docs/project-context.md).

For the external ora2pg migration tracking strategy, see [docs/migration-jobs.md](docs/migration-jobs.md).

For JDE Type B model templates, see [docs/data-model-templates.md](docs/data-model-templates.md).

## Local Setup

Prerequisites:

- Docker Desktop
- Docker Compose

Create a local environment file if you want to override defaults:

```bash
cp .env.example .env
```

Start the full stack from the repository root:

```bash
docker compose up -d --build
```

Rebuild after backend or frontend dependency changes:

```bash
docker compose up -d --build
```

Check containers:

```bash
docker compose ps
```

Follow backend logs:

```bash
docker compose logs -f backend
```

Stop the stack:

```bash
docker compose down
```

Run backend tests locally:

```bash
docker compose up -d --build
docker compose exec backend pytest
```

Run the frontend build locally:

```bash
cd frontend
npm install
npm run build
```

The production frontend Docker image uses the Next.js standalone output, so `docker compose build frontend` is the container build check.

## Production Deployment Preparation

Production deployment assets are included for a cloud server Docker Compose deployment:

- `.env.production.example`: production environment template with required secrets.
- `docker-compose.prod.yml`: production stack using Caddy as the only public entry point.
- `deploy/Caddyfile`: reverse proxy configuration for frontend, `/api`, `/docs`, and `/openapi.json`.
- `scripts/backup_postgres.sh`: timestamped PostgreSQL backup script.
- `scripts/restore_postgres.sh`: PostgreSQL restore script.

Production startup requires `APP_ENV=production` and rejects default or weak secrets. See [docs/deployment.md](docs/deployment.md) for the deployment architecture and [docs/deployment-runbook.md](docs/deployment-runbook.md) for the Dev/Product deployment checklist from the release candidate tag.

The frontend is now a Next.js App Router application migrated from the `Hieu123k/MDP-ver1.0` variant repository. Local development uses `NEXT_PUBLIC_API_URL=http://localhost:8000` to call FastAPI directly. Production leaves `NEXT_PUBLIC_API_URL` empty so the browser calls same-origin `/api/*`; Caddy strips `/api` and forwards requests to the original FastAPI root routes.

Frontend code should call canonical backend paths through `frontend/src/lib/api.ts`, for example `apiFetch("/data-models")` or `apiPath("/outbound/supplier")`. Do not hardcode `/api` inside pages or components; the API helper adds the public prefix when needed.

## URLs

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs
- pgAdmin: http://localhost:5050

## Default Admin Account

- Username: `admin`
- Email: `admin@mdp.local`
- Password: `admin123`
- Role: `admin`

## Admin Web UI

The Avenue MDP Admin Web UI at `http://localhost:3000` is the main MVP demo workspace. It uses an enterprise-style dark sidebar and light data workspace with:

- Dashboard
- Data Models
- DB Browser
- Data Browser
- API Keys
- Transactions
- Connections
- Migration Jobs
- Demo Data
- Users

The dashboard summarizes data models, Type A/Type B split, active API keys, active connections, today's inbound/outbound transactions, failed transactions, and procurement demo seed status. It also includes quick links for creating the demo Type B Supplier and Purchase Order Summary models.

Recommended demo flow:

1. Open `Demo Data` and seed procurement staging data.
2. Open `DB Browser` and inspect `mdp_staging` tables and `vw_jde_purchase_order_summary`.
3. Open `Data Models` and create a Type B `supplier` model from `mdp_staging.stg_jde_supplier`.
4. Create a Type B `purchase_order_summary` model from `mdp_staging.vw_jde_purchase_order_summary`.
5. Open `Data Browser` and query saved models through `/outbound/{model_name}`.
6. Open `API Keys` and create a scoped key for selected models and directions.
7. Test outbound access with the API key.
8. Open `Migration Jobs` to register an external ora2pg load and validate the PostgreSQL staging target.
9. Open `Transactions` to review JWT/API-key activity and failures.

The UI uses selectors for system-backed choices such as model type, schemas, tables/views, columns, data types, API key scope, directions, transaction filters, and connection types so demo users do not need to type internal identifiers manually.

Users page capabilities:

- Create users with username, email, full name, role, password, and active status.
- View and edit user profile fields.
- Activate or deactivate users without deleting the row.
- Reset user passwords from the Admin UI.
- Filter users by search text, role, and status.

Current roles are basic labels: `admin`, `data_engineer`, `api_manager`, and `viewer`. Fine-grained RBAC will be added later.

## Backend

Health check:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "manufacturing-data-platform"
}
```

Alembic is configured under `backend/alembic` for users and data model metadata tables.

## Authentication

Login API example:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"admin123\"}"
```

The response includes a JWT access token:

```json
{
  "access_token": "<token>",
  "token_type": "bearer"
}
```

Use the token with protected APIs:

```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer <token>"
```

## Data Model Management

All `/data-models` endpoints require a JWT bearer token.

Create a Type A ingested model:

```bash
curl -X POST http://localhost:8000/data-models \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"invoice\",\"display_name\":\"Invoice\",\"type\":\"A\",\"primary_key\":\"invoice_no\",\"attributes\":[{\"name\":\"invoice_no\",\"display_name\":\"Invoice Number\",\"data_type\":\"text\",\"required\":true,\"is_primary_key\":true}]}"
```

List active Type A models:

```bash
curl "http://localhost:8000/data-models?status=active&type=A" \
  -H "Authorization: Bearer <token>"
```

Filter by classification metadata:

```bash
curl "http://localhost:8000/data-models?domain=procurement&source_layer=curated_view&canonical_status=curated" \
  -H "Authorization: Bearer <token>"
```

Update a model:

```bash
curl -X PUT http://localhost:8000/data-models/<id> \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"display_name\":\"Supplier Invoice\"}"
```

Deactivate a model:

```bash
curl -X DELETE http://localhost:8000/data-models/<id> \
  -H "Authorization: Bearer <token>"
```

This milestone stores model metadata and creates generated PostgreSQL storage tables for Type A models.

### Classification and Namespace Metadata

Data models include lightweight classification fields that prepare Avenue MDP for future canonical model organization, semantic search, IIoT hierarchy, and AI access:

- `namespace`: lowercase dot-separated path, for example `avenue.demo.procurement.supplier`
- `domain`: controlled business domain such as `procurement`, `quality`, `production`, `iiot`, or `finance`
- `entity_type`: lowercase snake_case business object type such as `supplier` or `purchase_order`
- `business_process`: controlled process such as `procure_to_pay` or `plan_to_produce`
- `source_layer`: `source`, `staging`, `canonical`, `curated_view`, `analytical`, `external_api`, or `generated_table`
- `canonical_status`: `source_aligned`, `canonical`, `curated`, `experimental`, or `deprecated`
- `site_scope`: `enterprise`, `site`, `area`, `line`, `work_center`, `asset`, or `not_applicable`

When fields are omitted, the backend applies safe defaults where possible. Procurement category models default to `domain=procurement`; Type A models default to `source_layer=generated_table`; Type B models mapped to `stg_` objects default to `staging`, and `vw_` objects default to `curated_view`. `canonical_status` defaults to `experimental` and `site_scope` defaults to `enterprise`.

These fields are metadata only in this MVP. Full UNS/MQTT hierarchy, IIoT time-series storage, semantic query, knowledge graph, and AI agents remain future phases.

Type A models now automatically create a PostgreSQL table in the `mdp_data` schema when the model is created. For example, creating the `invoice` Type A model creates:

```text
mdp_data.dm_invoice
```

Type B models store metadata only and do not generate new tables. Updating a model does not alter an already generated table in this milestone, and deactivating a model does not drop the generated table.

### Type B Linked Models

Type B data models link attributes to existing PostgreSQL staging columns instead of creating new tables. For the MVP, these mappings target verified tables such as `mdp_staging.stg_jde_supplier`.

Current Type B rules:

- All attributes must map to one source table per model.
- `source_schema`, `source_table`, and `source_column` are required for each attribute.
- Allowed source schemas are `mdp_staging`, `public`, and `mdp_data`.
- The source table and columns must exist.
- Declared model data types must be compatible with source column types.
- A primary key is required.
- Nullable primary key metadata produces a warning instead of a hard failure. This is especially important for PostgreSQL views, where `information_schema` often cannot reliably enforce nullability.

Validate a draft Type B mapping:

```bash
curl -X POST http://localhost:8000/data-models/type-b/validate-mapping \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"supplier\",\"display_name\":\"Supplier\",\"type\":\"B\",\"primary_key\":\"supplier_code\",\"attributes\":[{\"name\":\"supplier_code\",\"display_name\":\"Supplier Code\",\"data_type\":\"text\",\"required\":true,\"source_schema\":\"mdp_staging\",\"source_table\":\"stg_jde_supplier\",\"source_column\":\"supplier_code\",\"is_primary_key\":true},{\"name\":\"supplier_name\",\"display_name\":\"Supplier Name\",\"data_type\":\"text\",\"required\":true,\"source_schema\":\"mdp_staging\",\"source_table\":\"stg_jde_supplier\",\"source_column\":\"supplier_name\"}]}"
```

Preview an unsaved mapping:

```bash
curl -X POST "http://localhost:8000/data-models/type-b/preview?limit=20" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d @supplier-type-b.json
```

Preview a saved Type B model:

```bash
curl "http://localhost:8000/data-models/<id>/mapped-preview?limit=20" \
  -H "Authorization: Bearer <token>"
```

Type B Mapping UI flow:

1. Open `Data Models`.
2. Choose `Type B: Linked Model`.
3. Select `mdp_staging` and a staging table or view.
4. Click `Generate Attributes from Source Columns`.
5. Pick one primary key attribute.
6. Validate the mapping, preview rows, then save.

To create `supplier`, select `mdp_staging.stg_jde_supplier`, generate attributes, keep the supplier fields you need, and mark `supplier_code` as the primary key.

To create `purchase_order_summary`, select `mdp_staging.vw_jde_purchase_order_summary`, generate attributes, keep the purchase order summary fields, and mark `po_no` as the primary key. View nullability warnings are expected and do not block saving.

In the UI, Type A models are ingested models that create generated PostgreSQL tables. Type B models are linked models that expose existing staging tables or views without creating new tables. Saved Type B models can be queried through `/outbound/{model_name}` and `/outbound/{model_name}/{key}`.

Oracle connector and sync jobs are still deferred.

## Dynamic Inbound API

Type A models accept authenticated flat JSON payloads at:

```text
POST /inbound/{model_name}
```

Example for `quality_result`:

```bash
curl -X POST http://localhost:8000/inbound/quality_result \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"result_no\":\"QR-001\",\"item_code\":\"ITEM-1001\",\"batch_no\":\"BATCH-2026-001\",\"inspection_date\":\"2026-05-30\",\"result_value\":98.5,\"passed\":true}"
```

Example response:

```json
{
  "status": "success",
  "model": "quality_result",
  "record_id": "00000000-0000-0000-0000-000000000000",
  "message": "Data received successfully"
}
```

Inbound validation uses the active Type A data model attributes:

- Required attributes must be present and non-null.
- Unknown fields are ignored for mapped table columns.
- Unknown fields remain preserved in `raw_payload`.
- Supported data types: `text`, `integer`, `float`, `boolean`, `date`, `datetime`, `json`.

Each inbound request writes a transaction log. Successful logs include request and response payloads. Failed validation or insert attempts write failed logs when the data model is found.

Current limitations:

- JWT or scoped API key authentication is required for inbound APIs.
- Insert only; no upsert behavior yet.
- Type B inbound is not supported.
- MQTT and schema evolution are not implemented yet.

## Dynamic Outbound API

Type A and Type B models can be queried through authenticated outbound APIs:

```text
GET /outbound/{model_name}
GET /outbound/{model_name}/{key}
```

Examples:

```bash
curl http://localhost:8000/outbound/quality_result \
  -H "Authorization: Bearer <token>"

curl http://localhost:8000/outbound/quality_result/QR-001 \
  -H "Authorization: Bearer <token>"

curl http://localhost:8000/outbound/supplier \
  -H "Authorization: Bearer <token>"

curl http://localhost:8000/outbound/supplier/SUP-1001 \
  -H "Authorization: Bearer <token>"

curl "http://localhost:8000/outbound/supplier?country=VN" \
  -H "Authorization: Bearer <token>"

curl http://localhost:8000/outbound/purchase_order_summary \
  -H "Authorization: Bearer <token>"

curl http://localhost:8000/outbound/purchase_order_summary/PO-2026-0001 \
  -H "Authorization: Bearer <token>"

curl "http://localhost:8000/outbound/purchase_order_summary?po_status=open" \
  -H "Authorization: Bearer <token>"
```

List response shape:

```json
{
  "status": "success",
  "model": "quality_result",
  "type": "A",
  "count": 2,
  "limit": 100,
  "offset": 0,
  "data": [
    {
      "result_no": "QR-001",
      "item_code": "ITEM-1001",
      "batch_no": "BATCH-2026-001",
      "inspection_date": "2026-05-30",
      "result_value": 98.5,
      "passed": true
    }
  ]
}
```

Type B responses use model attribute names and do not expose the source table/view in each data row:

```json
{
  "status": "success",
  "model": "supplier",
  "type": "B",
  "count": 5,
  "limit": 100,
  "offset": 0,
  "data": [
    {
      "supplier_code": "SUP-1001",
      "supplier_name": "ABC Industrial Supplies",
      "country": "VN",
      "status": "active"
    }
  ]
}
```

By-key response shape:

```json
{
  "status": "success",
  "model": "quality_result",
  "type": "A",
  "key": "QR-001",
  "data": {
    "result_no": "QR-001",
    "item_code": "ITEM-1001"
  }
}
```

Options:

- `limit`: default `100`, max `500`
- `offset`: default `0`
- `include_meta=true`: include `id`, `created_at`, `updated_at`
- `include_raw=true`: include `raw_payload` for Type A only
- Equality filters on model attributes, such as `?item_code=ITEM-1001&passed=true` or `?country=VN`

Current limitations:

- Type B outbound supports one mapped source table or view per model.
- Type B `include_raw=true` returns `400` because linked models do not have `raw_payload`.
- JWT or scoped API key authentication is required.
- Equality filters only.
- No AI semantic query layer yet.

## API Key Authentication

Human users authenticate with JWT. External systems can call inbound and outbound APIs with an API key:

```text
X-API-Key: <api_key>
```

API keys are managed by authenticated users. The plain key is shown only once during creation and is never stored by the backend.

Create an API key:

```bash
curl -X POST http://localhost:8000/api-keys \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"QMS integration\",\"source_system\":\"QMS\",\"allowed_directions\":[\"inbound\",\"outbound\"],\"allowed_models\":[\"quality_result\"]}"
```

Example create response includes `api_key` once:

```json
{
  "id": "...",
  "name": "QMS integration",
  "key_prefix": "mdp_live_abcd123",
  "api_key": "mdp_live_abcd123...",
  "source_system": "QMS",
  "allowed_directions": ["inbound", "outbound"],
  "allowed_models": ["quality_result"],
  "is_active": true
}
```

Inbound with API key:

```bash
curl -X POST http://localhost:8000/inbound/quality_result \
  -H "X-API-Key: <api_key>" \
  -H "Content-Type: application/json" \
  -d "{\"result_no\":\"QR-001\",\"result_value\":98.5,\"passed\":true}"
```

Outbound with API key:

```bash
curl http://localhost:8000/outbound/quality_result/QR-001 \
  -H "X-API-Key: <api_key>"
```

API keys can be scoped by direction (`inbound`, `outbound`) and model names. Null or empty `allowed_models` means all models are allowed. Transaction logs record whether the request used JWT or API key authentication.

## Connection Manager

Authenticated users can manage external system connection metadata through:

```text
POST /connections
GET /connections
GET /connections/{id}
PUT /connections/{id}
DELETE /connections/{id}
POST /connections/{id}/test
```

Supported connection types:

- `postgresql`
- `oracle`
- `sqlserver`
- `rest_api`
- `mqtt`

Connection passwords are encrypted with Fernet before storage using `CONNECTION_SECRET_KEY`. API responses never return `password` or `encrypted_password`.

Example PostgreSQL connection:

```bash
curl -X POST http://localhost:8000/connections \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"plant_postgres\",\"type\":\"postgresql\",\"host\":\"postgres\",\"port\":5432,\"database_name\":\"mdp\",\"username\":\"mdp_user\",\"password\":\"mdp_password\"}"
```

Example Oracle JDE connection metadata:

```json
{
  "name": "jde_production",
  "type": "oracle",
  "host": "jde-db.company.local",
  "port": 1521,
  "database_name": "JDEPROD",
  "username": "jde_readonly",
  "password": "<password>",
  "description": "JDE ERP production Oracle database"
}
```

Current limitations:

- Connection records are metadata only until source browser, sync jobs, and migration worker features are added.
- Oracle tests use `python-oracledb` thin mode and require client network access to the Oracle listener.
- SQL Server tests require `pyodbc` and a compatible ODBC driver.
- MQTT testing currently validates metadata only.
- Large Oracle JDE bulk migrations should use ora2pg or another external loader, then be tracked through Migration Jobs.

## Migration Jobs

Migration Jobs track external bulk migration work such as ora2pg full loads from Oracle JDE to PostgreSQL staging.

Important rule:

```text
MDP does not replace ora2pg for 30M+ row initial loads.
```

Use ora2pg or another external bulk loader for high-volume full loads. Avenue MDP stores the job metadata, records run results, validates target staging tables, tracks row-limit/time-window/watermark metadata for future incremental updates, and then exposes the migrated data through Type B Linked Data Models and governed outbound APIs. Detailed guidance is in [docs/migration-jobs.md](docs/migration-jobs.md).

Authenticated APIs:

```text
GET /migration-templates
GET /migration-templates/{template_key}
POST /migration-templates/{template_key}/create-job

POST /migration-jobs
GET /migration-jobs
GET /migration-jobs/{id}
PUT /migration-jobs/{id}
DELETE /migration-jobs/{id}
POST /migration-jobs/{id}/runs
GET /migration-jobs/{id}/runs
GET /migration-runs/{id}
PUT /migration-runs/{id}
POST /migration-runs/{id}/validate-target
```

Target validation checks only PostgreSQL staging targets:

- target schema/table existence
- target row count
- configured primary key columns
- primary key null counts
- duplicate key counts
- first 10 sample rows

Source row counts should be entered from ora2pg or external loader logs. See [docs/migration-jobs.md](docs/migration-jobs.md).

The JDE Procurement templates provide starting points for Supplier Master, Purchase Order Header, Purchase Order Line, Purchase Order Receipt, AP Invoice, and the curated Purchase Order Summary View. They pre-fill source/target metadata, primary key columns, watermark fields, and validation level; customer-specific JDE schemas should still be reviewed with the DBA/JDE team.

## Data Model Templates

Data Model Templates create governed Type B models from migrated JDE staging tables and curated views after migration data has landed in PostgreSQL. They reuse the existing Type B mapping validation and do not create physical tables or run migration workloads.

Authenticated APIs:

```text
GET /data-model-templates
GET /data-model-templates/{template_key}
POST /data-model-templates/{template_key}/create-model
```

Current JDE Procurement templates include `jde_supplier`, `jde_purchase_order_summary`, `jde_ap_invoice`, `jde_po_header`, and `jde_po_line`. Detailed guidance is in [docs/data-model-templates.md](docs/data-model-templates.md).

## JDE Procurement Demo Flow

The `JDE Demo Flow` page guides demo/UAT users through the complete MVP path:

1. Seed or confirm migrated JDE staging data.
2. Create a supplier Migration Job from template.
3. Record an external migration run.
4. Validate the PostgreSQL target.
5. Create the supplier Type B model from template.
6. Preview supplier data.
7. Test `GET /outbound/supplier/SUP-1001`.
8. Open Transactions to review audit logging.

The workflow status API is:

```text
GET /demo/jde-procurement/workflow-status
```

The flow also includes the curated `purchase_order_summary` model and `GET /outbound/purchase_order_summary/PO-2026-0001`. It does not execute ora2pg; seeded staging data simulates migrated JDE data for demo mode.

## Mock JDE Procurement Staging Data

The MVP includes mock PostgreSQL staging tables in the `mdp_staging` schema. These tables simulate procurement data from Oracle JDE that has already been migrated by an external ETL or database migration tool.

The real Oracle JDE connector and sync jobs are deferred to later milestones.

Simulated JDE tables:

- `F0101` / `F0401`: `mdp_staging.stg_jde_supplier`
- `F4301`: `mdp_staging.stg_jde_po_header`
- `F4311`: `mdp_staging.stg_jde_po_line`
- `F43121`: `mdp_staging.stg_jde_po_receipt`
- `F0411`: `mdp_staging.stg_jde_ap_invoice`

Curated procurement view:

- `mdp_staging.vw_jde_purchase_order_summary`

This view joins and summarizes supplier, purchase order header, purchase order line, and AP invoice staging data into one row per purchase order. It exists so the MVP can create a Type B `purchase_order_summary` model against one source object while the full multi-table Type B join engine remains deferred.

Reseed demo data from the API:

```bash
curl -X POST http://localhost:8000/admin/demo/seed-procurement-staging \
  -H "Authorization: Bearer <token>"
```

Check row counts:

```bash
curl http://localhost:8000/admin/demo/procurement-staging-summary \
  -H "Authorization: Bearer <token>"
```

SQL examples:

```sql
SELECT * FROM mdp_staging.stg_jde_supplier;
SELECT * FROM mdp_staging.stg_jde_po_header;
SELECT * FROM mdp_staging.stg_jde_po_line;
SELECT * FROM mdp_staging.stg_jde_po_receipt;
SELECT * FROM mdp_staging.stg_jde_ap_invoice;
SELECT * FROM mdp_staging.vw_jde_purchase_order_summary;
```

## DB Table Browser

The DB Browser lets authenticated administrators inspect PostgreSQL schemas, tables, columns, and sample rows. Its first purpose is to inspect migrated staging data before creating Type B Linked Data Models.

Example endpoints:

```text
GET /db-browser/schemas
GET /db-browser/schemas/mdp_staging/tables
GET /db-browser/schemas/mdp_staging/tables/stg_jde_supplier/columns
GET /db-browser/schemas/mdp_staging/tables/stg_jde_supplier/preview
```

Preview supports `limit` and `offset`:

```bash
curl "http://localhost:8000/db-browser/schemas/mdp_staging/tables/stg_jde_supplier/preview?limit=50&offset=0" \
  -H "Authorization: Bearer <token>"
```

Security limits:

- JWT authentication is required.
- Only lowercase snake_case schema and table identifiers are accepted.
- System schemas such as `pg_catalog`, `information_schema`, and `pg_toast` are excluded.
- The API does not accept raw SQL.
- Preview queries only run after schema and table existence are verified.
- Preview `limit` is capped at `100`.

## Testing Auth In Swagger UI

1. Open http://localhost:8000/docs.
2. Run `POST /auth/login` with username `admin` and password `admin123`.
3. Copy the `access_token` value from the response.
4. Click `Authorize`.
5. Paste the token value into the bearer authorization field.
6. Run protected endpoints such as `GET /auth/me` or `GET /users`.

## Backend Tests

Run tests from the backend container or a local Python environment with backend dependencies installed:

```bash
pytest
```
