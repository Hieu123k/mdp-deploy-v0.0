# API Design

This milestone exposes health, authentication, user management, and data model metadata endpoints.

## Health Check

`GET /health`

Response:

```json
{
  "status": "ok",
  "service": "manufacturing-data-platform"
}
```

Future milestones will add APIs for data model management, inbound flat JSON ingestion, and outbound data access based on configured data models.

## Authentication

`POST /auth/login`

Request:

```json
{
  "username": "admin",
  "password": "admin123"
}
```

Response:

```json
{
  "access_token": "<token>",
  "token_type": "bearer"
}
```

`GET /auth/me`

Requires `Authorization: Bearer <token>`.

## Users

All user endpoints require a valid JWT for an active user.

- `POST /users`
- `GET /users`
- `GET /users/{id}`
- `PUT /users/{id}`
- `DELETE /users/{id}`

## Data Models

All data model endpoints require a valid JWT for an active user.

- `POST /data-models`
- `GET /data-models`
- `GET /data-models/{id}`
- `PUT /data-models/{id}`
- `DELETE /data-models/{id}`

`GET /data-models` supports simple filters:

- `status`
- `type`
- `ai_enabled`

`DELETE /data-models/{id}` is a soft delete that sets `status` to `inactive`.

When `POST /data-models` creates a Type A model, the response includes `generated_table`, such as `mdp_data.dm_invoice`. Type B model responses return `generated_table` as `null`.

## Dynamic Inbound

`POST /inbound/{model_name}`

Requires either a valid JWT for an active user or a scoped API key with `inbound` access.

Behavior:

- Finds the active data model by `model_name`.
- Accepts Type A models only.
- Validates the flat JSON request body against model attributes.
- Inserts mapped fields into `mdp_data.dm_{model_name}`.
- Stores the full original request body in `raw_payload`.
- Writes a transaction log.

Example:

```json
{
  "result_no": "QR-001",
  "item_code": "ITEM-1001",
  "batch_no": "BATCH-2026-001",
  "inspection_date": "2026-05-30",
  "result_value": 98.5,
  "passed": true
}
```

Response:

```json
{
  "status": "success",
  "model": "quality_result",
  "record_id": "...",
  "message": "Data received successfully"
}
```

Current limitations:

- Insert only; no upsert yet.
- JWT or scoped API key authentication is required.
- Type B inbound, MQTT, and schema evolution are not implemented yet.

## Dynamic Outbound

`GET /outbound/{model_name}`

Requires either a valid JWT for an active user or a scoped API key with `outbound` access.

Behavior:

- Finds the active data model by `model_name`.
- Accepts Type A generated-table models and Type B linked models.
- Selects only data model attribute columns by default.
- Supports `limit`, `offset`, `include_meta`, and `include_raw`.
- Supports simple equality filters on defined data model attributes.
- Writes an outbound transaction log.
- For Type B, queries the saved mapped staging table or view and returns model attribute names.
- For Type B, `include_raw=true` returns `400` because linked models do not store raw payloads.

List response:

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

Type B list examples:

```bash
curl http://localhost:8000/outbound/supplier \
  -H "Authorization: Bearer <token>"

curl "http://localhost:8000/outbound/supplier?country=VN" \
  -H "Authorization: Bearer <token>"

curl http://localhost:8000/outbound/purchase_order_summary \
  -H "Authorization: Bearer <token>"

curl "http://localhost:8000/outbound/purchase_order_summary?po_status=open" \
  -H "Authorization: Bearer <token>"
```

Type B list response:

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

`GET /outbound/{model_name}/{key}`

Uses the data model `primary_key` attribute as the lookup column.

For Type B, the primary key attribute is translated to its mapped `source_column`. If the lookup returns more than one row, the API returns `409 Conflict`.

By-key response:

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

Type B by-key examples:

```bash
curl http://localhost:8000/outbound/supplier/SUP-1001 \
  -H "Authorization: Bearer <token>"

curl http://localhost:8000/outbound/purchase_order_summary/PO-2026-0001 \
  -H "Authorization: Bearer <token>"
```

Security rules:

- JWT or scoped API key authentication is required.
- Users cannot submit SQL.
- Users cannot choose table names directly.
- Table names are derived only from active data model metadata.
- Type B source table/view names are derived only from saved attribute mappings.
- Filter fields must be defined model attributes.
- All filter values are bound SQL parameters.

Current limitations:

- Type B outbound supports one mapped source table or view per model.
- JWT or API key authentication is supported.
- Equality filters only.
- AI semantic query layer is not implemented yet.

## API Keys

Human users use JWT bearer tokens. External systems can call inbound and outbound APIs with:

```text
X-API-Key: <api_key>
```

API key management endpoints require JWT:

- `POST /api-keys`
- `GET /api-keys`
- `GET /api-keys/{id}`
- `PUT /api-keys/{id}`
- `DELETE /api-keys/{id}`

API keys support:

- `allowed_directions`: `inbound`, `outbound`
- `allowed_models`: optional list of model names; null or empty allows all models
- `source_system`
- `expires_at`
- `is_active`

Security rules:

- Plain API keys are returned only once on create.
- Plain API keys are never stored.
- API responses never expose `hashed_key`.
- `DELETE /api-keys/{id}` deactivates the key.

Example inbound request:

```bash
curl -X POST http://localhost:8000/inbound/quality_result \
  -H "X-API-Key: <api_key>" \
  -H "Content-Type: application/json" \
  -d "{\"result_no\":\"QR-001\",\"result_value\":98.5,\"passed\":true}"
```

Example outbound request:

```bash
curl http://localhost:8000/outbound/quality_result/QR-001 \
  -H "X-API-Key: <api_key>"
```

## Transactions

Transaction APIs require a valid JWT:

- `GET /transactions`
- `GET /transactions/{id}`

`GET /transactions` supports filters:

- `direction`
- `protocol`
- `status`
- `data_model_id`
- `limit`
- `offset`

## Connections

Connection Manager endpoints require JWT authentication:

- `POST /connections`
- `GET /connections`
- `GET /connections/{id}`
- `PUT /connections/{id}`
- `DELETE /connections/{id}`
- `POST /connections/{id}/test`

Supported `type` values:

- `postgresql`
- `oracle`
- `sqlserver`
- `rest_api`
- `mqtt`

`GET /connections` supports filters:

- `type`
- `status`

Security rules:

- Passwords are encrypted before storage.
- API responses never return `password` or `encrypted_password`.
- `DELETE /connections/{id}` is a soft delete that sets `status` to `inactive`.

Testing behavior:

- PostgreSQL runs `SELECT 1`.
- REST API sends `GET` to `base_url` with a timeout.
- Oracle returns a clear unavailable-driver message when `python-oracledb` is missing or not configured.
- SQL Server returns a clear unavailable-driver message when `pyodbc` or an ODBC driver is missing.
- MQTT validates metadata only in this milestone.

## Migration Jobs

Migration Job endpoints require JWT authentication. They track external migration work such as ora2pg full loads from Oracle JDE into PostgreSQL staging.

MDP does not execute large JDE/Oracle full-load migrations inside FastAPI. For high-volume tables, run ora2pg or another external bulk loader outside the web API, then record the run and validate the target staging table.

Job endpoints:

- `POST /migration-jobs`
- `GET /migration-jobs`
- `GET /migration-jobs/{id}`
- `PUT /migration-jobs/{id}`
- `DELETE /migration-jobs/{id}`

Run endpoints:

- `POST /migration-jobs/{id}/runs`
- `GET /migration-jobs/{id}/runs`
- `GET /migration-runs/{id}`
- `PUT /migration-runs/{id}`

Target validation:

- `POST /migration-runs/{id}/validate-target`

Supported migration tools:

- `ora2pg`
- `manual`
- `external_tool`
- `native_small_table`

`native_small_table` is reserved for small manual tests only and is not the recommended path for production JDE full loads.

Target validation checks only PostgreSQL staging targets:

- target schema exists
- target table exists
- target row count
- configured primary key columns exist
- primary key null count
- duplicate key group count
- first 10 sample rows

Source row counts should be copied from ora2pg or external loader logs. Validation does not scan huge Oracle source tables by default.

## Demo Procurement Staging

Demo staging endpoints require JWT authentication:

- `POST /admin/demo/seed-procurement-staging`
- `GET /admin/demo/procurement-staging-summary`

`POST /admin/demo/seed-procurement-staging` safely creates and reseeds mock JDE procurement staging tables. The operation is idempotent and returns deterministic row counts:

```json
{
  "status": "success",
  "message": "Procurement staging data seeded successfully",
  "tables": {
    "stg_jde_supplier": 5,
    "stg_jde_po_header": 5,
    "stg_jde_po_line": 5,
    "stg_jde_po_receipt": 3,
    "stg_jde_ap_invoice": 5
  }
}
```

These endpoints do not implement Oracle sync, Type B query mapping, or table browsing.

## DB Browser

DB Browser endpoints require JWT authentication and expose safe metadata browsing plus limited row previews:

- `GET /db-browser/schemas`
- `GET /db-browser/schemas/{schema_name}/tables`
- `GET /db-browser/schemas/{schema_name}/tables/{table_name}/columns`
- `GET /db-browser/schemas/{schema_name}/tables/{table_name}/preview`

Example URLs:

```text
GET /db-browser/schemas
GET /db-browser/schemas/mdp_staging/tables
GET /db-browser/schemas/mdp_staging/tables/stg_jde_supplier/columns
GET /db-browser/schemas/mdp_staging/tables/stg_jde_supplier/preview
```

Security rules:

- Schema and table names must match `^[a-z][a-z0-9_]*$`.
- System schemas are excluded.
- Raw SQL is never accepted from the caller.
- Preview only selects from verified schema/table names.
- `limit` defaults to `50` and is capped at `100`.

The DB Browser is intended for inspecting staging data before creating Type B Linked Data Models. It does not execute mappings itself; saved Type B models are queried through the outbound APIs.

## Type B Linked Data Models

Type B models link configured attributes to existing PostgreSQL staging columns. They do not create generated tables.

Type B mapping endpoints require JWT authentication:

- `POST /data-models/type-b/validate-mapping`
- `POST /data-models/type-b/preview`
- `GET /data-models/{id}/mapped-preview`

Validation rules:

- Every Type B attribute requires `source_schema`, `source_table`, and `source_column`.
- Allowed schemas are `mdp_staging`, `public`, and `mdp_data`.
- Source schema, table, and column identifiers must be lowercase snake_case.
- Source schema, table, and column must exist.
- All attributes must map to one source table per model.
- The declared model data type must be compatible with the source column type.
- A primary key is required.
- Attribute names may differ from source column names.
- Missing `source_column` is rejected as a mapping configuration error.
- The primary key must match an attribute name and map to a valid source column.
- Primary key nullability metadata is reported as a warning, not a hard error. PostgreSQL views often report columns as nullable even when the underlying source is logically non-null.

Draft validation response:

```json
{
  "status": "success",
  "message": "Type B mapping is valid",
  "warnings": [
    {
      "field": "primary_key",
      "message": "Primary key source column is from a view. Nullability cannot be reliably enforced by information_schema."
    }
  ],
  "source_schema": "mdp_staging",
  "source_table": "vw_jde_purchase_order_summary",
  "mapped_columns": [
    {
      "attribute": "po_no",
      "source_column": "po_no",
      "source_data_type": "text",
      "model_data_type": "text"
    }
  ]
}
```

Preview responses return flat rows using model attribute names. Saved Type B models can also be queried through `/outbound/{model_name}` and `/outbound/{model_name}/{key}`. Oracle connector and sync jobs are not implemented in this milestone.
