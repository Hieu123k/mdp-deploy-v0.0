from collections.abc import Mapping
from typing import Any

from sqlalchemy import text


STAGING_SCHEMA = "mdp_staging"
PURCHASE_ORDER_SUMMARY_VIEW = "vw_jde_purchase_order_summary"

TABLE_PRIMARY_KEYS = {
    "stg_jde_supplier": "supplier_code",
    "stg_jde_po_header": "po_no",
    "stg_jde_po_line": "po_line_id",
    "stg_jde_po_receipt": "receipt_no",
    "stg_jde_ap_invoice": "invoice_no",
}

EXPECTED_TABLE_COUNTS = {
    "stg_jde_supplier": 5,
    "stg_jde_po_header": 5,
    "stg_jde_po_line": 5,
    "stg_jde_po_receipt": 3,
    "stg_jde_ap_invoice": 5,
}

TABLE_COLUMNS = {
    "stg_jde_supplier": [
        "supplier_code",
        "supplier_name",
        "tax_code",
        "supplier_type",
        "country",
        "city",
        "address",
        "phone",
        "email",
        "status",
    ],
    "stg_jde_po_header": [
        "po_no",
        "supplier_code",
        "buyer_code",
        "buyer_name",
        "company_code",
        "branch_plant",
        "order_date",
        "currency",
        "po_status",
        "total_amount",
    ],
    "stg_jde_po_line": [
        "po_line_id",
        "po_no",
        "line_no",
        "item_code",
        "item_description",
        "uom",
        "quantity_ordered",
        "quantity_received",
        "unit_cost",
        "line_amount",
        "line_status",
        "promised_date",
    ],
    "stg_jde_po_receipt": [
        "receipt_no",
        "po_no",
        "po_line_id",
        "supplier_code",
        "item_code",
        "receipt_date",
        "quantity_received",
        "receiver_name",
        "receipt_status",
    ],
    "stg_jde_ap_invoice": [
        "invoice_no",
        "supplier_code",
        "po_no",
        "invoice_date",
        "due_date",
        "currency",
        "gross_amount",
        "open_amount",
        "payment_status",
        "invoice_status",
    ],
}

SEED_DATA: dict[str, list[dict[str, Any]]] = {
    "stg_jde_supplier": [
        {
            "supplier_code": "SUP-1001",
            "supplier_name": "ABC Industrial Supplies",
            "tax_code": None,
            "supplier_type": "domestic",
            "country": "VN",
            "city": "Ho Chi Minh City",
            "address": None,
            "phone": None,
            "email": None,
            "status": "active",
        },
        {
            "supplier_code": "SUP-1002",
            "supplier_name": "Vietnam Mechanical Parts Co.",
            "tax_code": None,
            "supplier_type": "domestic",
            "country": "VN",
            "city": "Binh Duong",
            "address": None,
            "phone": None,
            "email": None,
            "status": "active",
        },
        {
            "supplier_code": "SUP-1003",
            "supplier_name": "Global Electrical Equipment Ltd.",
            "tax_code": None,
            "supplier_type": "foreign",
            "country": "SG",
            "city": "Singapore",
            "address": None,
            "phone": None,
            "email": None,
            "status": "active",
        },
        {
            "supplier_code": "SUP-1004",
            "supplier_name": "Mekong Packaging Materials",
            "tax_code": None,
            "supplier_type": "domestic",
            "country": "VN",
            "city": "Can Tho",
            "address": None,
            "phone": None,
            "email": None,
            "status": "active",
        },
        {
            "supplier_code": "SUP-1005",
            "supplier_name": "Saigon Automation Services",
            "tax_code": None,
            "supplier_type": "domestic",
            "country": "VN",
            "city": "Ho Chi Minh City",
            "address": None,
            "phone": None,
            "email": None,
            "status": "inactive",
        },
    ],
    "stg_jde_po_header": [
        {
            "po_no": "PO-2026-0001",
            "supplier_code": "SUP-1001",
            "buyer_code": None,
            "buyer_name": "Buyer A",
            "company_code": "00001",
            "branch_plant": "PLANT-HCM",
            "order_date": "2026-05-01",
            "currency": "VND",
            "po_status": "open",
            "total_amount": 35000000,
        },
        {
            "po_no": "PO-2026-0002",
            "supplier_code": "SUP-1003",
            "buyer_code": None,
            "buyer_name": "Buyer B",
            "company_code": "00001",
            "branch_plant": "PLANT-HCM",
            "order_date": "2026-05-03",
            "currency": "USD",
            "po_status": "received",
            "total_amount": 12000,
        },
        {
            "po_no": "PO-2026-0003",
            "supplier_code": "SUP-1004",
            "buyer_code": None,
            "buyer_name": "Buyer C",
            "company_code": "00002",
            "branch_plant": "PLANT-CT",
            "order_date": "2026-05-05",
            "currency": "VND",
            "po_status": "open",
            "total_amount": 8500000,
        },
        {
            "po_no": "PO-2026-0004",
            "supplier_code": "SUP-1002",
            "buyer_code": None,
            "buyer_name": "Buyer A",
            "company_code": "00001",
            "branch_plant": "PLANT-BD",
            "order_date": "2026-05-08",
            "currency": "VND",
            "po_status": "closed",
            "total_amount": 23000000,
        },
        {
            "po_no": "PO-2026-0005",
            "supplier_code": "SUP-1005",
            "buyer_code": None,
            "buyer_name": "Buyer D",
            "company_code": "00001",
            "branch_plant": "PLANT-HCM",
            "order_date": "2026-05-10",
            "currency": "VND",
            "po_status": "cancelled",
            "total_amount": 5000000,
        },
    ],
    "stg_jde_po_line": [
        {
            "po_line_id": "PO-2026-0001-001",
            "po_no": "PO-2026-0001",
            "line_no": 1,
            "item_code": "PUMP-SEAL-001",
            "item_description": "Mechanical Seal for Pump",
            "uom": "EA",
            "quantity_ordered": 10,
            "quantity_received": 0,
            "unit_cost": 1500000,
            "line_amount": 15000000,
            "line_status": "open",
            "promised_date": "2026-05-20",
        },
        {
            "po_line_id": "PO-2026-0001-002",
            "po_no": "PO-2026-0001",
            "line_no": 2,
            "item_code": "MOTOR-BRG-6205",
            "item_description": "Motor Bearing 6205",
            "uom": "EA",
            "quantity_ordered": 20,
            "quantity_received": 0,
            "unit_cost": 1000000,
            "line_amount": 20000000,
            "line_status": "open",
            "promised_date": "2026-05-21",
        },
        {
            "po_line_id": "PO-2026-0002-001",
            "po_no": "PO-2026-0002",
            "line_no": 1,
            "item_code": "SENSOR-PRESS-16BAR",
            "item_description": "Pressure Sensor 16 Bar",
            "uom": "EA",
            "quantity_ordered": 15,
            "quantity_received": 15,
            "unit_cost": 800,
            "line_amount": 12000,
            "line_status": "received",
            "promised_date": "2026-05-15",
        },
        {
            "po_line_id": "PO-2026-0003-001",
            "po_no": "PO-2026-0003",
            "line_no": 1,
            "item_code": "FILTER-BAG-010",
            "item_description": "Filter Bag 10 Micron",
            "uom": "EA",
            "quantity_ordered": 100,
            "quantity_received": 0,
            "unit_cost": 85000,
            "line_amount": 8500000,
            "line_status": "open",
            "promised_date": "2026-05-25",
        },
        {
            "po_line_id": "PO-2026-0004-001",
            "po_no": "PO-2026-0004",
            "line_no": 1,
            "item_code": "VALVE-BALL-2IN",
            "item_description": "Ball Valve 2 Inch",
            "uom": "EA",
            "quantity_ordered": 30,
            "quantity_received": 30,
            "unit_cost": 766667,
            "line_amount": 23000000,
            "line_status": "closed",
            "promised_date": "2026-05-18",
        },
    ],
    "stg_jde_po_receipt": [
        {
            "receipt_no": "RCV-2026-0001",
            "po_no": "PO-2026-0002",
            "po_line_id": "PO-2026-0002-001",
            "supplier_code": "SUP-1003",
            "item_code": "SENSOR-PRESS-16BAR",
            "receipt_date": "2026-05-15",
            "quantity_received": 15,
            "receiver_name": "Nguyen Van A",
            "receipt_status": "posted",
        },
        {
            "receipt_no": "RCV-2026-0002",
            "po_no": "PO-2026-0004",
            "po_line_id": "PO-2026-0004-001",
            "supplier_code": "SUP-1002",
            "item_code": "VALVE-BALL-2IN",
            "receipt_date": "2026-05-18",
            "quantity_received": 30,
            "receiver_name": "Tran Thi B",
            "receipt_status": "posted",
        },
        {
            "receipt_no": "RCV-2026-0003",
            "po_no": "PO-2026-0001",
            "po_line_id": "PO-2026-0001-001",
            "supplier_code": "SUP-1001",
            "item_code": "PUMP-SEAL-001",
            "receipt_date": "2026-05-20",
            "quantity_received": 5,
            "receiver_name": "Le Van C",
            "receipt_status": "partial",
        },
    ],
    "stg_jde_ap_invoice": [
        {
            "invoice_no": "INV-2026-0001",
            "supplier_code": "SUP-1001",
            "po_no": "PO-2026-0001",
            "invoice_date": "2026-05-21",
            "due_date": "2026-06-20",
            "currency": "VND",
            "gross_amount": 15000000,
            "open_amount": 15000000,
            "payment_status": "unpaid",
            "invoice_status": "approved",
        },
        {
            "invoice_no": "INV-2026-0002",
            "supplier_code": "SUP-1003",
            "po_no": "PO-2026-0002",
            "invoice_date": "2026-05-16",
            "due_date": "2026-06-15",
            "currency": "USD",
            "gross_amount": 12000,
            "open_amount": 0,
            "payment_status": "paid",
            "invoice_status": "posted",
        },
        {
            "invoice_no": "INV-2026-0003",
            "supplier_code": "SUP-1004",
            "po_no": "PO-2026-0003",
            "invoice_date": "2026-05-22",
            "due_date": "2026-06-21",
            "currency": "VND",
            "gross_amount": 8500000,
            "open_amount": 8500000,
            "payment_status": "unpaid",
            "invoice_status": "pending",
        },
        {
            "invoice_no": "INV-2026-0004",
            "supplier_code": "SUP-1002",
            "po_no": "PO-2026-0004",
            "invoice_date": "2026-05-19",
            "due_date": "2026-06-18",
            "currency": "VND",
            "gross_amount": 23000000,
            "open_amount": 0,
            "payment_status": "paid",
            "invoice_status": "posted",
        },
        {
            "invoice_no": "INV-2026-0005",
            "supplier_code": "SUP-1005",
            "po_no": None,
            "invoice_date": "2026-05-23",
            "due_date": "2026-06-22",
            "currency": "VND",
            "gross_amount": 5000000,
            "open_amount": 5000000,
            "payment_status": "unpaid",
            "invoice_status": "pending",
        },
    ],
}


def _dialect_name(executor: Any) -> str:
    bind = getattr(executor, "bind", executor)
    return bind.dialect.name


def _qualified_table(table_name: str, dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return f"{STAGING_SCHEMA}.{table_name}"
    return table_name


def _execute(executor: Any, statement: str, params: Mapping[str, Any] | None = None) -> None:
    executor.execute(text(statement), params or {})


def create_procurement_staging_tables(executor: Any) -> None:
    dialect_name = _dialect_name(executor)
    if dialect_name == "postgresql":
        _execute(executor, f"CREATE SCHEMA IF NOT EXISTS {STAGING_SCHEMA}")

    _execute(
        executor,
        f"""
        CREATE TABLE IF NOT EXISTS {_qualified_table("stg_jde_supplier", dialect_name)} (
            supplier_code TEXT PRIMARY KEY,
            supplier_name TEXT NOT NULL,
            tax_code TEXT NULL,
            supplier_type TEXT NULL,
            country TEXT NULL,
            city TEXT NULL,
            address TEXT NULL,
            phone TEXT NULL,
            email TEXT NULL,
            status TEXT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    _execute(
        executor,
        f"""
        CREATE TABLE IF NOT EXISTS {_qualified_table("stg_jde_po_header", dialect_name)} (
            po_no TEXT PRIMARY KEY,
            supplier_code TEXT NOT NULL,
            buyer_code TEXT NULL,
            buyer_name TEXT NULL,
            company_code TEXT NULL,
            branch_plant TEXT NULL,
            order_date DATE NULL,
            currency TEXT NULL,
            po_status TEXT NULL,
            total_amount DOUBLE PRECISION NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    _execute(
        executor,
        f"""
        CREATE TABLE IF NOT EXISTS {_qualified_table("stg_jde_po_line", dialect_name)} (
            po_line_id TEXT PRIMARY KEY,
            po_no TEXT NOT NULL,
            line_no INTEGER NOT NULL,
            item_code TEXT NULL,
            item_description TEXT NULL,
            uom TEXT NULL,
            quantity_ordered DOUBLE PRECISION NULL,
            quantity_received DOUBLE PRECISION NULL,
            unit_cost DOUBLE PRECISION NULL,
            line_amount DOUBLE PRECISION NULL,
            line_status TEXT NULL,
            promised_date DATE NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    _execute(
        executor,
        f"""
        CREATE TABLE IF NOT EXISTS {_qualified_table("stg_jde_po_receipt", dialect_name)} (
            receipt_no TEXT PRIMARY KEY,
            po_no TEXT NOT NULL,
            po_line_id TEXT NULL,
            supplier_code TEXT NULL,
            item_code TEXT NULL,
            receipt_date DATE NULL,
            quantity_received DOUBLE PRECISION NULL,
            receiver_name TEXT NULL,
            receipt_status TEXT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    _execute(
        executor,
        f"""
        CREATE TABLE IF NOT EXISTS {_qualified_table("stg_jde_ap_invoice", dialect_name)} (
            invoice_no TEXT PRIMARY KEY,
            supplier_code TEXT NOT NULL,
            po_no TEXT NULL,
            invoice_date DATE NULL,
            due_date DATE NULL,
            currency TEXT NULL,
            gross_amount DOUBLE PRECISION NULL,
            open_amount DOUBLE PRECISION NULL,
            payment_status TEXT NULL,
            invoice_status TEXT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )


def seed_procurement_staging_data(executor: Any) -> dict[str, int]:
    create_procurement_staging_tables(executor)
    dialect_name = _dialect_name(executor)

    for table_name, rows in SEED_DATA.items():
        columns = TABLE_COLUMNS[table_name]
        primary_key = TABLE_PRIMARY_KEYS[table_name]
        insert_columns = ", ".join(columns)
        values = ", ".join(f":{column}" for column in columns)
        update_columns = [column for column in columns if column != primary_key]
        update_set = ", ".join(f"{column} = excluded.{column}" for column in update_columns)
        statement = f"""
            INSERT INTO {_qualified_table(table_name, dialect_name)} ({insert_columns})
            VALUES ({values})
            ON CONFLICT ({primary_key}) DO UPDATE SET
                {update_set},
                updated_at = CURRENT_TIMESTAMP
        """
        for row in rows:
            _execute(executor, statement, row)

    create_purchase_order_summary_view(executor)
    return get_procurement_staging_counts(executor)


def create_purchase_order_summary_view(executor: Any) -> None:
    dialect_name = _dialect_name(executor)
    if dialect_name == "postgresql":
        _execute(
            executor,
            f"""
            CREATE OR REPLACE VIEW {STAGING_SCHEMA}.{PURCHASE_ORDER_SUMMARY_VIEW} AS
            WITH line_summary AS (
                SELECT
                    po_no,
                    COUNT(DISTINCT po_line_id)::integer AS line_count,
                    COALESCE(SUM(quantity_ordered), 0)::double precision AS total_ordered_quantity,
                    COALESCE(SUM(quantity_received), 0)::double precision AS total_received_quantity,
                    COUNT(*) FILTER (WHERE line_status = 'open')::integer AS open_line_count,
                    MAX(updated_at) AS lines_updated_at
                FROM {STAGING_SCHEMA}.stg_jde_po_line
                GROUP BY po_no
            ),
            invoice_summary AS (
                SELECT
                    po_no,
                    COUNT(DISTINCT invoice_no)::integer AS invoice_count,
                    COALESCE(SUM(gross_amount), 0)::double precision AS total_invoice_amount,
                    COALESCE(SUM(open_amount), 0)::double precision AS total_open_invoice_amount,
                    MAX(updated_at) AS invoices_updated_at
                FROM {STAGING_SCHEMA}.stg_jde_ap_invoice
                WHERE po_no IS NOT NULL
                GROUP BY po_no
            )
            SELECT
                h.po_no,
                h.supplier_code,
                s.supplier_name,
                h.buyer_code,
                h.buyer_name,
                h.company_code,
                h.branch_plant,
                h.order_date,
                h.currency,
                h.po_status,
                h.total_amount,
                COALESCE(l.line_count, 0) AS line_count,
                COALESCE(l.total_ordered_quantity, 0) AS total_ordered_quantity,
                COALESCE(l.total_received_quantity, 0) AS total_received_quantity,
                COALESCE(l.open_line_count, 0) AS open_line_count,
                COALESCE(i.invoice_count, 0) AS invoice_count,
                COALESCE(i.total_invoice_amount, 0) AS total_invoice_amount,
                COALESCE(i.total_open_invoice_amount, 0) AS total_open_invoice_amount,
                CASE
                    WHEN COALESCE(i.invoice_count, 0) = 0 THEN 'no_invoice'
                    WHEN COALESCE(i.total_open_invoice_amount, 0) = 0 AND COALESCE(i.invoice_count, 0) > 0 THEN 'paid'
                    WHEN COALESCE(i.total_open_invoice_amount, 0) > 0 THEN 'open'
                    ELSE 'unknown'
                END AS payment_status_summary,
                GREATEST(
                    h.updated_at,
                    COALESCE(s.updated_at, h.updated_at),
                    COALESCE(l.lines_updated_at, h.updated_at),
                    COALESCE(i.invoices_updated_at, h.updated_at)
                ) AS updated_at
            FROM {STAGING_SCHEMA}.stg_jde_po_header h
            LEFT JOIN {STAGING_SCHEMA}.stg_jde_supplier s
                ON h.supplier_code = s.supplier_code
            LEFT JOIN line_summary l
                ON h.po_no = l.po_no
            LEFT JOIN invoice_summary i
                ON h.po_no = i.po_no
            """,
        )
        return

    _execute(executor, f"DROP VIEW IF EXISTS {PURCHASE_ORDER_SUMMARY_VIEW}")
    _execute(
        executor,
        f"""
        CREATE VIEW {PURCHASE_ORDER_SUMMARY_VIEW} AS
        WITH line_summary AS (
            SELECT
                po_no,
                COUNT(DISTINCT po_line_id) AS line_count,
                COALESCE(SUM(quantity_ordered), 0) AS total_ordered_quantity,
                COALESCE(SUM(quantity_received), 0) AS total_received_quantity,
                SUM(CASE WHEN line_status = 'open' THEN 1 ELSE 0 END) AS open_line_count,
                MAX(updated_at) AS lines_updated_at
            FROM stg_jde_po_line
            GROUP BY po_no
        ),
        invoice_summary AS (
            SELECT
                po_no,
                COUNT(DISTINCT invoice_no) AS invoice_count,
                COALESCE(SUM(gross_amount), 0) AS total_invoice_amount,
                COALESCE(SUM(open_amount), 0) AS total_open_invoice_amount,
                MAX(updated_at) AS invoices_updated_at
            FROM stg_jde_ap_invoice
            WHERE po_no IS NOT NULL
            GROUP BY po_no
        )
        SELECT
            h.po_no,
            h.supplier_code,
            s.supplier_name,
            h.buyer_code,
            h.buyer_name,
            h.company_code,
            h.branch_plant,
            h.order_date,
            h.currency,
            h.po_status,
            h.total_amount,
            COALESCE(l.line_count, 0) AS line_count,
            COALESCE(l.total_ordered_quantity, 0) AS total_ordered_quantity,
            COALESCE(l.total_received_quantity, 0) AS total_received_quantity,
            COALESCE(l.open_line_count, 0) AS open_line_count,
            COALESCE(i.invoice_count, 0) AS invoice_count,
            COALESCE(i.total_invoice_amount, 0) AS total_invoice_amount,
            COALESCE(i.total_open_invoice_amount, 0) AS total_open_invoice_amount,
            CASE
                WHEN COALESCE(i.invoice_count, 0) = 0 THEN 'no_invoice'
                WHEN COALESCE(i.total_open_invoice_amount, 0) = 0 AND COALESCE(i.invoice_count, 0) > 0 THEN 'paid'
                WHEN COALESCE(i.total_open_invoice_amount, 0) > 0 THEN 'open'
                ELSE 'unknown'
            END AS payment_status_summary,
            MAX(
                h.updated_at,
                COALESCE(s.updated_at, h.updated_at),
                COALESCE(l.lines_updated_at, h.updated_at),
                COALESCE(i.invoices_updated_at, h.updated_at)
            ) AS updated_at
        FROM stg_jde_po_header h
        LEFT JOIN stg_jde_supplier s
            ON h.supplier_code = s.supplier_code
        LEFT JOIN line_summary l
            ON h.po_no = l.po_no
        LEFT JOIN invoice_summary i
            ON h.po_no = i.po_no
        """
    )


def get_procurement_staging_counts(executor: Any) -> dict[str, int]:
    dialect_name = _dialect_name(executor)
    counts: dict[str, int] = {}
    for table_name in EXPECTED_TABLE_COUNTS:
        result = executor.execute(
            text(f"SELECT COUNT(*) FROM {_qualified_table(table_name, dialect_name)}")
        )
        counts[table_name] = int(result.scalar_one())
    return counts


def staging_schema_exists(executor: Any) -> bool:
    dialect_name = _dialect_name(executor)
    if dialect_name != "postgresql":
        return all(staging_table_exists(executor, table) for table in EXPECTED_TABLE_COUNTS)
    result = executor.execute(
        text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema"),
        {"schema": STAGING_SCHEMA},
    )
    return result.first() is not None


def staging_table_exists(executor: Any, table_name: str) -> bool:
    dialect_name = _dialect_name(executor)
    if dialect_name == "postgresql":
        result = executor.execute(
            text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = :schema AND table_name = :table_name
                """
            ),
            {"schema": STAGING_SCHEMA, "table_name": table_name},
        )
        return result.first() is not None
    result = executor.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
        {"table_name": table_name},
    )
    return result.first() is not None
