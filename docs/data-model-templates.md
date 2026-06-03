# Data Model Templates

## Purpose

Type B Data Model Templates help users create governed data models from migrated JDE procurement staging tables and curated views without manually entering every attribute mapping.

They are the layer after Migration Jobs:

```text
Oracle JDE
-> ora2pg / external bulk loader
-> PostgreSQL mdp_staging
-> Migration Job validation
-> Type B Data Model Template
-> Governed outbound API
-> Apps / BI / AI
```

Templates do not execute ora2pg, run sync jobs, or create new physical tables. They create normal Type B `data_models` records that reuse the existing Type B mapping validation.

## Relationship To Migration Templates

Migration Templates create `migration_jobs` for external ora2pg tracking.

Data Model Templates create Type B governed models after data has landed in PostgreSQL staging.

Example:

- `jde_supplier_master` migration template tracks migration into `mdp_staging.stg_jde_supplier`.
- `jde_supplier` data model template creates the Type B `supplier` model from `mdp_staging.stg_jde_supplier`.

## APIs

All APIs require JWT authentication.

```text
GET /data-model-templates
GET /data-model-templates/{template_key}
POST /data-model-templates/{template_key}/create-model
```

`POST /data-model-templates/{template_key}/create-model` supports overrides:

- `name`
- `display_name`
- `source_schema`
- `source_table`
- `status`
- `config`

If the model name already exists, the API returns `409`.

If the source table or view does not exist, the API returns `422`. In that case, run or validate the related Migration Job first.

## JDE Procurement Templates

| Template | Model | Source | Primary Key | Related Migration Template |
| --- | --- | --- | --- | --- |
| `jde_supplier` | `supplier` | `mdp_staging.stg_jde_supplier` | `supplier_code` | `jde_supplier_master` |
| `jde_purchase_order_summary` | `purchase_order_summary` | `mdp_staging.vw_jde_purchase_order_summary` | `po_no` | `jde_purchase_order_summary_view` |
| `jde_ap_invoice` | `ap_invoice` | `mdp_staging.stg_jde_ap_invoice` | `invoice_no` | `jde_ap_invoice` |
| `jde_po_header` | `purchase_order_header` | `mdp_staging.stg_jde_po_header` | `po_no` | `jde_po_header` |
| `jde_po_line` | `purchase_order_line` | `mdp_staging.stg_jde_po_line` | `po_line_id` | `jde_po_line` |

The PO line template uses `po_line_id` because the MVP mock staging table has that single-column identifier. Composite key support is a future enhancement.

## Demo Flow

1. Seed demo procurement staging data.
2. Open `JDE Demo Flow`.
3. Create the related Migration Job from template.
4. Create the external run record.
5. Validate the PostgreSQL target table/view.
6. Create the Type B model from template.
7. Preview the created model and verify `SUP-1001`.
8. Repeat for `JDE Purchase Order Summary Type B Model` and verify `PO-2026-0001`.

The same model creation can also be done from `Data Models` using `Create from Template`.

## Guided Workflow Page

The `JDE Demo Flow` page is a checklist for demo/UAT:

- staging data readiness
- migration job creation
- migration run recording
- target validation
- Type B model creation
- mapped preview
- outbound API test
- transaction log review

This page does not execute ora2pg. It simulates migration with seeded staging data for demos and records external-run metadata for UAT.

## Production Notes

JDE table layouts and customer naming conventions can vary. These templates are starting points and should be reviewed with the customer DBA/JDE team before production use.

Do not expose raw Oracle or staging tables directly to consuming applications. Create approved Type B models and use outbound APIs.

## Deferred

- Relationship registry
- Knowledge Graph
- Type B multi-table join engine
- ora2pg execution
- Scheduler
- Incremental sync
