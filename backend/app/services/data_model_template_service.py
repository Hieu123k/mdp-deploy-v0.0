from copy import deepcopy
from typing import Any

from app.schemas.data_model import DataModelAttribute, DataModelCreate, DataModelTemplateRead


def _attr(
    name: str,
    data_type: str,
    source_column: str | None = None,
    *,
    display_name: str | None = None,
    required: bool = False,
    primary: bool = False,
) -> DataModelAttribute:
    return DataModelAttribute(
        name=name,
        display_name=display_name or name.replace("_", " ").title(),
        data_type=data_type,  # type: ignore[arg-type]
        required=required,
        source_schema="mdp_staging",
        source_table=None,
        source_column=source_column or name,
        is_primary_key=primary,
        sensitivity="internal",
    )


def _with_source(
    attributes: list[DataModelAttribute],
    source_schema: str,
    source_table: str,
) -> list[DataModelAttribute]:
    return [
        attribute.model_copy(update={"source_schema": source_schema, "source_table": source_table})
        for attribute in attributes
    ]


_TEMPLATES: dict[str, DataModelTemplateRead] = {
    "jde_supplier": DataModelTemplateRead(
        template_key="jde_supplier",
        display_name="JDE Supplier Type B Model",
        description="Creates Type B supplier model from migrated JDE supplier staging table.",
        category="procurement",
        domain="procurement",
        entity_type="supplier",
        business_process="procure_to_pay",
        source_system="JDE Oracle",
        source_layer="staging",
        canonical_status="canonical",
        site_scope="enterprise",
        model_name="supplier",
        model_display_name="Supplier",
        primary_key="supplier_code",
        source_schema="mdp_staging",
        source_table="stg_jde_supplier",
        related_migration_template_key="jde_supplier_master",
        related_migration_target_table="mdp_staging.stg_jde_supplier",
        attributes=_with_source(
            [
                _attr("supplier_code", "text", required=True, primary=True),
                _attr("supplier_name", "text", required=True),
                _attr("tax_code", "text"),
                _attr("supplier_type", "text"),
                _attr("country", "text"),
                _attr("city", "text"),
                _attr("status", "text"),
            ],
            "mdp_staging",
            "stg_jde_supplier",
        ),
        config={"template_group": "JDE Procurement"},
    ),
    "jde_purchase_order_summary": DataModelTemplateRead(
        template_key="jde_purchase_order_summary",
        display_name="JDE Purchase Order Summary Type B Model",
        description="Creates Type B purchase_order_summary model from curated JDE purchase order summary view.",
        category="procurement",
        domain="procurement",
        entity_type="purchase_order",
        business_process="procure_to_pay",
        source_system="JDE Oracle",
        source_layer="curated_view",
        canonical_status="curated",
        site_scope="enterprise",
        model_name="purchase_order_summary",
        model_display_name="Purchase Order Summary",
        primary_key="po_no",
        source_schema="mdp_staging",
        source_table="vw_jde_purchase_order_summary",
        related_migration_template_key="jde_purchase_order_summary_view",
        related_migration_target_table="mdp_staging.vw_jde_purchase_order_summary",
        attributes=_with_source(
            [
                _attr("po_no", "text", required=True, primary=True),
                _attr("supplier_code", "text", required=True),
                _attr("supplier_name", "text"),
                _attr("buyer_name", "text"),
                _attr("company_code", "text"),
                _attr("branch_plant", "text"),
                _attr("order_date", "date"),
                _attr("currency", "text"),
                _attr("po_status", "text"),
                _attr("total_amount", "float"),
                _attr("line_count", "integer"),
                _attr("total_ordered_quantity", "float"),
                _attr("total_received_quantity", "float"),
                _attr("open_line_count", "integer"),
                _attr("invoice_count", "integer"),
                _attr("total_invoice_amount", "float"),
                _attr("total_open_invoice_amount", "float"),
                _attr("payment_status_summary", "text"),
                _attr("source_updated_at", "datetime", source_column="updated_at", display_name="Source Updated At"),
            ],
            "mdp_staging",
            "vw_jde_purchase_order_summary",
        ),
        config={"template_group": "JDE Procurement"},
    ),
    "jde_ap_invoice": DataModelTemplateRead(
        template_key="jde_ap_invoice",
        display_name="JDE AP Invoice Type B Model",
        description="Creates Type B AP invoice model from migrated JDE AP invoice staging table.",
        category="procurement",
        domain="procurement",
        entity_type="ap_invoice",
        business_process="procure_to_pay",
        source_system="JDE Oracle",
        source_layer="staging",
        canonical_status="source_aligned",
        site_scope="enterprise",
        model_name="ap_invoice",
        model_display_name="AP Invoice",
        primary_key="invoice_no",
        source_schema="mdp_staging",
        source_table="stg_jde_ap_invoice",
        related_migration_template_key="jde_ap_invoice",
        related_migration_target_table="mdp_staging.stg_jde_ap_invoice",
        attributes=_with_source(
            [
                _attr("invoice_no", "text", required=True, primary=True),
                _attr("supplier_code", "text"),
                _attr("po_no", "text"),
                _attr("invoice_date", "date"),
                _attr("due_date", "date"),
                _attr("currency", "text"),
                _attr("gross_amount", "float"),
                _attr("open_amount", "float"),
                _attr("payment_status", "text"),
                _attr("status", "text", source_column="invoice_status"),
            ],
            "mdp_staging",
            "stg_jde_ap_invoice",
        ),
        config={"template_group": "JDE Procurement"},
    ),
    "jde_po_header": DataModelTemplateRead(
        template_key="jde_po_header",
        display_name="JDE PO Header Type B Model",
        description="Creates Type B purchase order header model from migrated JDE PO header staging table.",
        category="procurement",
        domain="procurement",
        entity_type="purchase_order",
        business_process="procure_to_pay",
        source_system="JDE Oracle",
        source_layer="staging",
        canonical_status="source_aligned",
        site_scope="enterprise",
        model_name="purchase_order_header",
        model_display_name="Purchase Order Header",
        primary_key="po_no",
        source_schema="mdp_staging",
        source_table="stg_jde_po_header",
        related_migration_template_key="jde_po_header",
        related_migration_target_table="mdp_staging.stg_jde_po_header",
        attributes=_with_source(
            [
                _attr("po_no", "text", required=True, primary=True),
                _attr("supplier_code", "text"),
                _attr("buyer_name", "text"),
                _attr("company_code", "text"),
                _attr("branch_plant", "text"),
                _attr("order_date", "date"),
                _attr("currency", "text"),
                _attr("po_status", "text"),
                _attr("total_amount", "float"),
            ],
            "mdp_staging",
            "stg_jde_po_header",
        ),
        config={"template_group": "JDE Procurement"},
    ),
    "jde_po_line": DataModelTemplateRead(
        template_key="jde_po_line",
        display_name="JDE PO Line Type B Model",
        description="Creates Type B purchase order line model from migrated JDE PO line staging table.",
        category="procurement",
        domain="procurement",
        entity_type="purchase_order_line",
        business_process="procure_to_pay",
        source_system="JDE Oracle",
        source_layer="staging",
        canonical_status="source_aligned",
        site_scope="enterprise",
        model_name="purchase_order_line",
        model_display_name="Purchase Order Line",
        primary_key="po_line_id",
        source_schema="mdp_staging",
        source_table="stg_jde_po_line",
        related_migration_template_key="jde_po_line",
        related_migration_target_table="mdp_staging.stg_jde_po_line",
        attributes=_with_source(
            [
                _attr("po_line_id", "text", required=True, primary=True),
                _attr("po_no", "text", required=True),
                _attr("line_no", "integer", required=True),
                _attr("item_code", "text"),
                _attr("item_description", "text"),
                _attr("uom", "text"),
                _attr("quantity_ordered", "float"),
                _attr("quantity_received", "float"),
                _attr("unit_cost", "float"),
                _attr("line_amount", "float"),
                _attr("line_status", "text"),
                _attr("promised_date", "date"),
            ],
            "mdp_staging",
            "stg_jde_po_line",
        ),
        config={"template_group": "JDE Procurement", "composite_key_note": "Composite key support is future; mock staging uses po_line_id."},
    ),
}


def list_data_model_templates() -> list[DataModelTemplateRead]:
    return [deepcopy(template) for template in _TEMPLATES.values()]


def get_data_model_template(template_key: str) -> DataModelTemplateRead | None:
    template = _TEMPLATES.get(template_key)
    return deepcopy(template) if template else None


def data_model_from_template(
    template: DataModelTemplateRead,
    *,
    name: str | None = None,
    display_name: str | None = None,
    source_schema: str | None = None,
    source_table: str | None = None,
    status: str | None = None,
    overrides: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> DataModelCreate:
    schema = source_schema or template.source_schema
    table = source_table or template.source_table
    attributes = [
        attribute.model_copy(update={"source_schema": schema, "source_table": table})
        for attribute in template.attributes
    ]
    payload: dict[str, Any] = {
        "name": name or template.model_name,
        "display_name": display_name or template.model_display_name,
        "type": "B",
        "category": template.category,
        "namespace": f"avenue.demo.{template.domain}.{name or template.model_name}",
        "domain": template.domain,
        "entity_type": template.entity_type,
        "business_process": template.business_process,
        "source_layer": template.source_layer,
        "canonical_status": template.canonical_status,
        "site_scope": template.site_scope,
        "description": template.description,
        "business_definition": f"Governed Type B model created from template {template.template_key}.",
        "owner_department": "Procurement",
        "source_system": template.source_system,
        "primary_key": template.primary_key,
        "refresh_policy": "external_migration",
        "sensitivity_level": "internal",
        "ai_enabled": True,
        "status": status or "active",
        "attributes": attributes,
        "relationships": [],
    }
    if overrides:
        payload.update(overrides)
    merged_config = {**(template.config or {})}
    if config:
        merged_config.update(config)
    if merged_config:
        payload["relationships"] = [{"type": "template_metadata", "config": merged_config}]
    return DataModelCreate.model_validate(payload)
