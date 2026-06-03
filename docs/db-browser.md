# DB Table Browser

The DB Browser gives administrators read-only visibility into PostgreSQL schemas, tables, columns, and sample rows.

Its first use is inspecting `mdp_staging` data before creating Type B Linked Data Models.

It lists both base tables and views, including curated staging objects such as `mdp_staging.vw_jde_purchase_order_summary`.

## APIs

```text
GET /db-browser/schemas
GET /db-browser/schemas/{schema_name}/tables
GET /db-browser/schemas/{schema_name}/tables/{table_name}/columns
GET /db-browser/schemas/{schema_name}/tables/{table_name}/preview
```

Example staging URLs:

```text
GET /db-browser/schemas
GET /db-browser/schemas/mdp_staging/tables
GET /db-browser/schemas/mdp_staging/tables/stg_jde_supplier/columns
GET /db-browser/schemas/mdp_staging/tables/stg_jde_supplier/preview
```

## Security

- JWT authentication is required.
- Schema and table identifiers must be lowercase snake_case.
- System schemas are excluded.
- The browser does not accept arbitrary SQL.
- Preview queries run only after schema and table existence are verified.
- Preview `limit` defaults to `50` and is capped at `100`.

## Current Limitations

- No Type B mapping UI.
- No Type B outbound API.
- No Oracle connector.
- No sync jobs.
- No ad hoc SQL console.
