"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Eye,
  History,
  Pencil,
  PlayCircle,
  Power,
  RotateCcw,
  ShieldCheck,
  SquarePen,
} from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Modal } from "@/components/ui/Modal";
import { Select } from "@/components/ui/Select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { Ora2pgMigrationDashboard } from "@/components/Ora2pgMigrationDashboard";
import {
  ApiError,
  apiPath,
  createMigrationJobFromTemplate,
  createMigrationJob,
  createMigrationRun,
  listMigrationTemplates,
  deleteMigrationJob,
  getMigrationJob,
  getMigrationRun,
  listMigrationJobs,
  listMigrationRuns,
  MIGRATION_INCREMENTAL_STRATEGIES,
  MIGRATION_INITIAL_LOAD_STRATEGIES,
  MIGRATION_LOAD_MODES,
  MIGRATION_RUN_STATUSES,
  MIGRATION_RUN_VALIDATION_STATUSES,
  MIGRATION_SOURCE_TYPES,
  MIGRATION_TOOLS,
  MIGRATION_VALIDATION_LEVELS,
  MIGRATION_WATERMARK_TYPES,
  updateMigrationJob,
  updateMigrationRun,
  validateMigrationTarget,
  type MigrationJob,
  type MigrationRun,
  type MigrationTemplate,
  type TargetValidationResult,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const RUN_TYPES = ["full_load", "incremental", "validation_only", "external_bulk"];
const TRIGGER_TYPES = ["manual", "external", "scheduled"];
const JOB_STATUSES = ["active", "inactive"];

type JobMode = "create" | "edit";
type RunMode = "create" | "edit" | "view";

type JobForm = {
  name: string;
  description: string;
  source_system: string;
  source_connection_id: string;
  source_type: string;
  migration_tool: string;
  source_schema: string;
  source_table: string;
  target_schema: string;
  target_table: string;
  estimated_rows: string;
  estimated_size_gb: string;
  primary_key_columns: string;
  load_mode: string;
  initial_load_strategy: string;
  max_rows_per_run: string;
  time_window_column: string;
  time_window_column_type: string;
  time_window_start: string;
  time_window_end: string;
  incremental_strategy: string;
  watermark_column: string;
  watermark_column_type: string;
  lookback_window_days: string;
  lookback_window_minutes: string;
  validation_level: string;
  status: string;
  config_json: string;
};

type RunForm = {
  run_type: string;
  trigger_type: string;
  status: string;
  started_at: string;
  finished_at: string;
  source_row_count: string;
  target_row_count: string;
  rows_loaded: string;
  duration_seconds: string;
  run_scope: string;
  from_watermark: string;
  to_watermark: string;
  source_min_watermark: string;
  source_max_watermark: string;
  target_min_watermark: string;
  target_max_watermark: string;
  validation_status: string;
  ora2pg_config_file: string;
  ora2pg_command: string;
  ora2pg_log_file: string;
  source_table_size_gb: string;
  target_table_size_gb: string;
  rows_per_second: string;
  log_text: string;
  error_message: string;
};

type TemplateForm = {
  name: string;
  source_connection_id: string;
  source_schema: string;
  target_table: string;
  estimated_rows: string;
  estimated_size_gb: string;
  config_json: string;
};

function badgeTone(value?: string | null): BadgeTone {
  if (value === "success" || value === "active" || value === "pass") return "success";
  if (value === "failed" || value === "fail" || value === "inactive" || value === "cancelled") return "danger";
  if (value === "running" || value === "warning" || value === "pending") return "warning";
  if (value === "ora2pg" || value === "external_bulk") return "info";
  return "neutral";
}

function titleize(value?: string | null): string {
  return value ? value.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase()) : "-";
}

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function formatDate(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function toDateTimeInput(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset();
  const local = new Date(date.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 16);
}

function fromDateTimeInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

function parseNullableNumber(value: string): number | null {
  const trimmed = value.trim();
  return trimmed ? Number(trimmed) : null;
}

function parseStringList(value: string): string[] | null {
  const items = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return items.length ? items : null;
}

function prettyJson(value: unknown): string {
  if (!value) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "";
  }
}

const ORA2PG_METADATA_BEGIN = "--- ora2pg_metadata ---";
const ORA2PG_METADATA_END = "--- end_ora2pg_metadata ---";
const ORA2PG_METADATA_FIELDS = [
  "ora2pg_config_file",
  "ora2pg_command",
  "ora2pg_log_file",
  "source_table_size_gb",
  "target_table_size_gb",
  "rows_per_second",
] as const;

type Ora2pgMetadataField = (typeof ORA2PG_METADATA_FIELDS)[number];

function stripOra2pgMetadata(logText?: string | null): string {
  if (!logText) return "";
  const start = logText.indexOf(ORA2PG_METADATA_BEGIN);
  const end = logText.indexOf(ORA2PG_METADATA_END);
  if (start === -1 || end === -1 || end < start) return logText;
  return `${logText.slice(0, start)}${logText.slice(end + ORA2PG_METADATA_END.length)}`.trim();
}

function parseOra2pgMetadata(logText?: string | null): Record<Ora2pgMetadataField, string> {
  const metadata = Object.fromEntries(ORA2PG_METADATA_FIELDS.map((field) => [field, ""])) as Record<Ora2pgMetadataField, string>;
  if (!logText) return metadata;
  const start = logText.indexOf(ORA2PG_METADATA_BEGIN);
  const end = logText.indexOf(ORA2PG_METADATA_END);
  if (start === -1 || end === -1 || end < start) return metadata;
  const block = logText.slice(start + ORA2PG_METADATA_BEGIN.length, end);
  for (const line of block.split(/\r?\n/)) {
    const separator = line.indexOf(":");
    if (separator === -1) continue;
    const key = line.slice(0, separator).trim() as Ora2pgMetadataField;
    const value = line.slice(separator + 1).trim();
    if (ORA2PG_METADATA_FIELDS.includes(key)) metadata[key] = value;
  }
  return metadata;
}

function buildLogTextWithOra2pgMetadata(form: RunForm): string | null {
  const baseLog = stripOra2pgMetadata(form.log_text).trim();
  const lines = ORA2PG_METADATA_FIELDS
    .map((field) => [field, form[field].trim()] as const)
    .filter(([, value]) => value)
    .map(([field, value]) => `${field}: ${value}`);
  if (lines.length === 0) return baseLog || null;
  return [baseLog, ORA2PG_METADATA_BEGIN, ...lines, ORA2PG_METADATA_END].filter(Boolean).join("\n");
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

function emptyJobForm(): JobForm {
  return {
    name: "",
    description: "",
    source_system: "JDE Oracle",
    source_connection_id: "",
    source_type: "oracle",
    migration_tool: "ora2pg",
    source_schema: "PRODDTA",
    source_table: "",
    target_schema: "mdp_staging",
    target_table: "",
    estimated_rows: "",
    estimated_size_gb: "",
    primary_key_columns: "",
    load_mode: "external_bulk",
    initial_load_strategy: "external_defined",
    max_rows_per_run: "",
    time_window_column: "",
    time_window_column_type: "unknown",
    time_window_start: "",
    time_window_end: "",
    incremental_strategy: "none",
    watermark_column: "",
    watermark_column_type: "unknown",
    lookback_window_days: "",
    lookback_window_minutes: "",
    validation_level: "basic",
    status: "active",
    config_json: '{\n  "ora2pg_project": ""\n}',
  };
}

function jobFormFromJob(job: MigrationJob): JobForm {
  return {
    name: job.name,
    description: job.description || "",
    source_system: job.source_system || "",
    source_connection_id: job.source_connection_id || "",
    source_type: job.source_type,
    migration_tool: job.migration_tool,
    source_schema: job.source_schema || "",
    source_table: job.source_table || "",
    target_schema: job.target_schema,
    target_table: job.target_table,
    estimated_rows: job.estimated_rows == null ? "" : String(job.estimated_rows),
    estimated_size_gb: job.estimated_size_gb == null ? "" : String(job.estimated_size_gb),
    primary_key_columns: job.primary_key_columns?.join(", ") || "",
    load_mode: job.load_mode,
    initial_load_strategy: job.initial_load_strategy || "external_defined",
    max_rows_per_run: job.max_rows_per_run == null ? "" : String(job.max_rows_per_run),
    time_window_column: job.time_window_column || "",
    time_window_column_type: job.time_window_column_type || "unknown",
    time_window_start: job.time_window_start || "",
    time_window_end: job.time_window_end || "",
    incremental_strategy: job.incremental_strategy || "none",
    watermark_column: job.watermark_column || "",
    watermark_column_type: job.watermark_column_type || "unknown",
    lookback_window_days: job.lookback_window_days == null ? "" : String(job.lookback_window_days),
    lookback_window_minutes: job.lookback_window_minutes == null ? "" : String(job.lookback_window_minutes),
    validation_level: job.validation_level || "basic",
    status: job.status,
    config_json: prettyJson(job.config),
  };
}

function emptyRunForm(): RunForm {
  return {
    run_type: "external_bulk",
    trigger_type: "external",
    status: "success",
    started_at: "",
    finished_at: "",
    source_row_count: "",
    target_row_count: "",
    rows_loaded: "",
    duration_seconds: "",
    run_scope: "",
    from_watermark: "",
    to_watermark: "",
    source_min_watermark: "",
    source_max_watermark: "",
    target_min_watermark: "",
    target_max_watermark: "",
    validation_status: "not_validated",
    ora2pg_config_file: "",
    ora2pg_command: "",
    ora2pg_log_file: "",
    source_table_size_gb: "",
    target_table_size_gb: "",
    rows_per_second: "",
    log_text: "",
    error_message: "",
  };
}

function emptyTemplateForm(template?: MigrationTemplate | null): TemplateForm {
  return {
    name: template ? `migrate_${template.template_key}` : "",
    source_connection_id: "",
    source_schema: template?.source_schema_suggestion || "",
    target_table: template?.target_table || "",
    estimated_rows: template?.estimated_rows == null ? "" : String(template.estimated_rows),
    estimated_size_gb: template?.estimated_size_gb == null ? "" : String(template.estimated_size_gb),
    config_json: "",
  };
}

function runFormFromRun(run: MigrationRun): RunForm {
  const ora2pgMetadata = parseOra2pgMetadata(run.log_text);
  return {
    run_type: run.run_type,
    trigger_type: run.trigger_type,
    status: run.status,
    started_at: toDateTimeInput(run.started_at),
    finished_at: toDateTimeInput(run.finished_at),
    source_row_count: run.source_row_count == null ? "" : String(run.source_row_count),
    target_row_count: run.target_row_count == null ? "" : String(run.target_row_count),
    rows_loaded: run.rows_loaded == null ? "" : String(run.rows_loaded),
    duration_seconds: run.duration_seconds == null ? "" : String(run.duration_seconds),
    run_scope: run.run_scope || "",
    from_watermark: run.from_watermark || "",
    to_watermark: run.to_watermark || "",
    source_min_watermark: run.source_min_watermark || "",
    source_max_watermark: run.source_max_watermark || "",
    target_min_watermark: run.target_min_watermark || "",
    target_max_watermark: run.target_max_watermark || "",
    validation_status: run.validation_status || "not_validated",
    ora2pg_config_file: ora2pgMetadata.ora2pg_config_file,
    ora2pg_command: ora2pgMetadata.ora2pg_command,
    ora2pg_log_file: ora2pgMetadata.ora2pg_log_file,
    source_table_size_gb: ora2pgMetadata.source_table_size_gb,
    target_table_size_gb: ora2pgMetadata.target_table_size_gb,
    rows_per_second: ora2pgMetadata.rows_per_second,
    log_text: stripOra2pgMetadata(run.log_text),
    error_message: run.error_message || "",
  };
}

function sourceLabel(job: MigrationJob): string {
  if (job.source_schema && job.source_table) return `${job.source_schema}.${job.source_table}`;
  return job.source_table || job.source_schema || "-";
}

function targetLabel(job: MigrationJob): string {
  return `${job.target_schema}.${job.target_table}`;
}

function ActionIcon({
  title,
  onClick,
  children,
  danger,
  disabled,
}: {
  title: string;
  onClick: () => void;
  children: React.ReactNode;
  danger?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-md border text-neutral-600 transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-40",
        danger
          ? "border-danger/20 text-danger hover:bg-danger/10"
          : "border-neutral-200 hover:border-brand/30 hover:bg-brand/10 hover:text-brand",
      )}
    >
      {children}
    </button>
  );
}

function DetailGrid({ items }: { items: Array<[string, unknown]> }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map(([label, value]) => (
        <div key={label} className="min-w-0 rounded-md border border-neutral-100 bg-neutral-50 px-3 py-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500">{label}</div>
          <div className="mt-1 truncate text-sm text-neutral-900" title={cellText(value)}>
            {cellText(value)}
          </div>
        </div>
      ))}
    </div>
  );
}

function Section({
  title,
  children,
  subtitle,
}: {
  title: string;
  children: React.ReactNode;
  subtitle?: string;
}) {
  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-4">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-neutral-900">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-neutral-500">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

function TextArea({
  label,
  value,
  onChange,
  rows = 4,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  disabled?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-neutral-700">{label}</span>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={rows}
        disabled={disabled}
        className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-900 focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30 disabled:cursor-not-allowed disabled:bg-neutral-50"
      />
    </label>
  );
}

export default function MigrationJobsPage() {
  const [jobs, setJobs] = useState<MigrationJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [modalError, setModalError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [jobMode, setJobMode] = useState<JobMode | null>(null);
  const [jobForm, setJobForm] = useState<JobForm>(emptyJobForm);
  const [editingJobId, setEditingJobId] = useState<string | null>(null);

  const [viewJob, setViewJob] = useState<MigrationJob | null>(null);
  const [viewRuns, setViewRuns] = useState<MigrationRun[]>([]);
  const [runsJob, setRunsJob] = useState<MigrationJob | null>(null);
  const [runs, setRuns] = useState<MigrationRun[]>([]);

  const [runMode, setRunMode] = useState<RunMode | null>(null);
  const [runForm, setRunForm] = useState<RunForm>(emptyRunForm);
  const [editingRunId, setEditingRunId] = useState<string | null>(null);
  const [runParentJobId, setRunParentJobId] = useState<string | null>(null);

  const [validation, setValidation] = useState<TargetValidationResult | null>(null);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [templates, setTemplates] = useState<MigrationTemplate[]>([]);
  const [selectedTemplateKey, setSelectedTemplateKey] = useState("");
  const [templateForm, setTemplateForm] = useState<TemplateForm>(emptyTemplateForm());
  const [templateLoading, setTemplateLoading] = useState(false);

  const selectedTemplate = templates.find((template) => template.template_key === selectedTemplateKey) || null;

  const reloadJobs = useCallback(async () => {
    setLoading(true);
    setPageError(null);
    try {
      setJobs(await listMigrationJobs());
    } catch (error) {
      setPageError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reloadJobs();
  }, [reloadJobs]);

  function setFormValue<K extends keyof JobForm>(key: K, value: JobForm[K]) {
    setJobForm((current) => ({ ...current, [key]: value }));
  }

  function setRunValue<K extends keyof RunForm>(key: K, value: RunForm[K]) {
    setRunForm((current) => ({ ...current, [key]: value }));
  }

  function setTemplateValue<K extends keyof TemplateForm>(key: K, value: TemplateForm[K]) {
    setTemplateForm((current) => ({ ...current, [key]: value }));
  }

  // Retained (prompt 33 keeps the create/template modals + APIs) but no longer wired to a header
  // button — the dashboard drives migrations from the reference catalog now.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async function openTemplateCreate() {
    setTemplateOpen(true);
    setTemplateLoading(true);
    setModalError(null);
    try {
      const loaded = await listMigrationTemplates();
      setTemplates(loaded);
      const first = loaded[0] || null;
      setSelectedTemplateKey(first?.template_key || "");
      setTemplateForm(emptyTemplateForm(first));
    } catch (error) {
      setModalError(errorMessage(error));
    } finally {
      setTemplateLoading(false);
    }
  }

  function changeSelectedTemplate(templateKey: string) {
    const template = templates.find((item) => item.template_key === templateKey) || null;
    setSelectedTemplateKey(templateKey);
    setTemplateForm(emptyTemplateForm(template));
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  function openCreateJob() {
    setModalError(null);
    setEditingJobId(null);
    setJobForm(emptyJobForm());
    setJobMode("create");
  }

  async function openViewJob(job: MigrationJob) {
    setBusy(true);
    setModalError(null);
    try {
      const detail = await getMigrationJob(job.id);
      const jobRuns = await listMigrationRuns(job.id);
      setViewJob(detail);
      setViewRuns(jobRuns.slice(0, 3));
    } catch (error) {
      setPageError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function openEditJob(job: MigrationJob) {
    setBusy(true);
    setModalError(null);
    try {
      const detail = await getMigrationJob(job.id);
      setEditingJobId(detail.id);
      setJobForm(jobFormFromJob(detail));
      setJobMode("edit");
    } catch (error) {
      setPageError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  function jobPayload(): Record<string, unknown> {
    let config: Record<string, unknown> | null = null;
    if (jobForm.config_json.trim()) {
      const parsed = JSON.parse(jobForm.config_json);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Config must be a JSON object.");
      }
      config = parsed as Record<string, unknown>;
    }
    return {
      name: jobForm.name.trim(),
      description: jobForm.description.trim() || null,
      source_system: jobForm.source_system.trim() || "JDE Oracle",
      source_connection_id: jobForm.source_connection_id.trim() || null,
      source_type: jobForm.source_type,
      migration_tool: jobForm.migration_tool,
      source_schema: jobForm.source_schema.trim() || null,
      source_table: jobForm.source_table.trim() || null,
      target_schema: jobForm.target_schema.trim() || "mdp_staging",
      target_table: jobForm.target_table.trim(),
      estimated_rows: parseNullableNumber(jobForm.estimated_rows),
      estimated_size_gb: parseNullableNumber(jobForm.estimated_size_gb),
      primary_key_columns: parseStringList(jobForm.primary_key_columns),
      load_mode: jobForm.load_mode,
      initial_load_strategy: jobForm.initial_load_strategy || null,
      max_rows_per_run: parseNullableNumber(jobForm.max_rows_per_run),
      time_window_column: jobForm.time_window_column.trim() || null,
      time_window_column_type: jobForm.time_window_column_type || null,
      time_window_start: jobForm.time_window_start.trim() || null,
      time_window_end: jobForm.time_window_end.trim() || null,
      incremental_strategy: jobForm.incremental_strategy || "none",
      watermark_column: jobForm.watermark_column.trim() || null,
      watermark_column_type: jobForm.watermark_column_type || null,
      lookback_window_days: parseNullableNumber(jobForm.lookback_window_days),
      lookback_window_minutes: parseNullableNumber(jobForm.lookback_window_minutes),
      validation_level: jobForm.validation_level || "basic",
      status: jobForm.status,
      config,
    };
  }

  function templatePayload(): Record<string, unknown> {
    let config: Record<string, unknown> | null = null;
    if (templateForm.config_json.trim()) {
      const parsed = JSON.parse(templateForm.config_json);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Config override must be a JSON object.");
      }
      config = parsed as Record<string, unknown>;
    }
    return {
      name: templateForm.name.trim() || null,
      source_connection_id: templateForm.source_connection_id.trim() || null,
      source_schema: templateForm.source_schema.trim() || null,
      target_table: templateForm.target_table.trim() || null,
      estimated_rows: parseNullableNumber(templateForm.estimated_rows),
      estimated_size_gb: parseNullableNumber(templateForm.estimated_size_gb),
      config,
    };
  }

  async function createFromTemplate() {
    if (!selectedTemplateKey) return;
    setBusy(true);
    setModalError(null);
    try {
      await createMigrationJobFromTemplate(selectedTemplateKey, templatePayload());
      setNotice("Migration job created from template.");
      setTemplateOpen(false);
      await reloadJobs();
    } catch (error) {
      setModalError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function saveJob() {
    setBusy(true);
    setModalError(null);
    try {
      const payload = jobPayload();
      if (jobMode === "edit" && editingJobId) {
        await updateMigrationJob(editingJobId, payload);
        setNotice("Migration job updated.");
      } else {
        await createMigrationJob(payload);
        setNotice("Migration job created.");
      }
      setJobMode(null);
      setEditingJobId(null);
      await reloadJobs();
    } catch (error) {
      setModalError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function deactivateJob(job: MigrationJob) {
    if (!confirm("Deactivate this migration job? Existing run history and validation results will be kept.")) return;
    setBusy(true);
    setPageError(null);
    try {
      await deleteMigrationJob(job.id);
      setNotice("Migration job deactivated.");
      await reloadJobs();
    } catch (error) {
      setPageError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function activateJob(job: MigrationJob) {
    setBusy(true);
    setPageError(null);
    try {
      await updateMigrationJob(job.id, { status: "active" });
      setNotice("Migration job activated.");
      await reloadJobs();
    } catch (error) {
      setPageError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function openRuns(job: MigrationJob) {
    setBusy(true);
    setModalError(null);
    setValidation(null);
    try {
      setRunsJob(job);
      setRunParentJobId(job.id);
      setRuns(await listMigrationRuns(job.id));
    } catch (error) {
      setPageError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function reloadRuns(jobId?: string) {
    const id = jobId || runsJob?.id;
    if (!id) return;
    setRuns(await listMigrationRuns(id));
  }

  function openCreateRun() {
    setModalError(null);
    setEditingRunId(null);
    setRunParentJobId(runsJob?.id || null);
    setRunForm(emptyRunForm());
    setRunMode("create");
  }

  async function openViewRun(run: MigrationRun) {
    setBusy(true);
    setModalError(null);
    try {
      const detail = await getMigrationRun(run.id);
      setEditingRunId(detail.id);
      setRunParentJobId(detail.migration_job_id);
      setRunForm(runFormFromRun(detail));
      setRunMode("view");
    } catch (error) {
      setModalError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function openEditRun(run: MigrationRun) {
    setBusy(true);
    setModalError(null);
    try {
      const detail = await getMigrationRun(run.id);
      setEditingRunId(detail.id);
      setRunParentJobId(detail.migration_job_id);
      setRunForm(runFormFromRun(detail));
      setRunMode("edit");
    } catch (error) {
      setModalError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  function runPayload(): Record<string, unknown> {
    return {
      run_type: runForm.run_type,
      trigger_type: runForm.trigger_type,
      started_at: fromDateTimeInput(runForm.started_at),
      finished_at: fromDateTimeInput(runForm.finished_at),
      status: runForm.status,
      source_row_count: parseNullableNumber(runForm.source_row_count),
      target_row_count: parseNullableNumber(runForm.target_row_count),
      rows_loaded: parseNullableNumber(runForm.rows_loaded),
      duration_seconds: parseNullableNumber(runForm.duration_seconds),
      run_scope: runForm.run_scope.trim() || null,
      from_watermark: runForm.from_watermark.trim() || null,
      to_watermark: runForm.to_watermark.trim() || null,
      source_min_watermark: runForm.source_min_watermark.trim() || null,
      source_max_watermark: runForm.source_max_watermark.trim() || null,
      target_min_watermark: runForm.target_min_watermark.trim() || null,
      target_max_watermark: runForm.target_max_watermark.trim() || null,
      validation_status: runForm.validation_status || "not_validated",
      log_text: buildLogTextWithOra2pgMetadata(runForm),
      error_message: runForm.error_message.trim() || null,
    };
  }

  async function saveRun() {
    if (!runsJob && runMode === "create") return;
    setBusy(true);
    setModalError(null);
    try {
      if (runMode === "edit" && editingRunId) {
        await updateMigrationRun(editingRunId, runPayload());
        setNotice("Migration run updated.");
      } else if (runMode === "create" && runsJob) {
        await createMigrationRun(runsJob.id, runPayload());
        setNotice("Migration run recorded.");
      }
      setRunMode(null);
      setEditingRunId(null);
      if (runParentJobId) {
        const refreshedRuns = await listMigrationRuns(runParentJobId);
        if (runsJob?.id === runParentJobId) setRuns(refreshedRuns);
        if (viewJob?.id === runParentJobId) setViewRuns(refreshedRuns.slice(0, 3));
      } else {
        await reloadRuns();
      }
      await reloadJobs();
    } catch (error) {
      setModalError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function validateRun(run: MigrationRun) {
    setBusy(true);
    setModalError(null);
    try {
      const result = await validateMigrationTarget(run.id);
      setValidation(result);
      setNotice(`Target validation ${result.status}.`);
      const parentJob = jobs.find((job) => job.id === run.migration_job_id) || runsJob || viewJob;
      if (parentJob) setRunsJob(parentJob);
      await reloadRuns(run.migration_job_id);
      await reloadJobs();
    } catch (error) {
      setModalError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function validateLatest(job: MigrationJob) {
    setBusy(true);
    setPageError(null);
    try {
      let jobRuns = await listMigrationRuns(job.id);
      if (jobRuns.length === 0) {
        const created = await createMigrationRun(job.id, {
          run_type: "validation_only",
          trigger_type: "manual",
          status: "success",
        });
        jobRuns = [created];
      }
      const result = await validateMigrationTarget(jobRuns[0].id);
      setValidation(result);
      setRunsJob(job);
      setRuns(await listMigrationRuns(job.id));
      setNotice(`Target validation ${result.status}.`);
      await reloadJobs();
    } catch (error) {
      setPageError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  function renderJobForm(readOnly = false) {
    return (
      <div className="space-y-4">
        <p className="rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
          MDP does not run large JDE full loads inside FastAPI. Use ora2pg or another external bulk loader, then record and validate the result here.
        </p>
        <p className="rounded-md bg-info/10 px-3 py-2 text-sm text-info">
          Initial full-load for large JDE tables should be performed by ora2pg or an external bulk loader. MDP records the run, validates the target staging table, and stores watermark metadata for future incremental updates.
        </p>
        <Section title="Overview">
          <div className="grid gap-3 md:grid-cols-2">
            <Input label="Name" requiredMark value={jobForm.name} onChange={(e) => setFormValue("name", e.target.value)} disabled={readOnly} />
            <Input label="Source System" value={jobForm.source_system} onChange={(e) => setFormValue("source_system", e.target.value)} disabled={readOnly} />
            <Select label="Migration Tool" requiredMark value={jobForm.migration_tool} onChange={(e) => setFormValue("migration_tool", e.target.value)} disabled={readOnly}>
              {MIGRATION_TOOLS.map((item) => <option key={item} value={item}>{item}</option>)}
            </Select>
            <Select label="Load Mode" requiredMark value={jobForm.load_mode} onChange={(e) => setFormValue("load_mode", e.target.value)} disabled={readOnly}>
              {MIGRATION_LOAD_MODES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Select label="Status" value={jobForm.status} onChange={(e) => setFormValue("status", e.target.value)} disabled={readOnly}>
              {JOB_STATUSES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Input label="Source Connection ID" value={jobForm.source_connection_id} onChange={(e) => setFormValue("source_connection_id", e.target.value)} disabled={readOnly} />
          </div>
          <div className="mt-3">
            <TextArea label="Description" value={jobForm.description} onChange={(value) => setFormValue("description", value)} rows={3} disabled={readOnly} />
          </div>
        </Section>
        <Section title="Source and Target">
          <div className="grid gap-3 md:grid-cols-2">
            <Select label="Source Type" requiredMark value={jobForm.source_type} onChange={(e) => setFormValue("source_type", e.target.value)} disabled={readOnly}>
              {MIGRATION_SOURCE_TYPES.map((item) => <option key={item} value={item}>{item}</option>)}
            </Select>
            <Input label="Source Schema" value={jobForm.source_schema} onChange={(e) => setFormValue("source_schema", e.target.value)} disabled={readOnly} />
            <Input label="Source Table" value={jobForm.source_table} onChange={(e) => setFormValue("source_table", e.target.value)} disabled={readOnly} />
            <Input label="Target Schema" value={jobForm.target_schema} onChange={(e) => setFormValue("target_schema", e.target.value)} disabled={readOnly} />
            <Input label="Target Table" requiredMark value={jobForm.target_table} onChange={(e) => setFormValue("target_table", e.target.value)} disabled={readOnly} />
            <Input label="Primary Key Columns" value={jobForm.primary_key_columns} onChange={(e) => setFormValue("primary_key_columns", e.target.value)} placeholder="supplier_code, company_code" disabled={readOnly} />
            <Input label="Estimated Rows" value={jobForm.estimated_rows} onChange={(e) => setFormValue("estimated_rows", e.target.value)} disabled={readOnly} />
            <Input label="Estimated Size GB" value={jobForm.estimated_size_gb} onChange={(e) => setFormValue("estimated_size_gb", e.target.value)} disabled={readOnly} />
          </div>
        </Section>
        <Section
          title="Migration Scope & Incremental Control"
          subtitle="Watermark is the latest successfully migrated position. Future incremental jobs can use it to migrate only new or changed records."
        >
          <div className="grid gap-3 md:grid-cols-2">
            <Select label="Initial Load Strategy" value={jobForm.initial_load_strategy} onChange={(e) => setFormValue("initial_load_strategy", e.target.value)} disabled={readOnly}>
              {MIGRATION_INITIAL_LOAD_STRATEGIES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Input label="Max Rows Per Run" value={jobForm.max_rows_per_run} onChange={(e) => setFormValue("max_rows_per_run", e.target.value)} disabled={readOnly} />
            <Input label="Time Window Column" value={jobForm.time_window_column} onChange={(e) => setFormValue("time_window_column", e.target.value)} placeholder="updated_at or upmj" disabled={readOnly} />
            <Select label="Time Window Column Type" value={jobForm.time_window_column_type} onChange={(e) => setFormValue("time_window_column_type", e.target.value)} disabled={readOnly}>
              {MIGRATION_WATERMARK_TYPES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Input label="Time Window Start" value={jobForm.time_window_start} onChange={(e) => setFormValue("time_window_start", e.target.value)} disabled={readOnly} />
            <Input label="Time Window End" value={jobForm.time_window_end} onChange={(e) => setFormValue("time_window_end", e.target.value)} disabled={readOnly} />
            <Select label="Incremental Strategy" value={jobForm.incremental_strategy} onChange={(e) => setFormValue("incremental_strategy", e.target.value)} disabled={readOnly}>
              {MIGRATION_INCREMENTAL_STRATEGIES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Input label="Watermark Column" value={jobForm.watermark_column} onChange={(e) => setFormValue("watermark_column", e.target.value)} placeholder="updated_at" disabled={readOnly} />
            <Select label="Watermark Column Type" value={jobForm.watermark_column_type} onChange={(e) => setFormValue("watermark_column_type", e.target.value)} disabled={readOnly}>
              {MIGRATION_WATERMARK_TYPES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Input label="Lookback Window Days" value={jobForm.lookback_window_days} onChange={(e) => setFormValue("lookback_window_days", e.target.value)} disabled={readOnly} />
            <Input label="Lookback Window Minutes" value={jobForm.lookback_window_minutes} onChange={(e) => setFormValue("lookback_window_minutes", e.target.value)} disabled={readOnly} />
            <Select label="Validation Level" value={jobForm.validation_level} onChange={(e) => setFormValue("validation_level", e.target.value)} disabled={readOnly}>
              {MIGRATION_VALIDATION_LEVELS.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
          </div>
        </Section>
        <Section title="Config" subtitle="Optional JSON object for external tool metadata, ora2pg project names, or command notes.">
          <TextArea label="Config JSON" value={jobForm.config_json} onChange={(value) => setFormValue("config_json", value)} rows={8} disabled={readOnly} />
        </Section>
      </div>
    );
  }

  function renderTemplateCreate() {
    return (
      <div className="space-y-4">
        <p className="rounded-md bg-info/10 px-3 py-2 text-sm text-info">
          Templates create migration job records for external ora2pg or curated-view tracking. They do not execute migration workloads inside MDP.
        </p>
        {templateLoading ? (
          <p className="text-sm text-neutral-500">Loading templates...</p>
        ) : (
          <>
            <Section title="JDE Procurement Templates">
              <div className="grid gap-3 md:grid-cols-[minmax(260px,360px)_1fr]">
                <Select
                  label="Template"
                  requiredMark
                  value={selectedTemplateKey}
                  onChange={(event) => changeSelectedTemplate(event.target.value)}
                >
                  {templates.map((template) => (
                    <option key={template.template_key} value={template.template_key}>
                      {template.display_name}
                    </option>
                  ))}
                </Select>
                {selectedTemplate && (
                  <div className="rounded-md border border-neutral-100 bg-neutral-50 px-3 py-2 text-sm text-neutral-700">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-neutral-900">{selectedTemplate.display_name}</span>
                      <Badge tone={selectedTemplate.template_type === "curated_view" ? "neutral" : "info"}>
                        {selectedTemplate.template_type}
                      </Badge>
                    </div>
                    <p className="mt-1 text-xs text-neutral-600">{selectedTemplate.description}</p>
                  </div>
                )}
              </div>
            </Section>
            {selectedTemplate && (
              <>
                <Section title="Template Defaults">
                  <DetailGrid
                    items={[
                      ["Source System", selectedTemplate.source_system],
                      ["Source Type", selectedTemplate.source_type],
                      ["Migration Tool", selectedTemplate.migration_tool],
                      ["Source Schema", selectedTemplate.source_schema_suggestion],
                      ["Source Table", selectedTemplate.source_table],
                      ["Related Tables", selectedTemplate.related_source_tables],
                      ["Target", `${selectedTemplate.target_schema}.${selectedTemplate.target_table}`],
                      ["Primary Key Columns", selectedTemplate.primary_key_columns],
                      ["Load Mode", titleize(selectedTemplate.load_mode)],
                      ["Watermark", selectedTemplate.watermark_column],
                      ["Watermark Type", titleize(selectedTemplate.watermark_column_type)],
                      ["Validation Level", titleize(selectedTemplate.validation_level)],
                    ]}
                  />
                </Section>
                <Section title="Overrides" subtitle="Review these defaults with the customer DBA/JDE team before using them for real environments.">
                  <div className="grid gap-3 md:grid-cols-2">
                    <Input label="Job Name" value={templateForm.name} onChange={(e) => setTemplateValue("name", e.target.value)} />
                    <Input label="Source Connection ID" value={templateForm.source_connection_id} onChange={(e) => setTemplateValue("source_connection_id", e.target.value)} />
                    <Input label="Source Schema" value={templateForm.source_schema} onChange={(e) => setTemplateValue("source_schema", e.target.value)} placeholder="PRODDTA" />
                    <Input label="Target Table" value={templateForm.target_table} onChange={(e) => setTemplateValue("target_table", e.target.value)} />
                    <Input label="Estimated Rows" value={templateForm.estimated_rows} onChange={(e) => setTemplateValue("estimated_rows", e.target.value)} />
                    <Input label="Estimated Size GB" value={templateForm.estimated_size_gb} onChange={(e) => setTemplateValue("estimated_size_gb", e.target.value)} />
                  </div>
                  <div className="mt-3">
                    <TextArea
                      label="Config Override JSON"
                      value={templateForm.config_json}
                      onChange={(value) => setTemplateValue("config_json", value)}
                      rows={5}
                    />
                  </div>
                </Section>
              </>
            )}
          </>
        )}
      </div>
    );
  }

  function renderRunForm(readOnly = false) {
    return (
      <div className="space-y-4">
        <Section title="Run Details">
          <div className="grid gap-3 md:grid-cols-2">
            <Select label="Run Type" value={runForm.run_type} onChange={(e) => setRunValue("run_type", e.target.value)} disabled={readOnly}>
              {RUN_TYPES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Select label="Trigger Type" value={runForm.trigger_type} onChange={(e) => setRunValue("trigger_type", e.target.value)} disabled={readOnly}>
              {TRIGGER_TYPES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Select label="Status" value={runForm.status} onChange={(e) => setRunValue("status", e.target.value)} disabled={readOnly}>
              {MIGRATION_RUN_STATUSES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Input label="Started At" type="datetime-local" value={runForm.started_at} onChange={(e) => setRunValue("started_at", e.target.value)} disabled={readOnly} />
            <Input label="Finished At" type="datetime-local" value={runForm.finished_at} onChange={(e) => setRunValue("finished_at", e.target.value)} disabled={readOnly} />
            <Input label="Duration Seconds" value={runForm.duration_seconds} onChange={(e) => setRunValue("duration_seconds", e.target.value)} disabled={readOnly} />
            <Input label="Source Row Count" value={runForm.source_row_count} onChange={(e) => setRunValue("source_row_count", e.target.value)} disabled={readOnly} />
            <Input label="Target Row Count" value={runForm.target_row_count} onChange={(e) => setRunValue("target_row_count", e.target.value)} disabled={readOnly} />
            <Input label="Rows Loaded" value={runForm.rows_loaded} onChange={(e) => setRunValue("rows_loaded", e.target.value)} disabled={readOnly} />
          </div>
        </Section>
        <Section
          title="ora2pg Pilot Metadata"
          subtitle="Optional fields copied from the real ora2pg run. Stored in the run log so no schema migration is needed."
        >
          <div className="grid gap-3 md:grid-cols-2">
            <Input label="ora2pg Config File" value={runForm.ora2pg_config_file} onChange={(e) => setRunValue("ora2pg_config_file", e.target.value)} placeholder="/opt/ora2pg/jde_supplier.conf" disabled={readOnly} />
            <Input label="ora2pg Log File" value={runForm.ora2pg_log_file} onChange={(e) => setRunValue("ora2pg_log_file", e.target.value)} placeholder="/var/log/ora2pg/jde_supplier.log" disabled={readOnly} />
            <Input label="Source Table Size GB" value={runForm.source_table_size_gb} onChange={(e) => setRunValue("source_table_size_gb", e.target.value)} placeholder="30" disabled={readOnly} />
            <Input label="Target Table Size GB" value={runForm.target_table_size_gb} onChange={(e) => setRunValue("target_table_size_gb", e.target.value)} placeholder="30" disabled={readOnly} />
            <Input label="Rows Per Second" value={runForm.rows_per_second} onChange={(e) => setRunValue("rows_per_second", e.target.value)} placeholder="2500" disabled={readOnly} />
            <Input label="ora2pg Command" value={runForm.ora2pg_command} onChange={(e) => setRunValue("ora2pg_command", e.target.value)} placeholder="ora2pg -c /opt/ora2pg/jde_supplier.conf" disabled={readOnly} />
          </div>
        </Section>
        <Section title="Scope & Watermark">
          <div className="grid gap-3 md:grid-cols-2">
            <Input label="Run Scope" value={runForm.run_scope} onChange={(e) => setRunValue("run_scope", e.target.value)} placeholder="watermark > 2026-05-31" disabled={readOnly} />
            <Select label="Validation Status" value={runForm.validation_status} onChange={(e) => setRunValue("validation_status", e.target.value)} disabled={readOnly}>
              {MIGRATION_RUN_VALIDATION_STATUSES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Input label="From Watermark" value={runForm.from_watermark} onChange={(e) => setRunValue("from_watermark", e.target.value)} disabled={readOnly} />
            <Input label="To Watermark" value={runForm.to_watermark} onChange={(e) => setRunValue("to_watermark", e.target.value)} disabled={readOnly} />
            <Input label="Source Min Watermark" value={runForm.source_min_watermark} onChange={(e) => setRunValue("source_min_watermark", e.target.value)} disabled={readOnly} />
            <Input label="Source Max Watermark" value={runForm.source_max_watermark} onChange={(e) => setRunValue("source_max_watermark", e.target.value)} disabled={readOnly} />
            <Input label="Target Min Watermark" value={runForm.target_min_watermark} onChange={(e) => setRunValue("target_min_watermark", e.target.value)} disabled={readOnly} />
            <Input label="Target Max Watermark" value={runForm.target_max_watermark} onChange={(e) => setRunValue("target_max_watermark", e.target.value)} disabled={readOnly} />
          </div>
        </Section>
        <Section title="Logs">
          <div className="grid gap-3 md:grid-cols-2">
            <TextArea label="Log Text" value={runForm.log_text} onChange={(value) => setRunValue("log_text", value)} rows={7} disabled={readOnly} />
            <TextArea label="Error Message" value={runForm.error_message} onChange={(value) => setRunValue("error_message", value)} rows={7} disabled={readOnly} />
          </div>
        </Section>
      </div>
    );
  }

  return (
    <>
      {/* "Create from Template" + "New Migration Job" buttons removed (prompt 33): the dashboard
          drives migrations from the reference catalog; the create/template modals + APIs are kept. */}
      <PageHeader
        title="Migration Jobs"
        subtitle={`Public API: ${apiPath("/migration-jobs")} - tracks external ora2pg/bulk loads and validates PostgreSQL staging targets.`}
      />
      <Ora2pgMigrationDashboard />
      <Card className="mb-4">
        <CardBody>
          <p className="text-sm text-neutral-600">
            MDP does not run large JDE full loads inside FastAPI. Use ora2pg or another external bulk loader for large tables, then record the run and validate the target table here.
          </p>
        </CardBody>
      </Card>
      {pageError && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{pageError}</p>}
      {notice && <p className="mb-4 rounded-md bg-success/10 px-3 py-2 text-sm text-success">{notice}</p>}
      <Card>
        <CardHeader title="Migration Jobs" subtitle={`${jobs.length} total`} />
        <CardBody>
          {loading ? (
            <p className="text-sm text-neutral-400">Loading...</p>
          ) : (
            <Table className="table-fixed text-[13px]">
              <colgroup>
                <col className="w-[180px]" />
                <col className="w-[210px]" />
                <col className="w-[140px]" />
                <col className="w-[180px]" />
                <col className="w-[180px]" />
                <col className="w-[95px]" />
                <col className="w-[120px]" />
                <col className="w-[95px]" />
                <col className="w-[110px]" />
                <col className="w-[110px]" />
              </colgroup>
              <THead>
                <TR>
                  <TH className="text-center">Actions</TH>
                  <TH>Name</TH>
                  <TH>Source System</TH>
                  <TH>Source Table</TH>
                  <TH>Target Table</TH>
                  <TH>Tool</TH>
                  <TH>Load Mode</TH>
                  <TH>Status</TH>
                  <TH>Latest Run</TH>
                  <TH>Target Rows</TH>
                </TR>
              </THead>
              <TBody>
                {jobs.map((job) => (
                  <TR key={job.id}>
                    <TD>
                      <div className="flex items-center justify-center gap-1">
                        <ActionIcon title={`View ${job.name}`} onClick={() => openViewJob(job)} disabled={busy}>
                          <Eye size={15} />
                        </ActionIcon>
                        <ActionIcon title={`Edit ${job.name}`} onClick={() => openEditJob(job)} disabled={busy}>
                          <Pencil size={15} />
                        </ActionIcon>
                        <ActionIcon title={`Runs for ${job.name}`} onClick={() => openRuns(job)} disabled={busy}>
                          <History size={15} />
                        </ActionIcon>
                        <ActionIcon title={`Validate target for ${job.name}`} onClick={() => validateLatest(job)} disabled={busy}>
                          <ShieldCheck size={15} />
                        </ActionIcon>
                        {job.status === "inactive" ? (
                          <ActionIcon title={`Activate ${job.name}`} onClick={() => activateJob(job)} disabled={busy}>
                            <RotateCcw size={15} />
                          </ActionIcon>
                        ) : (
                          <ActionIcon title={`Deactivate ${job.name}`} onClick={() => deactivateJob(job)} disabled={busy} danger>
                            <Power size={15} />
                          </ActionIcon>
                        )}
                      </div>
                    </TD>
                    <TD className="truncate font-medium" title={job.name}>{job.name}</TD>
                    <TD className="truncate" title={job.source_system || job.source_type}>{job.source_system || job.source_type}</TD>
                    <TD className="truncate font-mono text-xs" title={sourceLabel(job)}>{sourceLabel(job)}</TD>
                    <TD className="truncate font-mono text-xs" title={targetLabel(job)}>{targetLabel(job)}</TD>
                    <TD><Badge tone={badgeTone(job.migration_tool)}>{job.migration_tool}</Badge></TD>
                    <TD>{titleize(job.load_mode)}</TD>
                    <TD><Badge tone={badgeTone(job.status)}>{job.status}</Badge></TD>
                    <TD><Badge tone={badgeTone(job.latest_run_status)}>{job.latest_run_status || "none"}</Badge></TD>
                    <TD>{job.latest_target_row_count ?? "-"}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>

      <Modal
        open={templateOpen}
        onClose={() => setTemplateOpen(false)}
        title="Create Migration Job from Template"
        className="data-model-dialog overflow-hidden"
        footer={
          <>
            <Button variant="ghost" onClick={() => setTemplateOpen(false)}>Cancel</Button>
            <Button onClick={createFromTemplate} disabled={busy || templateLoading || !selectedTemplateKey}>
              {busy ? "Creating..." : "Create Job"}
            </Button>
          </>
        }
      >
        {modalError && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{modalError}</p>}
        {renderTemplateCreate()}
      </Modal>

      <Modal
        open={jobMode !== null}
        onClose={() => setJobMode(null)}
        title={jobMode === "edit" ? "Edit Migration Job" : "New Migration Job"}
        className="data-model-dialog overflow-hidden"
        footer={
          <>
            <Button variant="ghost" onClick={() => setJobMode(null)}>Cancel</Button>
            <Button onClick={saveJob} disabled={busy}>{busy ? "Saving..." : jobMode === "edit" ? "Save Changes" : "Create Job"}</Button>
          </>
        }
      >
        {modalError && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{modalError}</p>}
        {renderJobForm(false)}
      </Modal>

      <Modal
        open={viewJob !== null}
        onClose={() => setViewJob(null)}
        title="View Migration Job"
        className="data-model-dialog overflow-hidden"
        footer={
          <>
            <Button variant="ghost" onClick={() => setViewJob(null)}>Close</Button>
            {viewJob && <Button onClick={() => { const job = viewJob; setViewJob(null); openEditJob(job); }}>Edit Job</Button>}
          </>
        }
      >
        {viewJob && (
          <div className="space-y-4">
            <Section title="Overview">
              <DetailGrid items={[
                ["Name", viewJob.name],
                ["Description", viewJob.description],
                ["Status", viewJob.status],
                ["Source System", viewJob.source_system],
                ["Migration Tool", viewJob.migration_tool],
                ["Load Mode", titleize(viewJob.load_mode)],
              ]} />
            </Section>
            <Section title="Source">
              <DetailGrid items={[
                ["Source Type", viewJob.source_type],
                ["Source Connection", viewJob.source_connection_id],
                ["Source Schema", viewJob.source_schema],
                ["Source Table", viewJob.source_table],
              ]} />
            </Section>
            <Section title="Target">
              <DetailGrid items={[
                ["Target Schema", viewJob.target_schema],
                ["Target Table", viewJob.target_table],
                ["Primary Key Columns", viewJob.primary_key_columns],
                ["Estimated Rows", viewJob.estimated_rows],
                ["Estimated Size GB", viewJob.estimated_size_gb],
              ]} />
            </Section>
            <Section title="Migration Scope & Incremental Control">
              <DetailGrid items={[
                ["Initial Load Strategy", titleize(viewJob.initial_load_strategy)],
                ["Max Rows Per Run", viewJob.max_rows_per_run],
                ["Time Window Column", viewJob.time_window_column],
                ["Time Window Type", titleize(viewJob.time_window_column_type)],
                ["Time Window Start", viewJob.time_window_start],
                ["Time Window End", viewJob.time_window_end],
                ["Incremental Strategy", titleize(viewJob.incremental_strategy)],
                ["Watermark Column", viewJob.watermark_column],
                ["Watermark Type", titleize(viewJob.watermark_column_type)],
                ["Lookback Days", viewJob.lookback_window_days],
                ["Lookback Minutes", viewJob.lookback_window_minutes],
              ]} />
            </Section>
            <Section title="Watermark & Latest Run">
              <DetailGrid items={[
                ["Last Run At", formatDate(viewJob.last_run_at)],
                ["Last Successful Run At", formatDate(viewJob.last_successful_run_at)],
                ["Last Successful Watermark", viewJob.last_successful_watermark],
                ["Validation Level", titleize(viewJob.validation_level)],
                ["Incremental Strategy", titleize(viewJob.incremental_strategy)],
              ]} />
            </Section>
            <Section title="Config">
              <pre className="max-h-72 overflow-auto rounded-md bg-neutral-950 p-3 text-xs text-neutral-50">
                {prettyJson(viewJob.config) || "-"}
              </pre>
            </Section>
            <Section title="Latest Runs" subtitle="Latest 3 run records">
              {viewRuns.length === 0 ? (
                <p className="text-sm text-neutral-500">No runs recorded yet.</p>
              ) : (
                <RunTable runs={viewRuns} onView={openViewRun} onEdit={openEditRun} onValidate={validateRun} busy={busy} />
              )}
            </Section>
          </div>
        )}
      </Modal>

      <Modal
        open={runsJob !== null}
        onClose={() => setRunsJob(null)}
        title={runsJob ? `Run History - ${runsJob.name}` : "Run History"}
        className="data-model-dialog overflow-hidden"
      >
        {modalError && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{modalError}</p>}
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-neutral-600">
              Record ora2pg or external-loader output here. MDP keeps the history and validates the PostgreSQL target.
            </p>
            <Button size="sm" onClick={openCreateRun}>
              <PlayCircle size={15} />
              New Run Record
            </Button>
          </div>
          {validation && <ValidationPanel validation={validation} />}
          {runs.length === 0 ? (
            <p className="rounded-md border border-neutral-200 bg-neutral-50 px-3 py-4 text-sm text-neutral-500">
              No migration runs have been recorded.
            </p>
          ) : (
            <RunTable runs={runs} onView={openViewRun} onEdit={openEditRun} onValidate={validateRun} busy={busy} />
          )}
        </div>
      </Modal>

      <Modal
        open={runMode !== null}
        onClose={() => setRunMode(null)}
        title={runMode === "view" ? "View Migration Run" : runMode === "edit" ? "Edit Migration Run" : "New Migration Run"}
        className="data-model-dialog overflow-hidden"
        footer={
          runMode === "view" ? (
            <>
              <Button variant="ghost" onClick={() => setRunMode(null)}>Close</Button>
              {editingRunId && <Button onClick={() => setRunMode("edit")}>Edit Run</Button>}
            </>
          ) : (
            <>
              <Button variant="ghost" onClick={() => setRunMode(null)}>Cancel</Button>
              <Button onClick={saveRun} disabled={busy}>{busy ? "Saving..." : runMode === "edit" ? "Save Changes" : "Create Run"}</Button>
            </>
          )
        }
      >
        {modalError && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{modalError}</p>}
        {renderRunForm(runMode === "view")}
      </Modal>
    </>
  );
}

function RunTable({
  runs,
  onView,
  onEdit,
  onValidate,
  busy,
}: {
  runs: MigrationRun[];
  onView: (run: MigrationRun) => void;
  onEdit: (run: MigrationRun) => void;
  onValidate: (run: MigrationRun) => void;
  busy: boolean;
}) {
  return (
    <Table className="table-fixed text-xs">
      <colgroup>
        <col className="w-[120px]" />
        <col className="w-[100px]" />
        <col className="w-[110px]" />
        <col className="w-[120px]" />
        <col className="w-[120px]" />
        <col className="w-[145px]" />
        <col className="w-[145px]" />
        <col className="w-[180px]" />
        <col className="w-[140px]" />
        <col className="w-[120px]" />
        <col className="w-[120px]" />
        <col className="w-[115px]" />
        <col className="w-[100px]" />
      </colgroup>
      <THead>
        <TR>
          <TH className="text-center">Actions</TH>
          <TH>Status</TH>
          <TH>Validation</TH>
          <TH>Run Type</TH>
          <TH>Trigger</TH>
          <TH>Started At</TH>
          <TH>Finished At</TH>
          <TH>Run Scope</TH>
          <TH>To Watermark</TH>
          <TH>Source Rows</TH>
          <TH>Target Rows</TH>
          <TH>Rows Loaded</TH>
          <TH>Duration</TH>
        </TR>
      </THead>
      <TBody>
        {runs.map((run) => (
          <TR key={run.id}>
            <TD>
              <div className="flex items-center justify-center gap-1">
                <ActionIcon title="View run" onClick={() => onView(run)} disabled={busy}>
                  <Eye size={14} />
                </ActionIcon>
                <ActionIcon title="Edit run" onClick={() => onEdit(run)} disabled={busy}>
                  <SquarePen size={14} />
                </ActionIcon>
                <ActionIcon title="Validate target" onClick={() => onValidate(run)} disabled={busy}>
                  <ShieldCheck size={14} />
                </ActionIcon>
              </div>
            </TD>
            <TD><Badge tone={badgeTone(run.status)}>{run.status}</Badge></TD>
            <TD><Badge tone={badgeTone(run.validation_status)}>{run.validation_status || "not_validated"}</Badge></TD>
            <TD>{titleize(run.run_type)}</TD>
            <TD>{titleize(run.trigger_type)}</TD>
            <TD className="truncate" title={formatDate(run.started_at)}>{formatDate(run.started_at)}</TD>
            <TD className="truncate" title={formatDate(run.finished_at)}>{formatDate(run.finished_at)}</TD>
            <TD className="truncate" title={run.run_scope || "-"}>{run.run_scope || "-"}</TD>
            <TD className="truncate" title={run.to_watermark || "-"}>{run.to_watermark || "-"}</TD>
            <TD>{run.source_row_count ?? "-"}</TD>
            <TD>{run.target_row_count ?? "-"}</TD>
            <TD>{run.rows_loaded ?? "-"}</TD>
            <TD>{run.duration_seconds == null ? "-" : `${run.duration_seconds}s`}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function ValidationPanel({ validation }: { validation: TargetValidationResult }) {
  const checks = Object.fromEntries(validation.validations.map((item) => [item.check_name, item]));
  const pkChecks = validation.validations.filter(
    (item) => item.check_name.startsWith("primary_key_column:")
      || item.check_name.startsWith("primary_key_null_count:")
      || item.check_name === "primary_key_duplicate_count",
  );
  const watermarkChecks = validation.validations.filter((item) => item.check_name.includes("watermark"));
  return (
    <Section
      title="Validation Report"
      subtitle={`${validation.target_schema}.${validation.target_table} - ${validation.target_row_count ?? "-"} rows`}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-neutral-600">Overall validation</span>
        <Badge tone={badgeTone(validation.validation_status)}>{validation.validation_status}</Badge>
        <span className="text-neutral-400">API result</span>
        <Badge tone={badgeTone(validation.status)}>{validation.status}</Badge>
      </div>
      <div className="mb-3 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ReportMetric
          label="Target Table"
          value={checks.target_table_exists?.target_value || `${validation.target_schema}.${validation.target_table}`}
          status={checks.target_table_exists?.status}
        />
        <ReportMetric label="Source Rows" value={validation.source_row_count ?? "-"} status={validation.source_row_count == null ? "warning" : "pass"} />
        <ReportMetric label="Target Rows" value={validation.target_row_count ?? "-"} status={checks.target_row_count?.status} />
        <ReportMetric
          label="Source vs Target"
          value={validation.row_count_match == null ? "Not provided" : validation.row_count_match ? "Match" : "Mismatch"}
          status={validation.row_count_match == null ? "warning" : validation.row_count_match ? "pass" : "fail"}
        />
      </div>
      <div className="mb-3 grid gap-3 md:grid-cols-2">
        <div className="rounded-md border border-neutral-100 bg-neutral-50 p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">Primary Key Integrity</div>
          {pkChecks.length === 0 ? (
            <p className="text-xs text-neutral-500">No primary key columns configured for this migration job.</p>
          ) : (
            <div className="space-y-1">
              {pkChecks.map((check) => (
                <div key={check.id} className="flex items-center justify-between gap-2 text-xs">
                  <span className="truncate font-mono" title={check.check_name}>{check.check_name}</span>
                  <Badge tone={badgeTone(check.status)}>{check.target_value ?? check.status}</Badge>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="rounded-md border border-neutral-100 bg-neutral-50 p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">Watermark Range</div>
          {watermarkChecks.length === 0 ? (
            <p className="text-xs text-neutral-500">No watermark column configured for this migration job.</p>
          ) : (
            <div className="space-y-1">
              {watermarkChecks.map((check) => (
                <div key={check.id} className="flex items-center justify-between gap-2 text-xs">
                  <span className="truncate font-mono" title={check.check_name}>{check.check_name}</span>
                  <Badge tone={badgeTone(check.status)}>{check.target_value ?? check.status}</Badge>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <p className="mb-3 rounded-md bg-neutral-50 px-3 py-2 text-xs text-neutral-600">
        This report is target-side and presentation-ready for pilot/UAT. When source row count is recorded from ora2pg logs, MDP compares it with PostgreSQL target row count. Checksums and source-side reconciliation remain future advanced controls.
      </p>
      <Table className="table-fixed text-xs">
        <colgroup>
          <col className="w-[230px]" />
          <col className="w-[90px]" />
          <col className="w-[130px]" />
          <col className="w-[130px]" />
          <col className="w-[300px]" />
        </colgroup>
        <THead>
          <TR>
            <TH>Check</TH>
            <TH>Status</TH>
            <TH>Source Value</TH>
            <TH>Target Value</TH>
            <TH>Message</TH>
          </TR>
        </THead>
        <TBody>
          {validation.validations.map((item) => (
            <TR key={item.id}>
              <TD className="truncate font-mono" title={item.check_name}>{item.check_name}</TD>
              <TD><Badge tone={badgeTone(item.status)}>{item.status}</Badge></TD>
              <TD className="truncate" title={item.source_value || "-"}>{item.source_value || "-"}</TD>
              <TD className="truncate" title={item.target_value || "-"}>{item.target_value || "-"}</TD>
              <TD className="truncate" title={item.message || "-"}>{item.message || "-"}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </Section>
  );
}

function ReportMetric({
  label,
  value,
  status,
}: {
  label: string;
  value: unknown;
  status?: string | null;
}) {
  return (
    <div className="rounded-md border border-neutral-100 bg-neutral-50 px-3 py-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500">{label}</span>
        {status && <Badge tone={badgeTone(status)}>{status}</Badge>}
      </div>
      <div className="truncate text-sm font-medium text-neutral-900" title={cellText(value)}>
        {cellText(value)}
      </div>
    </div>
  );
}
