import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
ALLOWED_DATA_TYPES = {"text", "integer", "float", "boolean", "date", "datetime", "json"}
SYSTEM_COLUMN_NAMES = {"id", "raw_payload", "created_at", "updated_at"}

DomainValue = Literal[
    "master_data",
    "procurement",
    "inventory",
    "production",
    "quality",
    "maintenance",
    "asset",
    "energy",
    "finance",
    "sales",
    "logistics",
    "iiot",
    "other",
]
BusinessProcessValue = Literal[
    "procure_to_pay",
    "order_to_cash",
    "plan_to_produce",
    "quality_management",
    "maintenance_management",
    "inventory_management",
    "asset_management",
    "energy_management",
    "iiot_monitoring",
    "other",
]
SourceLayerValue = Literal[
    "source",
    "staging",
    "canonical",
    "curated_view",
    "analytical",
    "external_api",
    "generated_table",
]
CanonicalStatusValue = Literal[
    "source_aligned",
    "canonical",
    "curated",
    "experimental",
    "deprecated",
]
SiteScopeValue = Literal[
    "enterprise",
    "site",
    "area",
    "line",
    "work_center",
    "asset",
    "not_applicable",
]


class DataModelAttribute(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    display_name: str | None = Field(default=None, max_length=255)
    data_type: Literal["text", "integer", "float", "boolean", "date", "datetime", "json"]
    required: bool = False
    description: str | None = None
    source_path: str | None = None
    source_schema: str | None = None
    source_table: str | None = None
    source_column: str | None = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    reference_model: str | None = None
    reference_attribute: str | None = None
    sensitivity: str | None = None
    synonyms: list[str] | None = None

    @model_validator(mode="after")
    def validate_attribute_name(self) -> "DataModelAttribute":
        if not SNAKE_CASE_PATTERN.fullmatch(self.name):
            raise ValueError("Attribute name must be lowercase snake_case")
        for field_name in ("source_schema", "source_table", "source_column"):
            value = getattr(self, field_name)
            if value is not None and not SNAKE_CASE_PATTERN.fullmatch(value):
                raise ValueError(f"{field_name} must be lowercase snake_case")
        return self


class DataModelBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    display_name: str = Field(min_length=1, max_length=255)
    type: Literal["A", "B"]
    category: str | None = Field(default=None, max_length=100)
    namespace: str | None = Field(default=None, max_length=255)
    domain: DomainValue | None = None
    entity_type: str | None = Field(default=None, max_length=150)
    business_process: BusinessProcessValue | None = None
    source_layer: SourceLayerValue | None = None
    canonical_status: CanonicalStatusValue | None = None
    site_scope: SiteScopeValue | None = None
    description: str | None = None
    business_definition: str | None = None
    owner_department: str | None = Field(default=None, max_length=150)
    source_system: str | None = Field(default=None, max_length=150)
    primary_key: str | None = Field(default=None, max_length=150)
    attributes: list[DataModelAttribute] = Field(min_length=1)
    relationships: list[dict[str, Any]] | None = None
    refresh_policy: str | None = Field(default=None, max_length=100)
    sensitivity_level: str = Field(default="internal", max_length=50)
    ai_enabled: bool = True
    status: str = Field(default="active", max_length=50)

    @model_validator(mode="after")
    def validate_model(self) -> "DataModelBase":
        if not SNAKE_CASE_PATTERN.fullmatch(self.name):
            raise ValueError("Data model name must be lowercase snake_case")
        if self.namespace is not None and not NAMESPACE_PATTERN.fullmatch(self.namespace):
            raise ValueError("namespace must be a lowercase dot-separated path")
        if self.entity_type is not None and not SNAKE_CASE_PATTERN.fullmatch(self.entity_type):
            raise ValueError("entity_type must be lowercase snake_case")

        attribute_names = [attribute.name for attribute in self.attributes]
        if len(attribute_names) != len(set(attribute_names)):
            raise ValueError("Attribute names must be unique")
        conflicting_columns = sorted(set(attribute_names).intersection(SYSTEM_COLUMN_NAMES))
        if conflicting_columns:
            raise ValueError(
                f"Attribute names conflict with system columns: {', '.join(conflicting_columns)}"
            )

        primary_attributes = [
            attribute.name for attribute in self.attributes if attribute.is_primary_key
        ]

        if self.primary_key and self.primary_key not in attribute_names:
            raise ValueError("primary_key must match one of the attribute names")

        if primary_attributes:
            if len(primary_attributes) > 1:
                raise ValueError("Only one attribute can be marked as primary key")
            if self.primary_key and self.primary_key != primary_attributes[0]:
                raise ValueError("primary_key must match the attribute marked as primary key")
            self.primary_key = primary_attributes[0]

        source_table = next(
            (attribute.source_table for attribute in self.attributes if attribute.source_table),
            None,
        )
        if self.domain is None and self.category == "procurement":
            self.domain = "procurement"
        if self.source_layer is None:
            if self.type == "A":
                self.source_layer = "generated_table"
            elif self.type == "B" and source_table:
                if source_table.startswith("stg_"):
                    self.source_layer = "staging"
                elif source_table.startswith("vw_"):
                    self.source_layer = "curated_view"
        if self.canonical_status is None:
            self.canonical_status = "experimental"
        if self.site_scope is None:
            self.site_scope = "enterprise"

        return self


class DataModelCreate(DataModelBase):
    # Type B "latest version only" dedup. Input-only here; persisted ADDITIVELY inside the
    # ``relationships`` JSON (no new DB column) and surfaced back as derived fields on read.
    latest_only: bool = False
    recency_column: str | None = Field(default=None, max_length=150)


class DataModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    type: Literal["A", "B"] | None = None
    category: str | None = Field(default=None, max_length=100)
    namespace: str | None = Field(default=None, max_length=255)
    domain: DomainValue | None = None
    entity_type: str | None = Field(default=None, max_length=150)
    business_process: BusinessProcessValue | None = None
    source_layer: SourceLayerValue | None = None
    canonical_status: CanonicalStatusValue | None = None
    site_scope: SiteScopeValue | None = None
    description: str | None = None
    business_definition: str | None = None
    owner_department: str | None = Field(default=None, max_length=150)
    source_system: str | None = Field(default=None, max_length=150)
    primary_key: str | None = Field(default=None, max_length=150)
    attributes: list[DataModelAttribute] | None = Field(default=None, min_length=1)
    relationships: list[dict[str, Any]] | None = None
    refresh_policy: str | None = Field(default=None, max_length=100)
    sensitivity_level: str | None = Field(default=None, max_length=50)
    ai_enabled: bool | None = None
    status: str | None = Field(default=None, max_length=50)
    latest_only: bool | None = None
    recency_column: str | None = Field(default=None, max_length=150)

    @model_validator(mode="after")
    def validate_partial_names(self) -> "DataModelUpdate":
        if self.name is not None and not SNAKE_CASE_PATTERN.fullmatch(self.name):
            raise ValueError("Data model name must be lowercase snake_case")
        if self.namespace is not None and not NAMESPACE_PATTERN.fullmatch(self.namespace):
            raise ValueError("namespace must be a lowercase dot-separated path")
        if self.entity_type is not None and not SNAKE_CASE_PATTERN.fullmatch(self.entity_type):
            raise ValueError("entity_type must be lowercase snake_case")
        return self


class DataModelRead(DataModelBase):
    id: uuid.UUID
    generated_table: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def source_schema(self) -> str | None:
        values = {
            attribute.source_schema
            for attribute in self.attributes
            if attribute.source_schema is not None
        }
        return values.pop() if len(values) == 1 else None

    @computed_field
    @property
    def source_table(self) -> str | None:
        values = {
            attribute.source_table
            for attribute in self.attributes
            if attribute.source_table is not None
        }
        return values.pop() if len(values) == 1 else None

    def _latest_config(self) -> dict[str, Any] | None:
        # The dedup config lives as one ``{"type": "latest_config", ...}`` entry in the SHARED
        # relationships JSON (no dedicated column) - surface it so Edit can restore the toggle.
        for relationship in self.relationships or []:
            if isinstance(relationship, dict) and relationship.get("type") == "latest_config":
                return relationship
        return None

    @computed_field
    @property
    def latest_only(self) -> bool:
        config = self._latest_config()
        return bool(config.get("latest_only")) if config else False

    @computed_field
    @property
    def recency_column(self) -> str | None:
        config = self._latest_config()
        return config.get("recency_column") if config else None


class DataModelTemplateRead(BaseModel):
    template_key: str
    display_name: str
    description: str
    category: str
    domain: DomainValue
    entity_type: str
    business_process: BusinessProcessValue
    source_system: str
    source_layer: SourceLayerValue
    canonical_status: CanonicalStatusValue
    site_scope: SiteScopeValue
    model_name: str
    model_display_name: str
    model_type: Literal["B"] = "B"
    primary_key: str
    source_schema: str
    source_table: str
    attributes: list[DataModelAttribute]
    related_migration_template_key: str | None = None
    related_migration_target_table: str | None = None
    config: dict[str, Any] | None = None


class DataModelTemplateCreateModelRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    source_schema: str | None = Field(default=None, max_length=150)
    source_table: str | None = Field(default=None, max_length=150)
    status: str | None = Field(default=None, max_length=50)
    overrides: dict[str, Any] | None = None
    config: dict[str, Any] | None = None


class DataModelTemplateCreateModelResponse(BaseModel):
    status: str
    data_model: DataModelRead
    warnings: list[dict[str, str]] = []


class TypeBParseSqlRequest(BaseModel):
    """Prompt 52: a subset SELECT to parse into the builder plan (NEVER executed). primary_key /
    latest_only / recency_column are builder toggles carried through so the round-trip preserves them."""

    sql: str
    primary_key: str | None = Field(default=None, max_length=150)
    latest_only: bool = False
    recency_column: str | None = Field(default=None, max_length=150)


class TypeBGenerateSqlRequest(BaseModel):
    """Prompt 52: the structured builder plan to render as canonical subset SQL text (no DB access)."""

    base: dict[str, Any] | None = None
    attributes: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] | None = None
    primary_key: str | None = Field(default=None, max_length=150)
    latest_only: bool = False
    recency_column: str | None = Field(default=None, max_length=150)
