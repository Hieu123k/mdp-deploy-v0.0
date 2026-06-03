# Mock JDE Procurement Staging

The `mdp_staging` schema simulates JDE procurement data already migrated into PostgreSQL by an external ETL or database migration tool.

This milestone does not implement an Oracle connector, sync jobs, table browsing, Type B outbound APIs, or Type B data mapping.

## Procurement Flow

```text
Supplier -> Purchase Order Header -> Purchase Order Line -> PO Receipt -> AP Invoice
```

## Simulated JDE Tables

| JDE source | Staging table | Purpose |
| --- | --- | --- |
| `F0101` / `F0401` | `mdp_staging.stg_jde_supplier` | Address Book and Supplier Master |
| `F4301` | `mdp_staging.stg_jde_po_header` | Purchase Order Header |
| `F4311` | `mdp_staging.stg_jde_po_line` | Purchase Order Detail |
| `F43121` | `mdp_staging.stg_jde_po_receipt` | Purchase Order Receiver / Goods Receipt |
| `F0411` | `mdp_staging.stg_jde_ap_invoice` | Accounts Payable Ledger / Supplier Invoice |

## Curated Purchase Order Summary View

`mdp_staging.vw_jde_purchase_order_summary` joins and summarizes the staging tables into one row per purchase order.

It is designed as a single source object for a Type B `purchase_order_summary` data model while the platform still limits Type B models to one source table or view per model.

The view uses:

- `stg_jde_po_header`
- `stg_jde_supplier`
- `stg_jde_po_line`
- `stg_jde_ap_invoice`

Key summary columns include:

- `line_count`
- `total_ordered_quantity`
- `total_received_quantity`
- `open_line_count`
- `invoice_count`
- `total_invoice_amount`
- `total_open_invoice_amount`
- `payment_status_summary`

## Seeded Row Counts

| Table | Rows |
| --- | ---: |
| `stg_jde_supplier` | 5 |
| `stg_jde_po_header` | 5 |
| `stg_jde_po_line` | 5 |
| `stg_jde_po_receipt` | 3 |
| `stg_jde_ap_invoice` | 5 |

## Admin Endpoints

```text
POST /admin/demo/seed-procurement-staging
GET /admin/demo/procurement-staging-summary
```

Both endpoints require JWT authentication.

## SQL Checks

```sql
SELECT * FROM mdp_staging.stg_jde_supplier;
SELECT * FROM mdp_staging.stg_jde_po_header;
SELECT * FROM mdp_staging.stg_jde_po_line;
SELECT * FROM mdp_staging.stg_jde_po_receipt;
SELECT * FROM mdp_staging.stg_jde_ap_invoice;
SELECT * FROM mdp_staging.vw_jde_purchase_order_summary;
```

## DB Browser Checks

The same staging tables can be inspected through the JWT-protected DB Browser:

```text
GET /db-browser/schemas
GET /db-browser/schemas/mdp_staging/tables
GET /db-browser/schemas/mdp_staging/tables/stg_jde_supplier/columns
GET /db-browser/schemas/mdp_staging/tables/stg_jde_supplier/preview
GET /db-browser/schemas/mdp_staging/tables/vw_jde_purchase_order_summary/preview
```

## Current Limitations

- No Oracle JDE connector.
- No sync job scheduler.
- No Type B model mapping.
- No Type B outbound API.
- No staging table browsing UI.
