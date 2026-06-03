# Data Model Design

Data models describe business objects in Avenue Manufacturing Data Platform (Avenue MDP). The current foundation stores metadata, creates generated PostgreSQL storage tables for Type A models, and exposes dynamic inbound/outbound REST APIs for Type A models.

## Model Types

### Type A: Ingested Model

Type A models describe flat JSON business data that will later be received through inbound APIs and stored in generated PostgreSQL tables. When a Type A model is created, the platform creates a table in the `mdp_data` schema.

Examples:

- `invoice`
- `purchase_order`
- `quality_result`
- `production_order`

### Type B: Linked Model

Type B models describe data linked or mapped from existing PostgreSQL staging tables. These staging tables may later receive data from ERP or database sources such as Oracle JDE or SQL Server. Type B models do not create generated tables.

For the MVP, Type B models support one source table per model. Each mapped attribute must include:

- `source_schema`
- `source_table`
- `source_column`

The backend validates that the schema, table, and column exist before saving the model or previewing rows.

Attribute names may differ from source column names. For example, a model attribute named `supplier_no` can map to `source_column: "supplier_code"`. Missing `source_column` is a mapping configuration error, not a nullable data value.

Examples:

- `supplier`
- `inventory_transaction`

## Attributes JSON Structure

Each data model has a required non-empty `attributes` array. Each attribute supports:

- `name`: lowercase snake_case technical name
- `display_name`: human-readable name
- `data_type`: one of `text`, `integer`, `float`, `boolean`, `date`, `datetime`, `json`
- `required`: whether a value is required
- `description`: business or technical description
- `source_path`: JSONPath-style source location for Type A models
- `source_schema`: source schema for Type B models
- `source_table`: staging table for Type B models
- `source_column`: staging column for Type B models
- `is_primary_key`: marks the model primary key attribute
- `is_foreign_key`: marks a relationship attribute
- `reference_model`: referenced data model name
- `reference_attribute`: referenced attribute name
- `sensitivity`: attribute-level sensitivity classification
- `synonyms`: alternate business terms for semantic search and AI use

If `primary_key` is provided at the model level, it must match one of the attribute names. If an attribute has `is_primary_key=true`, the model primary key is set to that attribute. For Type B models, the primary key attribute must map to a valid source column. Nullable source metadata is returned as a validation warning instead of a hard failure.

Attribute names cannot conflict with generated system columns:

- `id`
- `raw_payload`
- `created_at`
- `updated_at`

## Generated Tables

Generated tables use this naming convention:

```text
mdp_data.dm_{model_name}
```

Examples:

- `invoice` -> `mdp_data.dm_invoice`
- `purchase_order` -> `mdp_data.dm_purchase_order`
- `quality_result` -> `mdp_data.dm_quality_result`

Each generated table includes system columns:

- `id UUID PRIMARY KEY`
- `raw_payload JSONB NULL`
- `created_at TIMESTAMP DEFAULT now()`
- `updated_at TIMESTAMP DEFAULT now()`

Each model attribute creates one data column using this mapping:

| Attribute type | PostgreSQL type |
| --- | --- |
| `text` | `TEXT` |
| `integer` | `INTEGER` |
| `float` | `DOUBLE PRECISION` |
| `boolean` | `BOOLEAN` |
| `date` | `DATE` |
| `datetime` | `TIMESTAMP` |
| `json` | `JSONB` |

Current limitations:

- Updating a data model does not alter the generated table. Schema evolution will be handled in a later milestone.
- Deactivating a data model does not drop the generated table. Archival and drop policy will be handled later.
- Updating a data model does not alter inbound/outbound behavior beyond metadata returned by the APIs.

## AI-Ready Metadata

The metadata fields prepare the platform for later AI, semantic layer, and knowledge graph work:

- `display_name`
- `description`
- `business_definition`
- `owner_department`
- `source_system`
- `sensitivity_level`
- `ai_enabled`
- attribute `synonyms`
- relationship metadata

## Classification and Namespace Metadata

Avenue MDP also stores lightweight classification fields on each data model. These fields organize the model catalog now and prepare the platform for future canonical data model management, semantic search, IIoT hierarchy integration, knowledge graph work, and AI access.

Fields:

- `namespace`: lowercase dot-separated path such as `avenue.demo.procurement.supplier`
- `domain`: controlled domain such as `master_data`, `procurement`, `inventory`, `production`, `quality`, `maintenance`, `asset`, `energy`, `finance`, `sales`, `logistics`, `iiot`, or `other`
- `entity_type`: lowercase snake_case business object type such as `supplier`, `purchase_order`, `ap_invoice`, `asset`, `quality_result`, `telemetry`, or `event`
- `business_process`: controlled process such as `procure_to_pay`, `order_to_cash`, `plan_to_produce`, `quality_management`, `maintenance_management`, `inventory_management`, `asset_management`, `energy_management`, `iiot_monitoring`, or `other`
- `source_layer`: `source`, `staging`, `canonical`, `curated_view`, `analytical`, `external_api`, or `generated_table`
- `canonical_status`: `source_aligned`, `canonical`, `curated`, `experimental`, or `deprecated`
- `site_scope`: `enterprise`, `site`, `area`, `line`, `work_center`, `asset`, or `not_applicable`

Default behavior:

- `category=procurement` defaults `domain` to `procurement`.
- Type A models default `source_layer` to `generated_table`.
- Type B models mapped to source objects beginning with `stg_` default `source_layer` to `staging`.
- Type B models mapped to source objects beginning with `vw_` default `source_layer` to `curated_view`.
- `canonical_status` defaults to `experimental`.
- `site_scope` defaults to `enterprise`.

These fields are metadata only in the MVP. Full UNS/MQTT, IIoT time-series storage, semantic query, knowledge graph, and AI agents are intentionally deferred to later phases.

## Example Type A: Invoice

```json
{
  "name": "invoice",
  "display_name": "Invoice",
  "type": "A",
  "category": "finance",
  "description": "Invoice data received from external systems",
  "business_definition": "A commercial document issued by a supplier for payment",
  "owner_department": "Finance",
  "source_system": "External API",
  "primary_key": "invoice_no",
  "sensitivity_level": "internal",
  "ai_enabled": true,
  "attributes": [
    {
      "name": "invoice_no",
      "display_name": "Invoice Number",
      "data_type": "text",
      "required": true,
      "description": "Unique invoice number",
      "source_path": "$.invoice_no",
      "is_primary_key": true,
      "sensitivity": "internal",
      "synonyms": ["invoice id", "invoice code"]
    },
    {
      "name": "supplier_code",
      "display_name": "Supplier Code",
      "data_type": "text",
      "required": true,
      "description": "Supplier identifier",
      "source_path": "$.supplier_code",
      "is_foreign_key": true,
      "reference_model": "supplier",
      "reference_attribute": "supplier_code",
      "sensitivity": "internal",
      "synonyms": ["vendor code", "supplier id"]
    },
    {
      "name": "amount",
      "display_name": "Amount",
      "data_type": "float",
      "required": true,
      "description": "Invoice amount",
      "source_path": "$.amount",
      "sensitivity": "confidential"
    },
    {
      "name": "invoice_date",
      "display_name": "Invoice Date",
      "data_type": "date",
      "required": false,
      "description": "Invoice issue date",
      "source_path": "$.invoice_date"
    }
  ]
}
```

## Example Type B: Supplier

```json
{
  "name": "supplier",
  "display_name": "Supplier",
  "type": "B",
  "category": "procurement",
  "description": "Supplier master data linked from JDE staging table",
  "business_definition": "A business entity that provides goods or services",
  "owner_department": "Procurement",
  "source_system": "JDE ERP",
  "primary_key": "supplier_code",
  "sensitivity_level": "internal",
  "ai_enabled": true,
  "attributes": [
    {
      "name": "supplier_code",
      "display_name": "Supplier Code",
      "data_type": "text",
      "required": true,
      "description": "Supplier code from JDE Address Book",
      "source_schema": "mdp_staging",
      "source_table": "stg_jde_supplier",
      "source_column": "supplier_code",
      "is_primary_key": true,
      "sensitivity": "internal",
      "synonyms": ["vendor code", "supplier id"]
    },
    {
      "name": "supplier_name",
      "display_name": "Supplier Name",
      "data_type": "text",
      "required": true,
      "description": "Supplier name from JDE Address Book",
      "source_schema": "mdp_staging",
      "source_table": "stg_jde_supplier",
      "source_column": "supplier_name",
      "sensitivity": "internal",
      "synonyms": ["vendor name"]
    }
  ]
}
```

## Example Type B: Supplier From MVP Staging

```json
{
  "name": "supplier",
  "display_name": "Supplier",
  "type": "B",
  "primary_key": "supplier_code",
  "attributes": [
    {
      "name": "supplier_code",
      "display_name": "Supplier Code",
      "data_type": "text",
      "required": true,
      "source_schema": "mdp_staging",
      "source_table": "stg_jde_supplier",
      "source_column": "supplier_code",
      "is_primary_key": true,
      "sensitivity": "internal",
      "synonyms": ["vendor code", "supplier id"]
    },
    {
      "name": "supplier_name",
      "display_name": "Supplier Name",
      "data_type": "text",
      "required": true,
      "source_schema": "mdp_staging",
      "source_table": "stg_jde_supplier",
      "source_column": "supplier_name"
    },
    {
      "name": "country",
      "display_name": "Country",
      "data_type": "text",
      "source_schema": "mdp_staging",
      "source_table": "stg_jde_supplier",
      "source_column": "country"
    },
    {
      "name": "status",
      "display_name": "Status",
      "data_type": "text",
      "source_schema": "mdp_staging",
      "source_table": "stg_jde_supplier",
      "source_column": "status"
    }
  ]
}
```

## Example Type B: Purchase Order

```json
{
  "name": "purchase_order",
  "display_name": "Purchase Order",
  "type": "B",
  "primary_key": "po_no",
  "attributes": [
    {
      "name": "po_no",
      "display_name": "PO Number",
      "data_type": "text",
      "required": true,
      "source_schema": "mdp_staging",
      "source_table": "stg_jde_po_header",
      "source_column": "po_no",
      "is_primary_key": true
    },
    {
      "name": "supplier_code",
      "display_name": "Supplier Code",
      "data_type": "text",
      "source_schema": "mdp_staging",
      "source_table": "stg_jde_po_header",
      "source_column": "supplier_code"
    },
    {
      "name": "order_date",
      "display_name": "Order Date",
      "data_type": "date",
      "source_schema": "mdp_staging",
      "source_table": "stg_jde_po_header",
      "source_column": "order_date"
    },
    {
      "name": "total_amount",
      "display_name": "Total Amount",
      "data_type": "float",
      "source_schema": "mdp_staging",
      "source_table": "stg_jde_po_header",
      "source_column": "total_amount"
    }
  ]
}
```

## Example Type B: Purchase Order Summary View

For multi-table procurement context, the MVP uses a curated PostgreSQL view:

```text
mdp_staging.vw_jde_purchase_order_summary
```

This keeps Type B mapping simple because the model still maps to one source object.

```json
{
  "name": "purchase_order_summary",
  "display_name": "Purchase Order Summary",
  "type": "B",
  "primary_key": "po_no",
  "attributes": [
    {
      "name": "po_no",
      "display_name": "PO Number",
      "data_type": "text",
      "required": true,
      "source_schema": "mdp_staging",
      "source_table": "vw_jde_purchase_order_summary",
      "source_column": "po_no",
      "is_primary_key": true
    },
    {
      "name": "supplier_name",
      "display_name": "Supplier Name",
      "data_type": "text",
      "source_schema": "mdp_staging",
      "source_table": "vw_jde_purchase_order_summary",
      "source_column": "supplier_name"
    },
    {
      "name": "line_count",
      "display_name": "Line Count",
      "data_type": "integer",
      "source_schema": "mdp_staging",
      "source_table": "vw_jde_purchase_order_summary",
      "source_column": "line_count"
    },
    {
      "name": "payment_status_summary",
      "display_name": "Payment Status Summary",
      "data_type": "text",
      "source_schema": "mdp_staging",
      "source_table": "vw_jde_purchase_order_summary",
      "source_column": "payment_status_summary"
    }
  ]
}
```

## Type B Mapping APIs

```text
POST /data-models/type-b/validate-mapping
POST /data-models/type-b/preview
GET /data-models/{id}/mapped-preview
```

These APIs require JWT authentication. Preview returns mapped rows using model attribute names, not source column names.

Validation responses include a `warnings` array. Primary key configuration errors still fail, but nullable source metadata is advisory for now. For PostgreSQL views, `information_schema` may report columns as nullable even when the underlying source is logically non-null, so view primary key nullability produces this warning instead of a 422:

```json
{
  "field": "primary_key",
  "message": "Primary key source column is from a view. Nullability cannot be reliably enforced by information_schema."
}
```

Current limitations:

- One source table per Type B model.
- No Oracle connector or sync jobs yet.

## Type B Mapping UI Flow

The Data Models page includes a Type B Mapping Designer for creating linked models without writing JSON manually. The Admin UI now keeps system-backed choices in selectors: source schema, source table/view, source column, platform data type, sensitivity, category, source system, owner department, and the primary key flag.

Basic flow:

1. Choose `Type B: Linked Model`.
2. Enter the model business metadata.
3. Select a source schema, usually `mdp_staging`.
4. Select a source table or view.
5. Click `Generate Attributes from Source Columns`, or add mapped attributes manually.
6. Select one primary key attribute.
7. Validate the mapping.
8. Preview mapped rows.
9. Save the model.

Generated attributes use the source column name by default, but the attribute name can be edited. Reserved platform system names are renamed automatically in the UI:

- `id` -> `source_id`
- `created_at` -> `source_created_at`
- `updated_at` -> `source_updated_at`
- `raw_payload` -> `source_raw_payload`

The original `source_column` mapping is preserved, so a source column named `updated_at` can still be exposed as the model attribute `source_updated_at`.

For `supplier`, select `mdp_staging.stg_jde_supplier` and mark `supplier_code` as the primary key. Suggested fields are `supplier_code`, `supplier_name`, `tax_code`, `supplier_type`, `country`, `city`, and `status`.

For `purchase_order_summary`, select `mdp_staging.vw_jde_purchase_order_summary` and mark `po_no` as the primary key. Suggested fields are `po_no`, `supplier_code`, `supplier_name`, `buyer_name`, `company_code`, `branch_plant`, `order_date`, `currency`, `po_status`, `total_amount`, `line_count`, `total_ordered_quantity`, `total_received_quantity`, `open_line_count`, `invoice_count`, `total_invoice_amount`, `total_open_invoice_amount`, and `payment_status_summary`.

Type A and Type B differ in the UI:

- Type A creates a generated PostgreSQL table for ingested data.
- Type B links to an existing staging table or view and does not create a new table.

## Admin Demo Flow

The UI demo path for Type B linked models is:

1. Seed the mock JDE procurement staging tables from `Demo Data`.
2. Inspect `mdp_staging` tables and views from `DB Browser`.
3. Create the `supplier` Type B model from `stg_jde_supplier`.
4. Create the `purchase_order_summary` Type B model from `vw_jde_purchase_order_summary`.
5. Query both saved models from `Data Browser`, which calls the governed outbound APIs.
6. Create an API key scoped to selected models and directions from `API Keys`.
7. Confirm JWT/API-key activity in `Transactions`.
