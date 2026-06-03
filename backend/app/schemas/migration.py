import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SourceType = Literal["oracle", "postgresql", "sqlserver", "external"]
MigrationTool = Literal["ora2pg", "manual", "external_tool", "native_small_table"]
LoadMode = Literal["full_load", "incremental", "external_bulk", "validation_only"]
RunType = Literal["full_load", "incremental", "validation_only", "external_bulk"]
TriggerType = Literal["manual", "external", "scheduled"]
RunStatus = Literal["pending", "running", "success", "failed", "cancelled"]
ValidationStatus = Literal["pass", "warning", "fail"]
InitialLoadStrategy = Literal["full_table", "row_limited", "time_window", "external_defined"]
WatermarkColumnType = Literal["date", "datetime", "number", "jde_julian_date", "text", "unknown"]
IncrementalStrategy = Literal["none", "greater_than_last_watermark", "greater_equal_last_watermark_with_overlap", "external_defined"]
ValidationLevel = Literal["none", "basic", "key_integrity", "source_target_count", "checksum_sample", "full_reconciliation"]
RunValidationStatus = Literal["not_validated", "pass", "warning", "fail"]


class MigrationJobBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    source_system: str | None = Field(default="JDE Oracle", max_length=150)
    source_connection_id: uuid.UUID | None = None
    source_type: SourceType
    migration_tool: MigrationTool
    source_schema: str | None = Field(default=None, max_length=150)
    source_table: str | None = Field(default=None, max_length=150)
    target_schema: str = Field(default="mdp_staging", min_length=1, max_length=150)
    target_table: str = Field(min_length=1, max_length=150)
    estimated_rows: int | None = Field(default=None, ge=0)
    estimated_size_gb: float | None = Field(default=None, ge=0)
    primary_key_columns: list[str] | None = None
    load_mode: LoadMode
    initial_load_strategy: InitialLoadStrategy | None = None
    max_rows_per_run: int | None = Field(default=None, gt=0)
    time_window_column: str | None = Field(default=None, max_length=150)
    time_window_column_type: WatermarkColumnType | None = None
    time_window_start: str | None = Field(default=None, max_length=150)
    time_window_end: str | None = Field(default=None, max_length=150)
    incremental_strategy: IncrementalStrategy | None = "none"
    watermark_column: str | None = Field(default=None, max_length=150)
    watermark_column_type: WatermarkColumnType | None = None
    last_successful_watermark: str | None = Field(default=None, max_length=150)
    last_successful_run_at: datetime | None = None
    last_run_at: datetime | None = None
    lookback_window_days: int | None = Field(default=None, ge=0)
    lookback_window_minutes: int | None = Field(default=None, ge=0)
    validation_level: ValidationLevel | None = "basic"
    status: str = Field(default="active", max_length=50)
    config: dict[str, Any] | None = None

    @model_validator(mode="after")
    def warn_native_small_table_tooling(self) -> "MigrationJobBase":
        if self.migration_tool == "native_small_table" and self.estimated_rows and self.estimated_rows > 100_000:
            raise ValueError(
                "native_small_table is only for small/manual tests; use ora2pg or external_tool for large JDE tables"
            )
        return self


class MigrationJobCreate(MigrationJobBase):
    pass


class MigrationJobUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    source_system: str | None = Field(default=None, max_length=150)
    source_connection_id: uuid.UUID | None = None
    source_type: SourceType | None = None
    migration_tool: MigrationTool | None = None
    source_schema: str | None = Field(default=None, max_length=150)
    source_table: str | None = Field(default=None, max_length=150)
    target_schema: str | None = Field(default=None, min_length=1, max_length=150)
    target_table: str | None = Field(default=None, min_length=1, max_length=150)
    estimated_rows: int | None = Field(default=None, ge=0)
    estimated_size_gb: float | None = Field(default=None, ge=0)
    primary_key_columns: list[str] | None = None
    load_mode: LoadMode | None = None
    initial_load_strategy: InitialLoadStrategy | None = None
    max_rows_per_run: int | None = Field(default=None, gt=0)
    time_window_column: str | None = Field(default=None, max_length=150)
    time_window_column_type: WatermarkColumnType | None = None
    time_window_start: str | None = Field(default=None, max_length=150)
    time_window_end: str | None = Field(default=None, max_length=150)
    incremental_strategy: IncrementalStrategy | None = None
    watermark_column: str | None = Field(default=None, max_length=150)
    watermark_column_type: WatermarkColumnType | None = None
    last_successful_watermark: str | None = Field(default=None, max_length=150)
    last_successful_run_at: datetime | None = None
    last_run_at: datetime | None = None
    lookback_window_days: int | None = Field(default=None, ge=0)
    lookback_window_minutes: int | None = Field(default=None, ge=0)
    validation_level: ValidationLevel | None = None
    status: str | None = Field(default=None, max_length=50)
    config: dict[str, Any] | None = None


class MigrationRunCreate(BaseModel):
    run_type: RunType = "external_bulk"
    trigger_type: TriggerType = "external"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: RunStatus = "pending"
    source_row_count: int | None = Field(default=None, ge=0)
    target_row_count: int | None = Field(default=None, ge=0)
    rows_loaded: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)
    run_scope: str | None = Field(default=None, max_length=255)
    from_watermark: str | None = Field(default=None, max_length=150)
    to_watermark: str | None = Field(default=None, max_length=150)
    source_min_watermark: str | None = Field(default=None, max_length=150)
    source_max_watermark: str | None = Field(default=None, max_length=150)
    target_min_watermark: str | None = Field(default=None, max_length=150)
    target_max_watermark: str | None = Field(default=None, max_length=150)
    validation_status: RunValidationStatus | None = "not_validated"
    log_text: str | None = None
    error_message: str | None = None


class MigrationRunUpdate(BaseModel):
    run_type: RunType | None = None
    trigger_type: TriggerType | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: RunStatus | None = None
    source_row_count: int | None = Field(default=None, ge=0)
    target_row_count: int | None = Field(default=None, ge=0)
    rows_loaded: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)
    run_scope: str | None = Field(default=None, max_length=255)
    from_watermark: str | None = Field(default=None, max_length=150)
    to_watermark: str | None = Field(default=None, max_length=150)
    source_min_watermark: str | None = Field(default=None, max_length=150)
    source_max_watermark: str | None = Field(default=None, max_length=150)
    target_min_watermark: str | None = Field(default=None, max_length=150)
    target_max_watermark: str | None = Field(default=None, max_length=150)
    validation_status: RunValidationStatus | None = None
    log_text: str | None = None
    error_message: str | None = None


class MigrationValidationRead(BaseModel):
    id: uuid.UUID
    migration_run_id: uuid.UUID
    check_name: str
    source_value: str | None
    target_value: str | None
    status: str
    message: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MigrationRunRead(BaseModel):
    id: uuid.UUID
    migration_job_id: uuid.UUID
    run_type: str
    trigger_type: str
    started_at: datetime | None
    finished_at: datetime | None
    status: str
    source_row_count: int | None
    target_row_count: int | None
    rows_loaded: int | None
    duration_seconds: int | None
    run_scope: str | None
    from_watermark: str | None
    to_watermark: str | None
    source_min_watermark: str | None
    source_max_watermark: str | None
    target_min_watermark: str | None
    target_max_watermark: str | None
    validation_status: str | None
    log_text: str | None
    error_message: str | None
    triggered_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MigrationJobRead(MigrationJobBase):
    id: uuid.UUID
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    latest_run_status: str | None = None
    latest_target_row_count: int | None = None

    model_config = ConfigDict(from_attributes=True)


class TargetValidationResponse(BaseModel):
    status: str
    validation_status: str
    migration_run_id: uuid.UUID
    target_schema: str
    target_table: str
    source_row_count: int | None
    target_row_count: int | None
    row_count_match: bool | None
    validations: list[MigrationValidationRead]
    sample_rows: list[dict[str, Any]]


class MigrationTemplateRead(BaseModel):
    template_key: str
    display_name: str
    description: str
    group: str = "JDE Procurement"
    template_type: str = "ora2pg_external_bulk"
    source_system: str
    source_type: SourceType
    migration_tool: MigrationTool
    source_schema_suggestion: str | None = None
    source_table: str | None = None
    related_source_tables: list[str] | None = None
    target_schema: str
    target_table: str
    primary_key_columns: list[str]
    load_mode: LoadMode
    initial_load_strategy: InitialLoadStrategy | None = None
    incremental_strategy: IncrementalStrategy | None = None
    watermark_column: str | None = None
    watermark_column_type: WatermarkColumnType | None = None
    lookback_window_days: int | None = None
    validation_level: ValidationLevel
    estimated_rows: int | None = None
    estimated_size_gb: float | None = None
    config: dict[str, Any] | None = None


class MigrationTemplateCreateJobRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    source_connection_id: uuid.UUID | None = None
    source_schema: str | None = Field(default=None, max_length=150)
    target_table: str | None = Field(default=None, min_length=1, max_length=150)
    estimated_rows: int | None = Field(default=None, ge=0)
    estimated_size_gb: float | None = Field(default=None, ge=0)
    config: dict[str, Any] | None = None
