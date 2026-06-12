"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ClipboardList, Eye, Pencil, Power, RotateCcw, TableProperties, Trash2 } from "lucide-react";
import { useAuth } from "@/components/auth/AuthProvider";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { RequiredMark } from "@/components/ui/RequiredMark";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import {
  ApiError,
  apiPath,
  ATTR_TYPES,
  createDataModelFromTemplate,
  createDataModel,
  deleteDataModel,
  purgeDataModel,
  getDataModel,
  listDataModelTemplates,
  listColumns,
  listDataModels,
  listSchemas,
  listTables,
  normalizePgType,
  outbound,
  parseTypeBSql,
  generateTypeBSql,
  previewSavedTypeBModel,
  previewTypeBMapping,
  updateDataModel,
  validateTypeBMapping,
  type TypeBSqlPlan,
  type AttrType,
  type DataModel,
  type DataModelAttribute,
  type TypeBJoin,
  type DataModelCreate,
  type DataModelTemplate,
  type DbColumn,
  type DbTable,
  type ModelPreview,
  type TypeBValidationResult,
  type ValidationMessage,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const SYSTEM_COLS = new Set(["id", "raw_payload", "created_at", "updated_at"]);
const attrName = (col: string) => (SYSTEM_COLS.has(col) ? `source_${col}` : snake(col));

const DOMAINS = [
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
];
const BUSINESS_PROCESSES = [
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
];
const SOURCE_LAYERS = [
  "source",
  "staging",
  "canonical",
  "curated_view",
  "analytical",
  "external_api",
  "generated_table",
];
const CANONICAL_STATUSES = ["source_aligned", "canonical", "curated", "experimental", "deprecated"];
const SITE_SCOPES = ["enterprise", "site", "area", "line", "work_center", "asset", "not_applicable"];
const SENSITIVITY_LEVELS = ["public", "internal", "confidential", "restricted"];
const SOURCE_SYSTEMS = ["JDE ERP", "External API", "Manual / Mock Data", "SQL Server", "PostgreSQL", "Other"];
const OWNER_DEPARTMENTS = ["Procurement", "Finance", "Operations", "Quality", "Maintenance", "IT/OT", "Other"];

type Mode = "create" | "view" | "edit" | "preview";
type FormState = {
  name: string;
  display_name: string;
  type: "A" | "B";
  category: string;
  namespace: string;
  domain: string;
  entity_type: string;
  business_process: string;
  source_layer: string;
  canonical_status: string;
  site_scope: string;
  description: string;
  business_definition: string;
  owner_department: string;
  source_system: string;
  primary_key: string;
  refresh_policy: string;
  sensitivity_level: string;
  ai_enabled: boolean;
  status: string;
  attributes: DataModelAttribute[];
  relationships: TypeBJoin[];
  // Type B "latest version only" dedup (prompt 50). recency_column matters only when latest_only.
  latest_only: boolean;
  recency_column: string;
};

type TemplateForm = {
  name: string;
  display_name: string;
  source_schema: string;
  source_table: string;
  status: string;
  config_json: string;
};

function snake(value: string): string {
  return value
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[^A-Za-z0-9]+/g, "_")
    // strip only LEADING underscores — keeping a trailing "_" lets the user type names like
    // `invoice_no` live (otherwise the "_" is eaten the instant it's typed, giving `invoiceno`).
    .replace(/^_+/g, "")
    .toLowerCase();
}

function titleize(value?: string | null): string {
  if (!value) return "-";
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

function emptyToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function initialForm(): FormState {
  return {
    name: "",
    display_name: "",
    type: "B",
    category: "",
    namespace: "",
    domain: "procurement",
    entity_type: "",
    business_process: "procure_to_pay",
    source_layer: "",
    canonical_status: "experimental",
    site_scope: "enterprise",
    description: "",
    business_definition: "",
    owner_department: "Procurement",
    source_system: "JDE ERP",
    primary_key: "",
    refresh_policy: "",
    sensitivity_level: "internal",
    ai_enabled: true,
    status: "active",
    // M (prompt 46): Type A & Type B both start with an EMPTY placeholder attribute (no seeded "code").
    attributes: [emptyAttribute(true)],
    relationships: [],
    latest_only: false,
    recency_column: "updated_at",
  };
}

// K (prompt 45) / M (prompt 46): a default or manually-added attribute row starts EMPTY (placeholder),
// not a seeded "code"/"Code" value - for both Type A and Type B.
function emptyAttribute(isPrimary = false): DataModelAttribute {
  return { name: "", display_name: "", data_type: "text", required: false, is_primary_key: isPrimary };
}

function emptyTemplateForm(template?: DataModelTemplate | null): TemplateForm {
  return {
    name: template?.model_name || "",
    display_name: template?.model_display_name || "",
    source_schema: template?.source_schema || "mdp_staging",
    source_table: template?.source_table || "",
    status: "active",
    config_json: "",
  };
}

function formFromModel(model: DataModel): FormState {
  return {
    name: model.name,
    display_name: model.display_name || model.name,
    type: model.type,
    category: model.category || "",
    namespace: model.namespace || "",
    domain: model.domain || "",
    entity_type: model.entity_type || "",
    business_process: model.business_process || "",
    source_layer: model.source_layer || "",
    canonical_status: model.canonical_status || "",
    site_scope: model.site_scope || "",
    description: model.description || "",
    business_definition: model.business_definition || "",
    owner_department: model.owner_department || "",
    source_system: model.source_system || "",
    primary_key: model.primary_key || "",
    refresh_policy: model.refresh_policy || "",
    sensitivity_level: model.sensitivity_level || "internal",
    ai_enabled: model.ai_enabled ?? true,
    status: model.status || "active",
    // Reconcile is_primary_key against primary_key so the FLAG is the single authoritative PK signal
    // (applyAttributePatch + the radio rely on it). Falls back to the stored flag if no primary_key.
    attributes: (model.attributes || []).map((attribute) => ({
      ...attribute,
      is_primary_key: model.primary_key ? attribute.name === model.primary_key : !!attribute.is_primary_key,
    })),
    // The relationships column is SHARED: drop the non-join "latest_config" entry (prompt 50) so it
    // never renders as a phantom join row - it is restored via latest_only/recency_column instead.
    relationships: (model.relationships || [])
      .filter((join) => join && (join.left != null || join.right != null))
      .map((join) => ({ ...join })),
    latest_only: !!model.latest_only,
    recency_column: model.recency_column || "updated_at",
  };
}

function modelSource(model: DataModel): string {
  if (model.type === "A") return model.generated_table ? `Generated: ${model.generated_table}` : "Generated table";
  const schema =
    model.source_schema ||
    model.attributes?.find((attribute) => attribute.source_schema)?.source_schema ||
    "";
  const table =
    model.source_table ||
    model.attributes?.find((attribute) => attribute.source_table)?.source_table ||
    "";
  return schema && table ? `Linked: ${schema}.${table}` : "Linked source";
}

function typeBSource(model: DataModel | FormState): { source_schema: string; source_table: string } {
  const attrs = model.attributes || [];
  // The base table is the PRIMARY-KEY attribute's table (mirrors the backend); fall back to the
  // first attribute carrying a source only when no PK is set yet.
  const pkName = model.primary_key || attrs.find((attribute) => attribute.is_primary_key)?.name;
  const pkAttr = pkName ? attrs.find((attribute) => attribute.name === pkName) : undefined;
  const base = (pkAttr?.source_table ? pkAttr : attrs.find((attribute) => attribute.source_table)) || undefined;
  return {
    source_schema: base?.source_schema || attrs.find((attribute) => attribute.source_schema)?.source_schema || "",
    source_table: base?.source_table || attrs.find((attribute) => attribute.source_table)?.source_table || "",
  };
}

// H (prompt 44): the ticked "Source tables" set, derived from a loaded model on edit - every distinct
// (schema, table) used by an attribute or a join's right side, plus the base table.
function selectedTablesFromModel(model: DataModel): { schema: string; table: string }[] {
  const out = new Map<string, { schema: string; table: string }>();
  const add = (schema?: string | null, table?: string | null) => {
    if (schema && table) out.set(`${schema}.${table}`, { schema, table });
  };
  const base = typeBSource(model);
  add(base.source_schema, base.source_table);
  for (const attribute of model.attributes || []) add(attribute.source_schema, attribute.source_table);
  for (const join of model.relationships || []) add(join.right?.schema, join.right?.table);
  // Defensive: a join's LEFT table is normally the base or a prior join's right (already added), but
  // include any not-yet-covered left table (schema unknown -> assume base schema) so buildPayload's
  // reachable() filter can never silently drop a join when the model is edited.
  const values = Array.from(out.values());
  for (const join of model.relationships || []) {
    const lt = join.left?.table;
    if (lt && !values.some((t) => t.table === lt)) add(base.source_schema, lt);
  }
  return Array.from(out.values());
}

function previewRows(preview: ModelPreview | null): Record<string, unknown>[] {
  return preview?.data || preview?.records || [];
}

function isCompleteJoin(join: TypeBJoin): boolean {
  return !!(
    join.left?.table && join.left?.column &&
    join.right?.schema && join.right?.table && join.right?.column
  );
}

function emptyJoin(baseSchema: string): TypeBJoin {
  return {
    type: "left",
    left: { table: "", column: "" },
    right: { schema: baseSchema || "mdp_staging", table: "", column: "" },
  };
}

// Stable key for a (schema, table) pair. pg identifiers are [a-z0-9_], so "//" is a safe separator
// that never collides with a real schema/table name. Used by the Source-table dropdown (F).
const SRC_SEP = "//";
function tableKey(schema?: string | null, table?: string | null): string {
  return table ? `${schema || ""}${SRC_SEP}${table}` : "";
}

// N (prompt 46): hide the "Create from Template" entry from the Data Models tab UI only. The handler
// (openTemplateCreate), the template drawer, the route and the backend are all kept intact.
const SHOW_CREATE_FROM_TEMPLATE = false;

function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// Type B Validate/Preview status (prompt 40): a single inline line next to the footer buttons so a
// click always shows feedback — fixing the "bấm không thấy gì" (nothing visible) gap where validate
// success / preview result were never rendered in the create/edit drawer.
type TbStatus =
  | { kind: "validating" }
  | { kind: "valid"; cols: number; warnings: number }
  | { kind: "invalid"; errors: number }
  | { kind: "previewing" }
  | { kind: "preview"; rows: number }
  | { kind: "error"; code: number };

function tbStatusFromError(error: unknown): TbStatus {
  return { kind: "error", code: error instanceof ApiError ? error.status : 0 };
}

function TbStatusLine({ status }: { status: TbStatus | null }) {
  if (!status) return <span className="text-xs text-neutral-400">idle</span>;
  switch (status.kind) {
    case "validating":
      return <span className="text-xs text-neutral-500">⏳ Validating…</span>;
    case "valid":
      return (
        <span className="text-xs text-success">
          ✓ Valid — {status.cols} column{status.cols === 1 ? "" : "s"}
          {status.warnings > 0 ? <span className="text-warning"> (+{status.warnings} warning{status.warnings === 1 ? "" : "s"})</span> : null}
        </span>
      );
    case "invalid":
      return <span className="text-xs text-danger">✗ {status.errors} error{status.errors === 1 ? "" : "s"}</span>;
    case "previewing":
      return <span className="text-xs text-neutral-500">⏳ Previewing…</span>;
    case "preview":
      return <span className="text-xs text-success">✓ Preview — {status.rows} row{status.rows === 1 ? "" : "s"}</span>;
    case "error":
      return <span className="text-xs text-danger">✗ Error{status.code ? ` (HTTP ${status.code})` : ""}</span>;
  }
}

function fieldErrors(items: unknown[]): ValidationMessage[] {
  return items.map((item) => {
    if (item && typeof item === "object") {
      const record = item as Record<string, unknown>;
      return {
        field: String(record.field || record.loc || "error"),
        message: String(record.message || record.msg || JSON.stringify(item)),
      };
    }
    return { field: "error", message: String(item) };
  });
}

function errorMessages(error: unknown): ValidationMessage[] {
  if (error instanceof ApiError && error.body && typeof error.body === "object") {
    const body = error.body as Record<string, unknown>;
    // Internal/FE routes: FastAPI {detail: string | [{msg,...}]}
    if ("detail" in body) {
      const detail = body.detail;
      if (Array.isArray(detail)) return fieldErrors(detail);
      return [{ field: "error", message: String(detail) }];
    }
    // Integration routes (/inbound, /outbound): envelope {code, message, data:{errors:[{field,msg}]}}
    const envData = body.data;
    if (envData && typeof envData === "object" && Array.isArray((envData as { errors?: unknown }).errors)) {
      return fieldErrors((envData as { errors: unknown[] }).errors);
    }
    if (typeof body.message === "string" && body.message) {
      return [{ field: "error", message: body.message }];
    }
  }
  return [{ field: "error", message: error instanceof Error ? error.message : String(error) }];
}

function DetailGrid({ items }: { items: Array<[string, unknown]> }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map(([label, value]) => (
        <div key={label} className="min-w-0 rounded-md border border-neutral-100 bg-neutral-50 px-3 py-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500">{label}</div>
          <div className="mt-1 truncate text-sm text-neutral-900" title={cellText(value) || "-"}>
            {cellText(value) || "-"}
          </div>
        </div>
      ))}
    </div>
  );
}

function DrawerSection({
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

function ActionIcon({
  title,
  onClick,
  children,
  danger,
}: {
  title: string;
  onClick: () => void;
  children: React.ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-md border text-neutral-600 transition-colors",
        danger
          ? "border-danger/20 text-danger hover:bg-danger/10"
          : "border-neutral-200 hover:border-brand/30 hover:bg-brand/10 hover:text-brand",
      )}
    >
      {children}
    </button>
  );
}

export default function DataModelsPage() {
  const [models, setModels] = useState<DataModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode | null>(null);
  const [selected, setSelected] = useState<DataModel | null>(null);
  const [form, setForm] = useState<FormState>(initialForm);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formErrors, setFormErrors] = useState<ValidationMessage[]>([]);
  const [warnings, setWarnings] = useState<ValidationMessage[]>([]);
  const [validation, setValidation] = useState<TypeBValidationResult | null>(null);
  const [preview, setPreview] = useState<ModelPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [tbStatus, setTbStatus] = useState<TbStatus | null>(null);
  const [confirm, setConfirm] = useState<DataModel | null>(null);
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [templateOpen, setTemplateOpen] = useState(false);
  const [templates, setTemplates] = useState<DataModelTemplate[]>([]);
  const [selectedTemplateKey, setSelectedTemplateKey] = useState("");
  const [templateForm, setTemplateForm] = useState<TemplateForm>(emptyTemplateForm());
  const [templateLoading, setTemplateLoading] = useState(false);

  const [schemas, setSchemas] = useState<string[]>([]);
  // H (prompt 44): table selection is consolidated into ONE multi-select. `selectedTables` is the set
  // of ticked tables (each remembers its schema, ticked across schemas); the BASE table (sourceSchema/
  // sourceTable) is the one marked "Base" (it holds the PK attribute). `browseSchema` is just which
  // schema's table list the checkbox picker currently shows.
  const [selectedTables, setSelectedTables] = useState<{ schema: string; table: string }[]>([]);
  const [browseSchema, setBrowseSchema] = useState("");
  const [sourceSchema, setSourceSchema] = useState("");
  const [sourceTable, setSourceTable] = useState("");
  const [columns, setColumns] = useState<DbColumn[]>([]);
  // Prompt 52: the SQL surface, kept in two-way sync with the builder. `sqlFocused` (state) drives the
  // builder->SQL effect; `sqlFocusedRef` is the synchronous guard the SQL->builder effect reads so a
  // programmatic regenerate (from the builder) never re-parses and loops.
  const [sqlText, setSqlText] = useState("");
  const [sqlError, setSqlError] = useState<string | null>(null);
  const [sqlWarnings, setSqlWarnings] = useState<string[]>([]);
  const [sqlFocused, setSqlFocused] = useState(false);
  const sqlFocusedRef = useRef(false);
  // Lazy caches so the table checkbox picker, joins editor, and per-attribute Source table/column
  // dropdowns can list tables/columns for ANY selected table. Keyed `${schema}.${table}`.
  const [tablesBySchema, setTablesBySchema] = useState<Record<string, DbTable[]>>({});
  const [columnsByTable, setColumnsByTable] = useState<Record<string, DbColumn[]>>({});
  const colFetchRef = useRef<Set<string>>(new Set());
  const tblFetchRef = useRef<Set<string>>(new Set());

  const [typeFilter, setTypeFilter] = useState("");
  const [domainFilter, setDomainFilter] = useState("");
  const [sourceLayerFilter, setSourceLayerFilter] = useState("");
  const [canonicalFilter, setCanonicalFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("active");
  const [search, setSearch] = useState("");

  const selectedTemplate = templates.find((template) => template.template_key === selectedTemplateKey) || null;

  const reload = useCallback(async () => {
    setLoading(true);
    setPageError(null);
    try {
      setModels(await listDataModels());
    } catch (error) {
      setPageError(error instanceof ApiError ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    if (!mode || form.type !== "B") return;
    if (schemas.length > 0) return;
    listSchemas()
      .then((items) => {
        setSchemas(items);
        // Default the checkbox picker's schema only (NOT the base - that is set by ticking a table).
        setBrowseSchema((cur) => cur || (items.includes("mdp_staging") ? "mdp_staging" : items[0] || ""));
      })
      .catch((error) => setFormErrors(errorMessages(error)));
  }, [form.type, mode, schemas.length]);

  useEffect(() => {
    if (!mode || form.type !== "B" || !sourceSchema || !sourceTable) {
      setColumns([]);
      return;
    }
    listColumns(sourceSchema, sourceTable)
      .then((items) => setColumns(items))
      .catch((error) => setFormErrors(errorMessages(error)));
  }, [form.type, mode, sourceSchema, sourceTable]);

  // A table's schema is whatever it was ticked under (selectedTables remembers it); the base table
  // resolves to the base schema. Used by render + the column lazy-loader + buildPayload.
  const resolveSchemaForTable = useCallback(
    (table: string): string => {
      if (!table || table === sourceTable) return sourceSchema;
      return selectedTables.find((t) => t.table === table)?.schema || sourceSchema;
    },
    [selectedTables, sourceSchema, sourceTable],
  );

  // Lazily fetch the table list for the schema being browsed + every selected table's schema.
  useEffect(() => {
    if (!mode || form.type !== "B") return;
    const needed = new Set<string>();
    if (browseSchema) needed.add(browseSchema);
    for (const t of selectedTables) if (t.schema) needed.add(t.schema);
    needed.forEach((schema) => {
      if (tablesBySchema[schema] || tblFetchRef.current.has(schema)) return;
      tblFetchRef.current.add(schema);
      listTables(schema)
        .then((items) => setTablesBySchema((m) => (m[schema] ? m : { ...m, [schema]: items })))
        .catch(() => {})
        .finally(() => tblFetchRef.current.delete(schema));
    });
  }, [mode, form.type, browseSchema, selectedTables, tablesBySchema]);

  // Lazily fetch columns for every selected (non-base) table so the join key-column dropdowns and the
  // per-attribute Source column dropdown can list them. The base table's columns live in `columns`.
  useEffect(() => {
    if (!mode || form.type !== "B") return;
    for (const { schema, table } of selectedTables) {
      if (!schema || !table || table === sourceTable) continue; // base handled by `columns`
      const key = `${schema}.${table}`;
      if (columnsByTable[key] || colFetchRef.current.has(key)) continue;
      colFetchRef.current.add(key);
      listColumns(schema, table)
        .then((items) => setColumnsByTable((m) => (m[key] ? m : { ...m, [key]: items })))
        .catch(() => {})
        .finally(() => colFetchRef.current.delete(key));
    }
  }, [mode, form.type, selectedTables, sourceTable, columnsByTable]);

  // ---- Prompt 52: SQL <-> builder two-way sync -----------------------------------------------
  // A normalized signature of the builder plan; changes here drive the builder->SQL regenerate.
  const builderPlanKey = useMemo(
    () =>
      JSON.stringify({
        s: sourceSchema,
        t: sourceTable,
        r: form.relationships,
        a: form.attributes.map((x) => [x.name, x.source_schema, x.source_table, x.source_column, x.data_type]),
        lo: form.latest_only,
        rc: form.recency_column,
        pk: form.primary_key,
      }),
    [sourceSchema, sourceTable, form.relationships, form.attributes, form.latest_only, form.recency_column, form.primary_key],
  );

  // Apply a parsed SQL plan to the builder. primary_key + latest_only/recency stay builder toggles
  // (never read from the SQL), so the live sync can never wipe them.
  function applyParsedPlan(plan: TypeBSqlPlan) {
    setSelectedTables(plan.selected_tables.map((t) => ({ schema: t.schema, table: t.table })));
    setSourceSchema(plan.base.schema);
    setSourceTable(plan.base.table);
    setForm((current) => {
      const pk = current.primary_key;
      const attributes = plan.attributes.map((a) => ({
        name: a.name,
        display_name: titleize(a.name),
        data_type: (a.data_type || "text") as AttrType,
        required: false,
        source_schema: a.source_schema,
        source_table: a.source_table,
        source_column: a.source_column,
        is_primary_key: a.name === pk,
      }));
      return {
        ...current,
        relationships: plan.relationships.map((r) => ({ ...r })),
        attributes: attributes.length ? attributes : current.attributes,
      };
    });
  }

  // builder -> SQL: regenerate the canonical SQL when the builder plan changes, unless the user is
  // editing the SQL box (then their text is preserved). Debounced; loop-safe (it only writes SQL
  // while the box is NOT focused, and the SQL->builder effect ignores writes made while unfocused).
  useEffect(() => {
    if (!mode || form.type !== "B") return;
    if (sqlFocused) return;
    const handle = setTimeout(async () => {
      try {
        const payload = buildPayload();
        const mapped = payload.attributes.filter((a) => a.source_table && a.source_column);
        if (!mapped.length || !sourceSchema || !sourceTable) {
          setSqlText("");
          return;
        }
        const res = await generateTypeBSql({
          base: { schema: sourceSchema, table: sourceTable },
          attributes: payload.attributes,
          relationships: payload.relationships,
          primary_key: payload.primary_key,
          latest_only: payload.latest_only,
          recency_column: payload.recency_column,
        });
        setSqlText(res.sql);
      } catch {
        // generate-sql is a read-only preview; on failure keep the last SQL text.
      }
    }, 400);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [builderPlanKey, sqlFocused, mode, form.type]);

  // SQL -> builder: when the user edits the SQL box, parse it (NEVER executed) and update the
  // builder; invalid / out-of-subset SQL shows an inline error and leaves the builder untouched.
  useEffect(() => {
    if (!mode || form.type !== "B") return;
    if (!sqlFocusedRef.current) return; // a programmatic regenerate from the builder -> do not re-parse
    const handle = setTimeout(async () => {
      if (!sqlText.trim()) {
        setSqlError(null);
        return;
      }
      try {
        const plan = await parseTypeBSql({
          sql: sqlText,
          primary_key: form.primary_key || undefined,
          latest_only: form.latest_only,
          recency_column: form.recency_column || undefined,
        });
        setSqlError(null);
        applyParsedPlan(plan);
        // Surface the validator's non-blocking warnings (the same checks the builder runs) + a notice
        // if the SQL re-aliased away the current primary key column (so the PK is not silently lost).
        const warns = (plan.warnings || []).map((w) => w.message).filter(Boolean);
        const names = new Set(plan.attributes.map((a) => a.name));
        if (plan.primary_key && !names.has(plan.primary_key)) {
          warns.unshift(`Primary key "${plan.primary_key}" is no longer a projected column - set a new primary key in the builder.`);
        }
        setSqlWarnings(warns);
      } catch (e) {
        const msgs = errorMessages(e).map((m) => m.message).filter(Boolean);
        setSqlError(msgs.length ? msgs.join("; ") : "Invalid SQL.");
        setSqlWarnings([]);
      }
    }, 400);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sqlText, mode, form.type]);
  // --------------------------------------------------------------------------------------------

  // The tables joins & attributes may use = exactly the ticked set (deduped).
  const availableTables = useMemo(() => {
    const seen = new Set<string>();
    return selectedTables.filter(({ schema, table }) => {
      const key = `${schema}.${table}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [selectedTables]);

  const columnsFor = useCallback(
    (schema: string, table: string): DbColumn[] => {
      if (table && table === sourceTable) return columns;
      return columnsByTable[`${schema}.${table}`] || [];
    },
    [columns, columnsByTable, sourceTable],
  );

  const isTableSelected = useCallback(
    (schema: string, table: string) => selectedTables.some((t) => t.schema === schema && t.table === table),
    [selectedTables],
  );

  // Tick/untick a table. Untick cascades: drop joins that reference it and reset attributes mapped to
  // it; if it was the base, clear the base. Ticking the first table makes it the base by default.
  function toggleTable(schema: string, table: string) {
    if (isTableSelected(schema, table)) {
      setSelectedTables((cur) => cur.filter((t) => !(t.schema === schema && t.table === table)));
      setForm((current) => ({
        ...current,
        relationships: current.relationships.filter((j) => j.left?.table !== table && j.right?.table !== table),
        attributes: current.attributes.map((a) =>
          a.source_table === table
            ? { ...a, source_schema: undefined, source_table: undefined, source_column: undefined }
            : a,
        ),
      }));
      if (schema === sourceSchema && table === sourceTable) {
        setSourceSchema("");
        setSourceTable("");
      }
    } else {
      setSelectedTables((cur) => [...cur, { schema, table }]);
      if (!sourceTable) {
        setSourceSchema(schema);
        setSourceTable(table);
      }
    }
  }

  function setBaseTable(schema: string, table: string) {
    setSourceSchema(schema);
    setSourceTable(table);
  }

  const filteredModels = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return models.filter((model) => {
      if (typeFilter && model.type !== typeFilter) return false;
      if (domainFilter && model.domain !== domainFilter) return false;
      if (sourceLayerFilter && model.source_layer !== sourceLayerFilter) return false;
      if (canonicalFilter && model.canonical_status !== canonicalFilter) return false;
      if (statusFilter && model.status !== statusFilter) return false;
      if (!needle) return true;
      return [model.name, model.display_name, model.domain, model.primary_key, modelSource(model)]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [canonicalFilter, domainFilter, models, search, sourceLayerFilter, statusFilter, typeFilter]);

  function clearMessages() {
    setFormErrors([]);
    setWarnings([]);
    setValidation(null);
    setPreview(null);
    setTbStatus(null);
    setNotice(null);
  }

  // Any form edit invalidates a prior Validate/Preview result → drop the status AND the now-stale
  // inline preview/validation, and bump the request generation so an in-flight response can't
  // overwrite the freshly-idle status.
  const tbGenRef = useRef(0);
  useEffect(() => {
    tbGenRef.current += 1;
    setTbStatus(null);
    setPreview(null);
    setValidation(null);
  }, [form]);

  function patchForm(patch: Partial<FormState>) {
    setForm((current) => ({ ...current, ...patch }));
  }

  function patchTemplateForm(patch: Partial<TemplateForm>) {
    setTemplateForm((current) => ({ ...current, ...patch }));
  }

  // Apply a patch to attributes[index] AND keep form.primary_key in lock-step with the PRIMARY
  // attribute's CURRENT name. Renaming the PK attribute (the radio-selected one, or the one whose
  // name equals primary_key) carries primary_key along, so the payload's primary_key always equals
  // an existing attribute.name - no more backend "primary_key must match one of the attribute names".
  function applyAttributePatch(
    current: FormState,
    index: number,
    patch: Partial<DataModelAttribute>,
  ): FormState {
    const old = current.attributes[index];
    const attrs = current.attributes.map((attribute, i) =>
      i === index ? { ...attribute, ...patch } : attribute,
    );
    let primary_key = current.primary_key;
    // Identify the PK row by its is_primary_key FLAG only (authoritative - set by setPrimaryAttribute,
    // formFromModel, generate/remove). The old "name === primary_key" heuristic could mis-fire on a
    // non-PK row that coincidentally shared the PK's name (reachable via the source dropdown, which
    // can set duplicate names) and silently steal the primary key.
    if (patch.name !== undefined && old?.is_primary_key === true) {
      primary_key = patch.name; // PK attribute renamed -> follow it
    }
    return { ...current, attributes: attrs, primary_key };
  }

  function updateAttribute(index: number, patch: Partial<DataModelAttribute>) {
    setForm((current) => applyAttributePatch(current, index, patch));
  }

  function setPrimaryAttribute(index: number) {
    setForm((current) => {
      const attrs = current.attributes.map((attribute, i) => ({
        ...attribute,
        is_primary_key: i === index,
      }));
      return { ...current, primary_key: attrs[index]?.name || "", attributes: attrs };
    });
  }

  function addJoin() {
    setForm((current) => ({ ...current, relationships: [...current.relationships, emptyJoin(sourceSchema)] }));
  }
  function updateJoin(index: number, patch: Partial<TypeBJoin>) {
    // Joins now only reference ticked tables; removing a join doesn't change table reachability
    // (that is `selectedTables`), so the prompt-43 right/left cascades are no longer needed here.
    setForm((current) => ({
      ...current,
      relationships: current.relationships.map((join, i) => (i === index ? { ...join, ...patch } : join)),
    }));
  }
  function removeJoin(index: number) {
    setForm((current) => ({ ...current, relationships: current.relationships.filter((_, i) => i !== index) }));
  }

  function addAttribute() {
    setForm((current) => ({
      ...current,
      attributes: [
        ...current.attributes,
        {
          ...emptyAttribute(),
          source_schema: current.type === "B" ? sourceSchema : undefined,
          source_table: current.type === "B" ? sourceTable : undefined,
        },
      ],
    }));
  }

  function removeAttribute(index: number) {
    setForm((current) => {
      const attrs = current.attributes.filter((_, i) => i !== index);
      const nextAttrs = attrs.length
        ? attrs
        : [{ name: "", display_name: "", data_type: "text" as AttrType, is_primary_key: true }];
      const key = nextAttrs.find((attribute) => attribute.is_primary_key)?.name || nextAttrs[0]?.name || "";
      return {
        ...current,
        attributes: nextAttrs.map((attribute, i) => ({ ...attribute, is_primary_key: attribute.name === key || i === 0 })),
        primary_key: key,
      };
    });
  }

  function generateAttributes() {
    const attrs = columns.map((column, index) => {
      const name = attrName(column.column_name);
      return {
        name,
        display_name: titleize(name),
        data_type: normalizePgType(column.data_type),
        required: false,
        description: "",
        source_schema: sourceSchema,
        source_table: sourceTable,
        source_column: column.column_name,
        is_primary_key: index === 0,
      };
    });
    setForm((current) => ({
      ...current,
      attributes: attrs,
      primary_key: attrs[0]?.name || "",
    }));
    setWarnings([
      {
        field: "attributes",
        message: "Reserved system columns are automatically renamed with source_ prefix.",
      },
    ]);
  }

  // F: the attribute source is two cascading dropdowns (Source table -> Source column).
  // Picking a table sets source_schema/table and clears the column (its old column may not exist
  // in the new table). The base table maps to source_schema=base; a joined table to its own schema.
  function selectAttributeTable(index: number, value: string) {
    const [schema, table] = value ? value.split(SRC_SEP) : ["", ""];
    setForm((current) =>
      applyAttributePatch(current, index, {
        source_schema: table ? schema : undefined,
        source_table: table || undefined,
        source_column: undefined,
      }),
    );
  }

  // F: picking the column auto-fills data_type and sets the attribute name (still editable).
  // PK sync runs via applyAttributePatch (so renaming/source-picking the PK row keeps primary_key).
  function selectAttributeColumn(index: number, schema: string, table: string, columnName: string) {
    if (!columnName) return; // placeholder -> leave the row's existing column untouched
    const column = columnsFor(schema, table).find((c) => c.column_name === columnName);
    const suggested = attrName(columnName);
    setForm((current) => {
      const existing = current.attributes[index];
      const patch: Partial<DataModelAttribute> = {
        data_type: normalizePgType(column?.data_type || "text"),
        source_schema: schema,
        source_table: table,
        source_column: columnName,
      };
      // Auto-fill name/display_name ONLY when empty, so re-picking a source for a curated attribute
      // (edit mode) doesn't clobber its name (and, via applyAttributePatch, the PK that follows it).
      if (!existing?.name?.trim()) patch.name = suggested;
      if (!existing?.display_name?.trim()) patch.display_name = titleize(suggested);
      return applyAttributePatch(current, index, patch);
    });
  }

  function buildPayload(): DataModelCreate {
    // A joined attribute's schema must match the schema of the join that brings its table in (not
    // blindly the base schema) so cross-schema joins pass the backend connectivity check.
    const joins = form.type === "B" ? form.relationships : [];
    const schemaForTable = (table: string): string => {
      if (!table || table === sourceTable) return sourceSchema;
      return joins.find((join) => join.right?.table === table)?.right?.schema || sourceSchema;
    };
    const attributes = form.attributes
      .filter((attribute) => attribute.name.trim())
      .map((attribute) => {
        const name = snake(attribute.name);
        const table = form.type === "B" ? attribute.source_table || sourceTable : attribute.source_table;
        return {
          ...attribute,
          name,
          display_name: emptyToNull(attribute.display_name || "") || titleize(name),
          description: emptyToNull(attribute.description || ""),
          sensitivity: emptyToNull(attribute.sensitivity || ""),
          // Per-attribute source overrides the base table (multi-table, prompt 38); blank = base.
          // Honour the schema the Source-table dropdown stored (it carries the exact schema via
          // tableKey) so a table name joined from two different schemas keeps the right one; fall
          // back to deriving it from the join graph by table name.
          source_schema: form.type === "B" ? attribute.source_schema || schemaForTable(table || "") : attribute.source_schema || undefined,
          source_table: form.type === "B" ? table || undefined : attribute.source_table || undefined,
          source_column: attribute.source_column || undefined,
          is_primary_key: attribute.is_primary_key || name === form.primary_key,
        };
      });
    // C: the primary_key we send is GUARANTEED to equal one of the attribute names (snaked), and
    // is_primary_key is flagged on exactly that attribute - so the backend never rejects with
    // "primary_key must match one of the attribute names".
    const attrNames = new Set(attributes.map((attribute) => attribute.name));
    let primary = form.primary_key;
    if (!primary || !attrNames.has(primary)) {
      primary = attributes.find((attribute) => attribute.is_primary_key)?.name || attributes[0]?.name || "";
    }
    for (const attribute of attributes) attribute.is_primary_key = attribute.name === primary;
    // Blank "Left table" defaults to the base table before filtering. Safety net: a join referencing a
    // table outside the ticked set is dropped rather than sent (the dropdowns already constrain this).
    const selectedNames = new Set(selectedTables.map((t) => t.table));
    const reachable = (table: string) => !table || table === sourceTable || selectedNames.has(table);
    const relationships =
      form.type === "B"
        ? form.relationships
            .map((join) => ({ ...join, left: { ...join.left, table: join.left.table || sourceTable } }))
            .filter((join) => isCompleteJoin(join) && reachable(join.left.table) && reachable(join.right.table))
        : null;
    return {
      relationships: relationships && relationships.length ? relationships : null,
      name: snake(form.name),
      display_name: form.display_name.trim() || titleize(form.name),
      type: form.type,
      category: emptyToNull(form.category),
      namespace: emptyToNull(form.namespace),
      domain: emptyToNull(form.domain),
      entity_type: emptyToNull(form.entity_type),
      business_process: emptyToNull(form.business_process),
      source_layer: emptyToNull(form.source_layer),
      canonical_status: emptyToNull(form.canonical_status),
      site_scope: emptyToNull(form.site_scope),
      description: emptyToNull(form.description),
      business_definition: emptyToNull(form.business_definition),
      owner_department: emptyToNull(form.owner_department),
      source_system: emptyToNull(form.source_system),
      primary_key: primary || null,
      refresh_policy: emptyToNull(form.refresh_policy),
      sensitivity_level: emptyToNull(form.sensitivity_level),
      ai_enabled: form.ai_enabled,
      status: form.status || "active",
      attributes,
      // Type B dedup (prompt 50). Send the boolean for Type B so toggling OFF on edit clears the
      // saved config; recency only matters when ON. OFF persists no config -> old behaviour intact.
      ...(form.type === "B"
        ? {
            latest_only: form.latest_only,
            recency_column: form.latest_only ? form.recency_column || "updated_at" : null,
          }
        : {}),
    };
  }

  function validateLocal(payload: DataModelCreate): ValidationMessage[] {
    const errors: ValidationMessage[] = [];
    if (!/^[a-z][a-z0-9_]*$/.test(payload.name)) {
      errors.push({ field: "name", message: "Name must be lowercase snake_case." });
    }
    if (!payload.attributes.length) {
      errors.push({ field: "attributes", message: "Add at least one attribute." });
    }
    if (!payload.primary_key) {
      errors.push({ field: "primary_key", message: "Select a primary key attribute." });
    }
    // K (prompt 45): ATTRIBUTE is a placeholder now, so a blank attribute name is an explicit error.
    // (buildPayload drops blank-name rows, so check the form rows directly rather than the payload.)
    form.attributes.forEach((attribute, index) => {
      if (!attribute.name.trim()) {
        errors.push({ field: `attributes[${index}].name`, message: "Attribute name required." });
      }
    });
    // Surface duplicate attribute names (the source dropdown can suggest a name that collides) - they
    // make is_primary_key ambiguous and the backend rejects them anyway.
    const seenNames = new Map<string, number>();
    payload.attributes.forEach((attribute, index) => {
      const first = seenNames.get(attribute.name);
      if (first === undefined) seenNames.set(attribute.name, index);
      else errors.push({ field: `attributes[${index}].name`, message: `Duplicate attribute name "${attribute.name}".` });
    });
    // I (prompt 44): a Type B attribute can only map to a ticked table; the PK attribute must map to
    // the base table. Flag both on the FE instead of letting the backend reject cryptically.
    const selectedNames = new Set<string>(selectedTables.map((t) => t.table));
    payload.attributes.forEach((attribute, index) => {
      if (!/^[a-z][a-z0-9_]*$/.test(attribute.name)) {
        errors.push({ field: `attributes[${index}].name`, message: "Attribute name must be lowercase snake_case." });
      }
      if (SYSTEM_COLS.has(attribute.name)) {
        errors.push({ field: `attributes[${index}].name`, message: "Reserved platform system column name." });
      }
      if (payload.type === "B" && (!attribute.source_schema || !attribute.source_table || !attribute.source_column)) {
        errors.push({ field: `attributes[${index}].source_column`, message: "Type B attributes require source mapping." });
      } else if (payload.type === "B" && attribute.source_table && !selectedNames.has(attribute.source_table)) {
        errors.push({
          field: `attributes[${index}].source_table`,
          message: `Source table "${attribute.source_table}" is not in the selected tables. Tick it above or pick another source.`,
        });
      }
      if (
        payload.type === "B" &&
        attribute.name === payload.primary_key &&
        attribute.source_table &&
        sourceTable &&
        attribute.source_table !== sourceTable
      ) {
        errors.push({
          field: `attributes[${index}].source_table`,
          message: "The primary key attribute must map to the Base table.",
        });
      }
    });
    // Prompt 50: "Latest version only" requires a recency column (the red-* required field).
    if (payload.type === "B" && form.latest_only && !form.recency_column) {
      errors.push({ field: "recency_column", message: "Recency column is required when Latest version only is on." });
    }
    return errors;
  }

  async function openTemplateCreate() {
    clearMessages();
    setTemplateOpen(true);
    setTemplateLoading(true);
    try {
      const loaded = await listDataModelTemplates();
      setTemplates(loaded);
      const first = loaded[0] || null;
      setSelectedTemplateKey(first?.template_key || "");
      setTemplateForm(emptyTemplateForm(first));
    } catch (error) {
      setFormErrors(errorMessages(error));
    } finally {
      setTemplateLoading(false);
    }
  }

  function changeTemplate(templateKey: string) {
    const template = templates.find((item) => item.template_key === templateKey) || null;
    setSelectedTemplateKey(templateKey);
    setTemplateForm(emptyTemplateForm(template));
  }

  async function createFromTemplate() {
    if (!selectedTemplateKey) return;
    setSaving(true);
    setFormErrors([]);
    setWarnings([]);
    try {
      let config: Record<string, unknown> | null = null;
      if (templateForm.config_json.trim()) {
        const parsed = JSON.parse(templateForm.config_json);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("Config override must be a JSON object.");
        }
        config = parsed as Record<string, unknown>;
      }
      const result = await createDataModelFromTemplate(selectedTemplateKey, {
        name: emptyToNull(templateForm.name),
        display_name: emptyToNull(templateForm.display_name),
        source_schema: emptyToNull(templateForm.source_schema),
        source_table: emptyToNull(templateForm.source_table),
        status: templateForm.status || "active",
        config,
      });
      setWarnings(result.warnings || []);
      setNotice(`Created ${result.data_model.name} from template.`);
      setTemplateOpen(false);
      await reload();
      if (result.data_model.type === "B") {
        await openPreview(result.data_model);
      }
    } catch (error) {
      setFormErrors(errorMessages(error));
    } finally {
      setSaving(false);
    }
  }

  async function openCreate() {
    clearMessages();
    setSelected(null);
    // initialForm already starts with an empty placeholder attribute (M) and primary_key="".
    setForm(initialForm());
    setMode("create");
    setSelectedTables([]);
    setSourceSchema("");
    setSourceTable("");
    setColumns([]);
    sqlFocusedRef.current = false;
    setSqlFocused(false);
    setSqlText("");
    setSqlError(null);
    setSqlWarnings([]);
    if (!schemas.length) {
      try {
        const items = await listSchemas();
        setSchemas(items);
        setBrowseSchema(items.includes("mdp_staging") ? "mdp_staging" : items[0] || "");
      } catch (error) {
        setFormErrors(errorMessages(error));
      }
    } else {
      setBrowseSchema(schemas.includes("mdp_staging") ? "mdp_staging" : schemas[0] || "");
    }
  }

  async function loadModel(id: string): Promise<DataModel | null> {
    setDetailLoading(true);
    setFormErrors([]);
    try {
      return await getDataModel(id);
    } catch (error) {
      setPageError(error instanceof ApiError ? error.message : String(error));
      return null;
    } finally {
      setDetailLoading(false);
    }
  }

  async function openView(model: DataModel) {
    clearMessages();
    setMode("view");
    const detail = await loadModel(model.id);
    if (detail) setSelected(detail);
  }

  async function openEdit(model: DataModel) {
    clearMessages();
    setMode("edit");
    sqlFocusedRef.current = false;
    setSqlFocused(false);
    setSqlText("");
    setSqlError(null);
    setSqlWarnings([]);
    const detail = await loadModel(model.id);
    if (!detail) return;
    setSelected(detail);
    const next = formFromModel(detail);
    setForm(next);
    const source = typeBSource(detail);
    setSourceSchema(source.source_schema);
    setSourceTable(source.source_table);
    setSelectedTables(detail.type === "B" ? selectedTablesFromModel(detail) : []);
    setBrowseSchema(source.source_schema || (schemas.includes("mdp_staging") ? "mdp_staging" : schemas[0] || ""));
  }

  async function openPreview(model: DataModel) {
    clearMessages();
    setMode("preview");
    setPreviewLoading(true);
    const detail = await loadModel(model.id);
    if (!detail) {
      setPreviewLoading(false);
      return;
    }
    setSelected(detail);
    try {
      const result = detail.type === "B" ? await previewSavedTypeBModel(detail.id, 20) : await outbound(detail.name, { limit: 20 });
      setPreview(result);
      setWarnings(result.warnings || []);
    } catch (error) {
      setFormErrors(errorMessages(error));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function runValidate(): Promise<boolean> {
    const payload = buildPayload();
    const localErrors = validateLocal(payload);
    if (localErrors.length) {
      setFormErrors(localErrors);
      setTbStatus({ kind: "invalid", errors: localErrors.length });
      return false;
    }
    if (payload.type !== "B") {
      setFormErrors([]);
      setWarnings([]);
      setTbStatus(null);
      return true;
    }
    const gen = tbGenRef.current;
    setTbStatus({ kind: "validating" });
    try {
      const result = await validateTypeBMapping(payload);
      if (gen !== tbGenRef.current) return false; // a form edit invalidated this request
      setValidation(result);
      setWarnings(result.warnings || []);
      setFormErrors([]);
      setTbStatus({ kind: "valid", cols: result.mapped_columns?.length ?? 0, warnings: (result.warnings || []).length });
      return true;
    } catch (error) {
      if (gen !== tbGenRef.current) return false;
      setValidation(null);
      setWarnings([]);
      setFormErrors(errorMessages(error));
      setTbStatus(tbStatusFromError(error));
      return false;
    }
  }

  async function runUnsavedPreview() {
    const ok = await runValidate();
    if (!ok) return;
    const gen = tbGenRef.current;
    setPreviewLoading(true);
    setTbStatus({ kind: "previewing" });
    try {
      const result = await previewTypeBMapping(buildPayload(), 20);
      if (gen !== tbGenRef.current) return; // a form edit invalidated this request
      setPreview(result);
      setWarnings(result.warnings || []);
      setTbStatus({ kind: "preview", rows: result.count ?? previewRows(result).length });
    } catch (error) {
      if (gen === tbGenRef.current) {
        setPreview(null);
        setFormErrors(errorMessages(error));
        setTbStatus(tbStatusFromError(error));
      }
    } finally {
      setPreviewLoading(false);
    }
  }

  async function saveModel() {
    const payload = buildPayload();
    const localErrors = validateLocal(payload);
    if (localErrors.length) {
      setFormErrors(localErrors);
      return;
    }
    if (payload.type === "B") {
      const ok = await runValidate();
      if (!ok) return;
    }
    setSaving(true);
    try {
      if (mode === "edit" && selected) {
        await updateDataModel(selected.id, payload);
        setNotice(`Updated ${payload.name}.`);
      } else {
        await createDataModel(payload);
        setNotice(`Created ${payload.name}.`);
      }
      setMode(null);
      await reload();
    } catch (error) {
      setFormErrors(errorMessages(error));
    } finally {
      setSaving(false);
    }
  }

  async function toggleStatus(model: DataModel) {
    setSaving(true);
    setPageError(null);
    try {
      if (model.status === "active") {
        await deleteDataModel(model.id);
        setNotice(`Deactivated ${model.name}.`);
      } else {
        await updateDataModel(model.id, { status: "active" });
        setNotice(`Activated ${model.name}.`);
      }
      setConfirm(null);
      await reload();
    } catch (error) {
      setPageError(error instanceof ApiError ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }

  // Admin-only HARD delete of the model record. The generated mdp_data.dm_* table + data are KEPT.
  async function purgeModel(model: DataModel) {
    if (
      !window.confirm(
        `Delete model “${model.name}” permanently?\n\nThe generated table mdp_data.dm_${model.name} ` +
          `and ALL its data are KEPT (not dropped). Re-creating a model with this name reuses the table.`,
      )
    )
      return;
    setSaving(true);
    setPageError(null);
    try {
      await purgeDataModel(model.id);
      setNotice(`Deleted model ${model.name} (generated table + data kept).`);
      await reload();
    } catch (error) {
      setPageError(error instanceof ApiError ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }

  const modalTitle =
    mode === "create"
      ? "Create Data Model"
      : mode === "edit"
        ? "Edit Data Model"
        : mode === "preview"
          ? "Preview Data Model"
          : "View Data Model";

  return (
    <>
      <PageHeader
        title="Data Models"
        subtitle={`Public API: ${apiPath("/data-models")} · Backend route: /data-models.`}
        action={
          <div className="flex flex-wrap gap-2">
            {SHOW_CREATE_FROM_TEMPLATE && (
              <Button variant="secondary" onClick={openTemplateCreate}>
                <ClipboardList size={16} />
                Create from Template
              </Button>
            )}
            <Button onClick={openCreate}>New Data Model</Button>
          </div>
        }
      />

      {pageError && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{pageError}</p>}
      {notice && <p className="mb-4 rounded-md bg-success/10 px-3 py-2 text-sm text-success">{notice}</p>}

      <Card className="mb-4">
        <CardBody>
          <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Input label="Search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="supplier, procurement..." />
            <Select label="Type" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
              <option value="">All</option>
              <option value="A">Type A</option>
              <option value="B">Type B</option>
            </Select>
            <Select label="Domain" value={domainFilter} onChange={(event) => setDomainFilter(event.target.value)}>
              <option value="">All</option>
              {DOMAINS.map((item) => (
                <option key={item} value={item}>{titleize(item)}</option>
              ))}
            </Select>
            <Select label="Source layer" value={sourceLayerFilter} onChange={(event) => setSourceLayerFilter(event.target.value)}>
              <option value="">All</option>
              {SOURCE_LAYERS.map((item) => (
                <option key={item} value={item}>{titleize(item)}</option>
              ))}
            </Select>
            <Select label="Canonical" value={canonicalFilter} onChange={(event) => setCanonicalFilter(event.target.value)}>
              <option value="">All</option>
              {CANONICAL_STATUSES.map((item) => (
                <option key={item} value={item}>{titleize(item)}</option>
              ))}
            </Select>
            <Select label="Status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">All</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </Select>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="All data models" subtitle={`${filteredModels.length} shown · ${models.length} total`} />
        <CardBody>
          {loading ? (
            <p className="text-sm text-neutral-400">Loading...</p>
          ) : filteredModels.length === 0 ? (
            <p className="rounded-md border border-dashed border-neutral-200 px-4 py-8 text-center text-sm text-neutral-500">
              No data models match the current filters.
            </p>
          ) : (
            <Table className="table-fixed text-[13px]">
              <colgroup>
                <col className="w-[138px]" />
                <col className="w-[220px]" />
                <col className="w-[180px]" />
                <col className="w-[86px]" />
                <col className="w-[132px]" />
                <col className="w-[270px]" />
                <col className="w-[150px]" />
                <col className="w-[110px]" />
                <col className="w-[145px]" />
              </colgroup>
              <THead>
                <TR>
                  <TH className="text-center">Actions</TH>
                  <TH className="text-center">Display Name</TH>
                  <TH className="text-center">Name</TH>
                  <TH className="text-center">Type</TH>
                  <TH className="text-center">Domain</TH>
                  <TH className="text-center">Source / Storage</TH>
                  <TH className="text-center">Primary Key</TH>
                  <TH className="text-center">Status</TH>
                  <TH className="text-center">Canonical</TH>
                </TR>
              </THead>
              <TBody>
                {filteredModels.map((model) => (
                  <TR key={model.id}>
                    <TD className="sticky left-0 z-10 bg-white">
                      <div className="flex items-center justify-center gap-1.5">
                        <ActionIcon title={`View ${model.name}`} onClick={() => openView(model)}>
                          <Eye size={15} />
                        </ActionIcon>
                        <ActionIcon title={`Edit ${model.name}`} onClick={() => openEdit(model)}>
                          <Pencil size={15} />
                        </ActionIcon>
                        <ActionIcon title={`Preview ${model.name}`} onClick={() => openPreview(model)}>
                          <TableProperties size={15} />
                        </ActionIcon>
                        <ActionIcon
                          title={model.status === "active" ? `Deactivate ${model.name}` : `Activate ${model.name}`}
                          onClick={() => setConfirm(model)}
                          danger={model.status === "active"}
                        >
                          {model.status === "active" ? <Power size={15} /> : <RotateCcw size={15} />}
                        </ActionIcon>
                        {isAdmin && (
                          <ActionIcon
                            title={`Delete ${model.name} (keeps generated table + data)`}
                            onClick={() => purgeModel(model)}
                            danger
                          >
                            <Trash2 size={15} />
                          </ActionIcon>
                        )}
                      </div>
                    </TD>
                    <TD className="truncate font-medium" title={model.display_name || model.name}>
                      {model.display_name || model.name}
                    </TD>
                    <TD className="truncate font-mono text-xs" title={model.name}>{model.name}</TD>
                    <TD className="text-center">
                      <Badge tone={model.type === "A" ? "success" : "info"}>{model.type === "A" ? "Type A" : "Type B"}</Badge>
                    </TD>
                    <TD className="truncate" title={model.domain || ""}>{titleize(model.domain)}</TD>
                    <TD className="truncate font-mono text-xs" title={modelSource(model)}>{modelSource(model)}</TD>
                    <TD className="truncate font-mono text-xs" title={model.primary_key || ""}>{model.primary_key || "-"}</TD>
                    <TD className="text-center">
                      <Badge tone={model.status === "active" ? "success" : "neutral"}>{titleize(model.status)}</Badge>
                    </TD>
                    <TD className="text-center">
                      <Badge tone={model.canonical_status === "canonical" || model.canonical_status === "curated" ? "info" : "neutral"}>
                        {titleize(model.canonical_status)}
                      </Badge>
                    </TD>
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
        title="Create Data Model from Template"
        className="data-model-dialog overflow-hidden"
        footer={
          <>
            <Button variant="ghost" onClick={() => setTemplateOpen(false)}>Cancel</Button>
            <Button onClick={createFromTemplate} disabled={saving || templateLoading || !selectedTemplateKey}>
              {saving ? "Creating..." : "Create Model"}
            </Button>
          </>
        }
      >
        <div className="pr-1">
          {renderMessages()}
          {renderTemplateCreate()}
        </div>
      </Modal>

      <Modal
        open={mode !== null && mode !== "preview"}
        onClose={() => setMode(null)}
        title={modalTitle}
        className="data-model-dialog overflow-hidden"
        footer={
          mode === "view" ? (
            <>
              <Button variant="ghost" onClick={() => setMode(null)}>Close</Button>
              {selected && <Button onClick={() => openEdit(selected)}>Edit Model</Button>}
            </>
          ) : (
            <>
              <Button variant="ghost" onClick={() => setMode(null)}>Cancel</Button>
              {form.type === "B" && (
                <>
                  <span className="mr-auto flex items-center pl-1"><TbStatusLine status={tbStatus} /></span>
                  <Button
                    variant="secondary"
                    onClick={runValidate}
                    disabled={saving || tbStatus?.kind === "validating" || tbStatus?.kind === "previewing"}
                  >
                    {tbStatus?.kind === "validating" ? "Validating…" : "Validate Mapping"}
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={runUnsavedPreview}
                    disabled={saving || previewLoading || tbStatus?.kind === "validating" || tbStatus?.kind === "previewing"}
                  >
                    {tbStatus?.kind === "previewing" || previewLoading ? "Previewing…" : "Preview Mapping"}
                  </Button>
                </>
              )}
              <Button
                onClick={saveModel}
                disabled={saving || tbStatus?.kind === "validating" || tbStatus?.kind === "previewing"}
              >
                {saving ? "Saving..." : mode === "edit" ? "Save Changes" : "Save Model"}
              </Button>
            </>
          )
        }
      >
        <div className="pr-1">
          {detailLoading && <p className="text-sm text-neutral-500">Loading data model...</p>}
          {mode === "view" && selected && renderView(selected)}
          {(mode === "create" || mode === "edit") && renderEditor()}
        </div>
      </Modal>

      <Modal
        open={mode === "preview"}
        onClose={() => setMode(null)}
        title="Preview Data Model"
        className="data-model-dialog overflow-hidden"
        footer={
          <>
            <Button variant="ghost" onClick={() => setMode(null)}>Close</Button>
            {selected && <Button variant="secondary" onClick={() => openView(selected)}>View Model</Button>}
          </>
        }
      >
        <div className="pr-1">
          {previewLoading && <p className="text-sm text-neutral-500">Loading preview...</p>}
          {selected && renderPreview(selected, preview)}
        </div>
      </Modal>

      <Modal
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title={confirm?.status === "active" ? "Deactivate Data Model" : "Activate Data Model"}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button>
            {confirm && (
              <Button
                variant={confirm.status === "active" ? "destructive" : "primary"}
                onClick={() => toggleStatus(confirm)}
                disabled={saving}
              >
                {saving ? "Working..." : confirm.status === "active" ? "Deactivate" : "Activate"}
              </Button>
            )}
          </>
        }
      >
        <p className="text-sm text-neutral-600">
          {confirm?.status === "active"
            ? "Deactivate this data model? Generated tables or staging tables will not be dropped."
            : "Activate this data model and make it available again?"}
        </p>
      </Modal>
    </>
  );

  function renderMessages() {
    return (
      <>
        {formErrors.length > 0 && (
          <div className="space-y-1 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">
            {formErrors.map((item, index) => (
              <p key={`${item.field}-${index}`}>
                <span className="font-semibold">{item.field}:</span> {item.message}
              </p>
            ))}
          </div>
        )}
        {warnings.length > 0 && (
          <div className="space-y-1 rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
            {warnings.map((item, index) => (
              <p key={`${item.field}-${index}`}>
                <span className="font-semibold">{item.field}:</span> {item.message}
              </p>
            ))}
          </div>
        )}
        {validation && formErrors.length === 0 && (
          <p className="rounded-md bg-success/10 px-3 py-2 text-sm text-success">{validation.message}</p>
        )}
      </>
    );
  }

  function renderTemplateCreate() {
    return (
      <div className="space-y-4">
        <p className="rounded-md bg-info/10 px-3 py-2 text-sm text-info">
          Type B templates turn migrated JDE staging tables or curated views into governed data models. Run or validate the related migration job first if the source object is missing.
        </p>
        {templateLoading ? (
          <p className="text-sm text-neutral-500">Loading templates...</p>
        ) : (
          <>
            <DrawerSection title="JDE Procurement Templates">
              <div className="grid gap-3 md:grid-cols-[minmax(260px,360px)_1fr]">
                <Select
                  label="Template"
                  requiredMark
                  value={selectedTemplateKey}
                  onChange={(event) => changeTemplate(event.target.value)}
                >
                  {templates.map((template) => (
                    <option key={template.template_key} value={template.template_key}>
                      {template.display_name}
                    </option>
                  ))}
                </Select>
                {selectedTemplate && (
                  <div className="rounded-md border border-neutral-100 bg-neutral-50 px-3 py-2 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-neutral-900">{selectedTemplate.display_name}</span>
                      <Badge tone="info">Type B</Badge>
                      <Badge tone={selectedTemplate.source_layer === "curated_view" ? "neutral" : "success"}>
                        {titleize(selectedTemplate.source_layer)}
                      </Badge>
                    </div>
                    <p className="mt-1 text-xs text-neutral-600">{selectedTemplate.description}</p>
                  </div>
                )}
              </div>
            </DrawerSection>
            {selectedTemplate && (
              <>
                <DrawerSection title="Template Summary">
                  <DetailGrid
                    items={[
                      ["Model Name", selectedTemplate.model_name],
                      ["Display Name", selectedTemplate.model_display_name],
                      ["Source", `${selectedTemplate.source_schema}.${selectedTemplate.source_table}`],
                      ["Primary Key", selectedTemplate.primary_key],
                      ["Domain", titleize(selectedTemplate.domain)],
                      ["Canonical Status", titleize(selectedTemplate.canonical_status)],
                      ["Migration Template", selectedTemplate.related_migration_template_key],
                      ["Migration Target", selectedTemplate.related_migration_target_table],
                    ]}
                  />
                </DrawerSection>
                <DrawerSection title="Overrides">
                  <div className="grid gap-3 md:grid-cols-2">
                    <Input label="Model name" value={templateForm.name} onChange={(event) => patchTemplateForm({ name: snake(event.target.value) })} />
                    <Input label="Display name" value={templateForm.display_name} onChange={(event) => patchTemplateForm({ display_name: event.target.value })} />
                    <Input label="Source schema" value={templateForm.source_schema} onChange={(event) => patchTemplateForm({ source_schema: event.target.value })} />
                    <Input label="Source table / view" value={templateForm.source_table} onChange={(event) => patchTemplateForm({ source_table: event.target.value })} />
                    <Select label="Status" value={templateForm.status} onChange={(event) => patchTemplateForm({ status: event.target.value })}>
                      <option value="active">Active</option>
                      <option value="inactive">Inactive</option>
                    </Select>
                  </div>
                  <div className="mt-3">
                    <label className="block">
                      <span className="mb-1.5 block text-sm font-medium text-neutral-700">Config Override JSON</span>
                      <textarea
                        value={templateForm.config_json}
                        onChange={(event) => patchTemplateForm({ config_json: event.target.value })}
                        rows={5}
                        className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 font-mono text-xs text-neutral-900 focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
                      />
                    </label>
                  </div>
                </DrawerSection>
                <DrawerSection title="Attributes" subtitle={`${selectedTemplate.attributes.length} mapped attribute(s)`}>
                  <Table className="table-fixed text-xs">
                    <colgroup>
                      <col className="w-[190px]" />
                      <col className="w-[110px]" />
                      <col className="w-[220px]" />
                      <col className="w-[90px]" />
                      <col className="w-[90px]" />
                    </colgroup>
                    <THead>
                      <TR>
                        <TH>Attribute</TH>
                        <TH>Type</TH>
                        <TH>Source Column</TH>
                        <TH className="text-center">Required</TH>
                        <TH className="text-center">Primary</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {selectedTemplate.attributes.map((attribute) => (
                        <TR key={attribute.name}>
                          <TD className="truncate font-mono text-xs" title={attribute.name}>{attribute.name}</TD>
                          <TD>{attribute.data_type}</TD>
                          <TD className="truncate font-mono text-xs" title={attribute.source_column || ""}>{attribute.source_column || "-"}</TD>
                          <TD className="text-center">{attribute.required ? "Yes" : "No"}</TD>
                          <TD className="text-center">{attribute.is_primary_key ? "Yes" : "No"}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </DrawerSection>
              </>
            )}
          </>
        )}
      </div>
    );
  }

  function renderEditor() {
    return (
      <div className="space-y-4">
        {renderMessages()}
        <DrawerSection title="Model Type" subtitle="Choose how this governed data model is backed.">
          <div className="grid gap-3 md:grid-cols-2">
            <button
              type="button"
              disabled={mode === "edit"}
              onClick={() => patchForm({ type: "A", source_layer: "generated_table", attributes: initialForm().attributes, relationships: [] })}
              className={cn(
                "rounded-lg border px-4 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-75",
                form.type === "A" ? "border-brand bg-brand/10" : "border-neutral-200 hover:border-brand/40",
              )}
            >
              <div className="text-sm font-semibold text-neutral-900">Type A - Ingested Model</div>
              <div className="mt-1 text-xs text-neutral-500">Receives JSON and creates a physical table.</div>
            </button>
            <button
              type="button"
              disabled={mode === "edit"}
              onClick={() => patchForm({ type: "B", source_layer: "", attributes: [] })}
              className={cn(
                "rounded-lg border px-4 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-75",
                form.type === "B" ? "border-brand bg-brand/10" : "border-neutral-200 hover:border-brand/40",
              )}
            >
              <div className="text-sm font-semibold text-neutral-900">Type B - Linked Model</div>
              <div className="mt-1 text-xs text-neutral-500">Maps to an existing staging table or view.</div>
            </button>
          </div>
        </DrawerSection>

        <DrawerSection title="Basic Information">
          <div className="grid gap-3 md:grid-cols-2">
            <Input label="Display name" requiredMark placeholder="Human-readable name" value={form.display_name} onChange={(event) => patchForm({ display_name: event.target.value })} />
            <Input
              label="Name"
              requiredMark
              placeholder="lowercase_snake_case"
              value={form.name}
              disabled={mode === "edit"}
              onChange={(event) => patchForm({ name: snake(event.target.value) })}
              hint="Lowercase snake_case."
            />
            <label className="md:col-span-2 block">
              <span className="mb-1.5 block text-sm font-medium text-neutral-700">Description</span>
              <textarea
                value={form.description}
                placeholder="What this model represents"
                onChange={(event) => patchForm({ description: event.target.value })}
                className="min-h-20 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm placeholder:text-neutral-400 focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
              />
            </label>
          </div>
        </DrawerSection>

        <DrawerSection
          title="Classification & Namespace"
          subtitle="Namespace helps future catalog, semantic search, IIoT hierarchy, and AI access."
        >
          <div className="grid gap-3 md:grid-cols-3">
            <Select label="Domain" value={form.domain} onChange={(event) => patchForm({ domain: event.target.value, category: event.target.value })}>
              <option value="">-</option>
              {DOMAINS.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Input label="Entity type" placeholder="e.g. supplier" value={form.entity_type} onChange={(event) => patchForm({ entity_type: snake(event.target.value) })} />
            <Select label="Business process" value={form.business_process} onChange={(event) => patchForm({ business_process: event.target.value })}>
              <option value="">-</option>
              {BUSINESS_PROCESSES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Input className="font-mono" label="Namespace" placeholder="avenue.domain.entity" value={form.namespace} onChange={(event) => patchForm({ namespace: event.target.value })} />
            <Select label="Source layer" value={form.source_layer} onChange={(event) => patchForm({ source_layer: event.target.value })}>
              <option value="">Infer automatically</option>
              {SOURCE_LAYERS.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Select label="Canonical status" value={form.canonical_status} onChange={(event) => patchForm({ canonical_status: event.target.value })}>
              <option value="">-</option>
              {CANONICAL_STATUSES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Select label="Site scope" value={form.site_scope} onChange={(event) => patchForm({ site_scope: event.target.value })}>
              <option value="">-</option>
              {SITE_SCOPES.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
          </div>
        </DrawerSection>

        <DrawerSection title="Ownership & Governance">
          <div className="grid gap-3 md:grid-cols-3">
            <Select label="Source system" value={form.source_system} onChange={(event) => patchForm({ source_system: event.target.value })}>
              <option value="">-</option>
              {SOURCE_SYSTEMS.map((item) => <option key={item} value={item}>{item}</option>)}
            </Select>
            <Select label="Owner department" value={form.owner_department} onChange={(event) => patchForm({ owner_department: event.target.value })}>
              <option value="">-</option>
              {OWNER_DEPARTMENTS.map((item) => <option key={item} value={item}>{item}</option>)}
            </Select>
            <Select label="Sensitivity" value={form.sensitivity_level} onChange={(event) => patchForm({ sensitivity_level: event.target.value })}>
              {SENSITIVITY_LEVELS.map((item) => <option key={item} value={item}>{titleize(item)}</option>)}
            </Select>
            <Input label="Refresh policy" value={form.refresh_policy} onChange={(event) => patchForm({ refresh_policy: event.target.value })} />
            <Select label="Status" value={form.status} onChange={(event) => patchForm({ status: event.target.value })}>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </Select>
            {/* G (prompt 43): "AI enabled" removed from the Create/Edit form. The backend field stays
                (default true); the form still carries ai_enabled (default true / loaded value) and
                buildPayload sends it unchanged, so models save fine without the toggle. */}
            <label className="md:col-span-3 block">
              <span className="mb-1.5 block text-sm font-medium text-neutral-700">Business definition</span>
              <textarea
                value={form.business_definition}
                onChange={(event) => patchForm({ business_definition: event.target.value })}
                className="min-h-20 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
              />
            </label>
          </div>
        </DrawerSection>

        {form.type === "A" ? renderTypeAEditor() : renderTypeBEditor()}
        {preview && renderPreviewForResult(preview)}
      </div>
    );
  }

  function renderTypeAEditor() {
    return (
      <DrawerSection
        title="Type A Attributes"
        subtitle="Saving adds any new attribute as a column on the generated table. Existing columns are kept (no drop/rename), so no data is lost."
      >
        {renderAttributesTable(false)}
        <Button size="sm" variant="secondary" onClick={addAttribute} className="mt-3">Add Attribute</Button>
      </DrawerSection>
    );
  }

  function renderTypeBEditor() {
    return (
      <DrawerSection
        title="Type B Source & Mapping"
        subtitle="Source columns are mapped to data model attributes. Attribute names may differ from source column names."
      >
        {/* H: one place to choose every table this model reads from. Tick across schemas; mark one Base. */}
        <div className="mb-3 rounded-md border border-neutral-200 p-3">
          <div className="mb-2">
            <h4 className="text-sm font-semibold text-neutral-700">Source tables<RequiredMark /></h4>
            <p className="text-xs text-neutral-500">
              Tick every table this model reads from (you can tick across schemas). Mark one as
              <span className="font-medium"> Base</span> (the table that holds the primary key).
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <Select
                label="Schema"
                value={browseSchema}
                onChange={(event) => setBrowseSchema(event.target.value)}
                className={browseSchema ? "" : "text-neutral-400"}
              >
                <option value="" disabled>- Select schema -</option>
                {schemas.map((schema) => <option key={schema} value={schema}>{schema}</option>)}
              </Select>
              <div className="mt-2 max-h-44 overflow-y-auto rounded border border-neutral-100 p-2">
                {(tablesBySchema[browseSchema] || []).length === 0 ? (
                  <p className="text-xs text-neutral-400">No tables in this schema.</p>
                ) : (
                  (tablesBySchema[browseSchema] || []).map((t) => (
                    <label key={t.table_name} className="flex items-center gap-2 py-0.5 font-mono text-[11px] text-neutral-700">
                      <input
                        type="checkbox"
                        aria-label={`Select ${browseSchema}.${t.table_name}`}
                        checked={isTableSelected(browseSchema, t.table_name)}
                        onChange={() => toggleTable(browseSchema, t.table_name)}
                      />
                      {/* L (prompt 45): show only the table name. The relkind ("BASE TABLE"/"VIEW")
                          was confusing next to the "Base" radio, so it is hidden in the UI. */}
                      {t.table_name}
                    </label>
                  ))
                )}
              </div>
            </div>
            <div>
              <span className="mb-1.5 block text-sm font-medium text-neutral-700">Selected tables</span>
              <div className="min-h-[44px] rounded border border-neutral-100 p-2">
                {selectedTables.length === 0 ? (
                  <p className="text-xs text-neutral-400">Tick tables on the left to add them.</p>
                ) : (
                  selectedTables.map((st) => (
                    <div key={`${st.schema}.${st.table}`} className="flex items-center gap-2 py-0.5 font-mono text-[11px]">
                      <label className="flex items-center gap-1 text-neutral-700">
                        <input
                          type="radio"
                          name="base_table"
                          aria-label={`Base ${st.schema}.${st.table}`}
                          checked={st.schema === sourceSchema && st.table === sourceTable}
                          onChange={() => setBaseTable(st.schema, st.table)}
                        />
                        Base
                      </label>
                      <span className="text-neutral-800">{st.schema}.{st.table}</span>
                      <button
                        type="button"
                        title="Remove table"
                        aria-label={`Remove ${st.schema}.${st.table}`}
                        onClick={() => toggleTable(st.schema, st.table)}
                        className="ml-auto rounded px-1 text-danger hover:bg-danger/10"
                      >
                        remove
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Button size="sm" variant="secondary" onClick={generateAttributes} disabled={!columns.length}>
            Generate Attributes from Source Columns
          </Button>
          <Button size="sm" variant="ghost" onClick={addAttribute}>Add Attribute</Button>
          <span className="text-xs text-neutral-500">Reserved system columns are automatically renamed with source_ prefix.</span>
        </div>
        {renderAttributesTable(true)}
        {renderRelationshipsEditor()}
        {renderLatestVersionEditor()}
        {renderSqlPanel()}
      </DrawerSection>
    );
  }

  // Y (prompt 52): the SQL surface, in two-way sync with the builder above. READ-ONLY - the SQL is
  // parsed to define joins/columns, never executed. PK and "Latest version only" are builder toggles.
  function renderSqlPanel() {
    return (
      <div className="mt-4 rounded-md border border-neutral-200 p-3">
        <div className="mb-2">
          <h4 className="text-sm font-semibold text-neutral-700">SQL definition (read-only)</h4>
          <p className="text-xs text-neutral-500">
            Define the joins and columns as a single SELECT - it stays in sync with the builder above
            both ways. The SQL is parsed only, never executed. Primary key and &quot;Latest version
            only&quot; are set in the builder, not in SQL.
          </p>
        </div>
        <textarea
          aria-label="Type B SQL"
          value={sqlText}
          onChange={(event) => {
            sqlFocusedRef.current = true;
            setSqlText(event.target.value);
          }}
          onFocus={() => {
            sqlFocusedRef.current = true;
            setSqlFocused(true);
          }}
          onBlur={() => {
            sqlFocusedRef.current = false;
            setSqlFocused(false);
          }}
          spellCheck={false}
          rows={8}
          placeholder={"SELECT t.col AS name\nFROM mdp_data.base_table t\nLEFT JOIN mdp_data.other o ON t.key = o.key"}
          className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 font-mono text-xs text-neutral-900 focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
        />
        {sqlError && (
          <p className="mt-1 rounded bg-danger/10 px-2 py-1 text-xs text-danger" role="alert">{sqlError}</p>
        )}
        {!sqlError && sqlWarnings.length > 0 && (
          <ul className="mt-1 space-y-0.5 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800">
            {sqlWarnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  // S (prompt 50): "Latest version only" toggle. ON wraps each source relation in a newest-row-per-key
  // dedup on the backend; the recency column (a required, red-* field) is what "newest" sorts by.
  function setLatestOnly(checked: boolean) {
    setForm((current) => {
      let recency = current.recency_column;
      if (checked && !recency) {
        recency = columns.some((c) => c.column_name === "updated_at") ? "updated_at" : "";
      }
      return { ...current, latest_only: checked, recency_column: recency };
    });
  }

  function renderLatestVersionEditor() {
    return (
      <div className="mt-4 rounded-md border border-neutral-200 p-3">
        <label className="flex items-center gap-2 text-sm font-medium text-neutral-700">
          <input
            type="checkbox"
            aria-label="Latest version only"
            checked={form.latest_only}
            onChange={(event) => setLatestOnly(event.target.checked)}
          />
          Latest version only (deduplicate by key)
        </label>
        <p className="mt-1 text-xs text-neutral-500">
          Keeps the newest row per key using the selected column.
        </p>
        {form.latest_only && (
          <div className="mt-2 max-w-xs">
            <Select
              label="Recency column"
              requiredMark
              aria-label="Recency column"
              value={form.recency_column}
              onChange={(event) => setForm((current) => ({ ...current, recency_column: event.target.value }))}
              className={cn("h-9 font-mono text-xs", form.recency_column ? "" : "text-neutral-400")}
            >
              <option value="" disabled>- Select column -</option>
              {/* Keep the saved recency column selectable before the base columns finish loading on Edit. */}
              {form.recency_column && !columns.some((c) => c.column_name === form.recency_column) && (
                <option value={form.recency_column}>{`${form.recency_column} (current)`}</option>
              )}
              {columns.map((column) => (
                <option key={column.column_name} value={column.column_name}>{column.column_name}</option>
              ))}
            </Select>
          </div>
        )}
      </div>
    );
  }

  function renderRelationshipsEditor() {
    return (
      <div className="mt-4 rounded-md border border-neutral-200 p-3">
        <div className="mb-2 flex items-center justify-between">
          <div>
            <h4 className="text-sm font-semibold text-neutral-700">Relationships / Joins (multi-table)</h4>
            <p className="text-xs text-neutral-500">
              Join the ticked tables. The <code>Right key column</code> must be unique (N:1) unless
              fan-out is allowed.
            </p>
          </div>
          <Button size="sm" variant="secondary" onClick={addJoin}>Add Join</Button>
        </div>
        {form.relationships.length === 0 ? (
          <p className="text-xs text-neutral-400">No joins - single-table model.</p>
        ) : (
          <div className="space-y-2">
            {form.relationships.map((join, index) => {
              // Both sides pick from the ticked set only. Left holds a table name (its schema is
              // resolved from selectedTables); right keeps {schema,table} so it stays unambiguous.
              const leftColumns = columnsFor(resolveSchemaForTable(join.left.table), join.left.table);
              const rightColumns = columnsFor(join.right.schema, join.right.table);
              const tableLabel = (t: { schema: string; table: string }) =>
                t.schema && t.schema !== sourceSchema ? `${t.schema}.${t.table}` : t.table;
              return (
                <div key={index} className="flex flex-wrap items-end gap-2 rounded border border-neutral-100 p-2">
                  <Select
                    label="Type"
                    value={join.type}
                    onChange={(event) => updateJoin(index, { type: event.target.value as TypeBJoin["type"] })}
                    className="h-8 min-w-[88px] text-xs"
                  >
                    <option value="left">left</option>
                    <option value="inner">inner</option>
                  </Select>
                  <Select
                    label="Left table"
                    requiredMark
                    value={join.left.table}
                    onChange={(event) => updateJoin(index, { left: { table: event.target.value, column: "" } })}
                    className={cn("h-8 min-w-[180px] font-mono text-[11px]", join.left.table ? "" : "text-neutral-400")}
                  >
                    <option value="" disabled>- Select table -</option>
                    {availableTables.map((t) => (
                      <option key={tableKey(t.schema, t.table)} value={t.table}>{tableLabel(t)}</option>
                    ))}
                  </Select>
                  <Select
                    label="Left key column"
                    requiredMark
                    value={join.left.column}
                    onChange={(event) => updateJoin(index, { left: { ...join.left, column: event.target.value } })}
                    className={cn("h-8 min-w-[160px] font-mono text-[11px]", join.left.column ? "" : "text-neutral-400")}
                  >
                    <option value="" disabled>- Select column -</option>
                    {leftColumns.map((column) => (
                      <option key={column.column_name} value={column.column_name}>{column.column_name}</option>
                    ))}
                  </Select>
                  <Select
                    label="Right table"
                    requiredMark
                    value={tableKey(join.right.schema, join.right.table)}
                    onChange={(event) => {
                      const [schema, table] = event.target.value ? event.target.value.split(SRC_SEP) : ["", ""];
                      updateJoin(index, { right: { schema, table, column: "" } });
                    }}
                    className={cn("h-8 min-w-[180px] font-mono text-[11px]", join.right.table ? "" : "text-neutral-400")}
                  >
                    <option value="" disabled>- Select table -</option>
                    {availableTables.map((t) => (
                      <option key={tableKey(t.schema, t.table)} value={tableKey(t.schema, t.table)}>{tableLabel(t)}</option>
                    ))}
                  </Select>
                  <Select
                    label="Right key column"
                    requiredMark
                    value={join.right.column}
                    onChange={(event) => updateJoin(index, { right: { ...join.right, column: event.target.value } })}
                    className={cn("h-8 min-w-[160px] font-mono text-[11px]", join.right.column ? "" : "text-neutral-400")}
                  >
                    <option value="" disabled>- Select column -</option>
                    {rightColumns.map((column) => (
                      <option key={column.column_name} value={column.column_name}>{column.column_name}</option>
                    ))}
                  </Select>
                  <label className="flex h-8 items-center gap-1 text-[11px] text-neutral-600">
                    <input
                      type="checkbox"
                      checked={!!join.allow_fanout}
                      onChange={(event) => updateJoin(index, { allow_fanout: event.target.checked })}
                    />
                    fan-out
                  </label>
                  <button
                    type="button"
                    title="Remove join"
                    onClick={() => removeJoin(index)}
                    className="h-8 rounded-md px-2 text-danger hover:bg-danger/10"
                  >
                    Remove
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  // I/F: two cascading dropdowns per attribute - Source table (ONLY the ticked tables) then Source
  // column (columns of THAT table). Picking the column auto-fills data_type + name.
  function renderSourceCell(attribute: DataModelAttribute, index: number) {
    const attrTable = attribute.source_table || sourceTable;
    const attrSchema = attribute.source_table ? attribute.source_schema || resolveSchemaForTable(attrTable) : sourceSchema;
    const cols = columnsFor(attrSchema, attrTable);
    const colKnown = !attribute.source_column || cols.some((c) => c.column_name === attribute.source_column);
    const curTableKey = tableKey(attrSchema, attrTable);
    const tableKnown = !attribute.source_table || availableTables.some((t) => tableKey(t.schema, t.table) === curTableKey);
    return (
      <div className="flex flex-col gap-1">
        <Select
          aria-label="Source table"
          value={curTableKey}
          onChange={(event) => selectAttributeTable(index, event.target.value)}
          className={cn("h-7 w-full font-mono text-[11px]", curTableKey ? "" : "text-neutral-400")}
        >
          <option value="" disabled>- Select table -</option>
          {/* Keep an orphaned mapping visible (e.g. its table was un-ticked) instead of a blank select. */}
          {attribute.source_table && !tableKnown && (
            <option value={curTableKey}>{`${attrSchema}.${attrTable} (current)`}</option>
          )}
          {availableTables.map((t) => {
            // Qualify with schema when it differs from the base so same-named tables stay distinct.
            const label = t.schema && t.schema !== sourceSchema ? `${t.schema}.${t.table}` : t.table;
            return <option key={tableKey(t.schema, t.table)} value={tableKey(t.schema, t.table)}>{label}</option>;
          })}
        </Select>
        <Select
          aria-label="Source column"
          value={attribute.source_column || ""}
          onChange={(event) => selectAttributeColumn(index, attrSchema, attrTable, event.target.value)}
          className={cn("h-7 w-full font-mono text-[11px]", attribute.source_column ? "" : "text-neutral-400")}
        >
          <option value="" disabled>- Select column -</option>
          {/* Keep the saved column selectable even before its table's columns finish loading. */}
          {attribute.source_column && !colKnown && (
            <option value={attribute.source_column}>{`${attribute.source_column} (current)`}</option>
          )}
          {cols.map((column) => (
            <option key={column.column_name} value={column.column_name}>{column.column_name}</option>
          ))}
        </Select>
      </div>
    );
  }

  function renderAttributesTable(typeB: boolean) {
    return (
      <Table className="table-fixed text-xs">
        <colgroup>
          <col className="w-[170px]" />
          <col className="w-[190px]" />
          <col className="w-[130px]" />
          {typeB && <col className="w-[320px]" />}
          <col className="w-[80px]" />
          <col className="w-[80px]" />
          {!typeB && <col className="w-[220px]" />}
          <col className="w-[82px]" />
        </colgroup>
        <THead>
          <TR>
            <TH>Attribute<RequiredMark /></TH>
            <TH>Display Name</TH>
            <TH>Data Type<RequiredMark /></TH>
            {typeB && <TH>Source table / column<RequiredMark /></TH>}
            <TH className="text-center">Required</TH>
            <TH className="text-center">Primary<RequiredMark /></TH>
            {!typeB && <TH>Description</TH>}
            <TH className="text-center">Actions</TH>
          </TR>
        </THead>
        <TBody>
          {form.attributes.map((attribute, index) => (
            // Key by position only — keying by `attribute.name` (the value the first input
            // edits) remounted the row on every keystroke, so the field lost focus after one
            // character. updateAttribute already updates immutably by index.
            <TR key={index}>
              <TD>
                <Input
                  aria-label="Attribute name"
                  placeholder="e.g. name"
                  value={attribute.name}
                  onChange={(event) => updateAttribute(index, { name: snake(event.target.value) })}
                  className="h-8 font-mono text-xs"
                />
              </TD>
              <TD>
                <Input
                  aria-label="Display name"
                  placeholder="e.g. Name"
                  value={attribute.display_name || ""}
                  onChange={(event) => updateAttribute(index, { display_name: event.target.value })}
                  className="h-8 text-xs"
                />
              </TD>
              <TD>
                <Select
                  aria-label="Data type"
                  value={attribute.data_type}
                  onChange={(event) => updateAttribute(index, { data_type: event.target.value as AttrType })}
                  className="h-8 text-xs"
                >
                  {ATTR_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
                </Select>
              </TD>
              {typeB && <TD>{renderSourceCell(attribute, index)}</TD>}
              <TD className="text-center">
                <input
                  type="checkbox"
                  checked={!!attribute.required}
                  onChange={(event) => updateAttribute(index, { required: event.target.checked })}
                />
              </TD>
              <TD className="text-center">
                <input
                  type="radio"
                  name="primary_key_attribute"
                  checked={!!attribute.is_primary_key}
                  onChange={() => setPrimaryAttribute(index)}
                />
              </TD>
              {!typeB && (
                <TD>
                  <Input
                    aria-label="Description"
                    value={attribute.description || ""}
                    onChange={(event) => updateAttribute(index, { description: event.target.value })}
                    className="h-8 text-xs"
                  />
                </TD>
              )}
              <TD className="text-center">
                <button
                  type="button"
                  title="Remove attribute"
                  aria-label="Remove attribute"
                  onClick={() => removeAttribute(index)}
                  className="rounded-md px-2 py-1 text-danger hover:bg-danger/10"
                >
                  Remove
                </button>
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    );
  }

  function renderView(model: DataModel) {
    const source = typeBSource(model);
    return (
      <div className="space-y-4">
        <DrawerSection title="Overview">
          <DetailGrid
            items={[
              ["Display Name", model.display_name || model.name],
              ["Name", model.name],
              ["Type", model.type === "A" ? "Type A" : "Type B"],
              ["Status", titleize(model.status)],
              ["Primary Key", model.primary_key],
            ]}
          />
        </DrawerSection>
        <DrawerSection title="Classification">
          <DetailGrid
            items={[
              ["Namespace", model.namespace],
              ["Domain", titleize(model.domain)],
              ["Entity Type", model.entity_type],
              ["Business Process", titleize(model.business_process)],
              ["Source Layer", titleize(model.source_layer)],
              ["Canonical Status", titleize(model.canonical_status)],
              ["Site Scope", titleize(model.site_scope)],
            ]}
          />
        </DrawerSection>
        <DrawerSection title="Governance">
          <DetailGrid
            items={[
              ["Source System", model.source_system],
              ["Owner Department", model.owner_department],
              ["Sensitivity Level", titleize(model.sensitivity_level)],
              ["AI Enabled", model.ai_enabled ? "Yes" : "No"],
              ["Refresh Policy", model.refresh_policy],
            ]}
          />
        </DrawerSection>
        <DrawerSection title="Storage / Source">
          {model.type === "A" ? (
            <DetailGrid
              items={[
                ["Generated Table", model.generated_table],
                ["Inbound Endpoint", `POST ${apiPath(`/inbound/${model.name}`)}`],
                ["Outbound List", `GET ${apiPath(`/outbound/${model.name}`)}`],
                ["Outbound By Key", `GET ${apiPath(`/outbound/${model.name}/{primary_key_value}`)}`],
              ]}
            />
          ) : (
            <DetailGrid
              items={[
                ["Source Schema", source.source_schema],
                ["Source Table/View", source.source_table],
                ["Outbound List", `GET ${apiPath(`/outbound/${model.name}`)}`],
                ["Outbound By Key", `GET ${apiPath(`/outbound/${model.name}/{primary_key_value}`)}`],
              ]}
            />
          )}
        </DrawerSection>
        <DrawerSection title="Attributes">
          {renderReadOnlyAttributes(model)}
        </DrawerSection>
      </div>
    );
  }

  function renderReadOnlyAttributes(model: DataModel) {
    return (
      <Table className="table-fixed text-xs">
        <colgroup>
          <col className="w-[180px]" />
          <col className="w-[190px]" />
          <col className="w-[110px]" />
          {model.type === "B" && <col className="w-[190px]" />}
          <col className="w-[90px]" />
          <col className="w-[90px]" />
          <col className="w-[120px]" />
        </colgroup>
        <THead>
          <TR>
            <TH>Attribute Name</TH>
            <TH>Display Name</TH>
            <TH>Data Type</TH>
            {model.type === "B" && <TH>Source Column</TH>}
            <TH className="text-center">Required</TH>
            <TH className="text-center">Primary</TH>
            <TH>Sensitivity</TH>
          </TR>
        </THead>
        <TBody>
          {(model.attributes || []).map((attribute) => (
            <TR key={attribute.name}>
              <TD className="truncate font-mono text-xs" title={attribute.name}>{attribute.name}</TD>
              <TD className="truncate" title={attribute.display_name || ""}>{attribute.display_name || "-"}</TD>
              <TD>{attribute.data_type}</TD>
              {model.type === "B" && (
                <TD className="truncate font-mono text-xs" title={attribute.source_column || ""}>{attribute.source_column || "-"}</TD>
              )}
              <TD className="text-center">{attribute.required ? "Yes" : "No"}</TD>
              <TD className="text-center">{attribute.is_primary_key || model.primary_key === attribute.name ? "Yes" : "No"}</TD>
              <TD>{attribute.sensitivity || "-"}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    );
  }

  function renderPreview(model: DataModel, result: ModelPreview | null) {
    const source = typeBSource(model);
    return (
      <div className="space-y-4">
        {renderMessages()}
        <DrawerSection title="Preview Context">
          <DetailGrid
            items={
              model.type === "B"
                ? [
                    ["Model", model.name],
                    ["Type", "Type B"],
                    ["Source Schema", source.source_schema],
                    ["Source Table/View", source.source_table],
                    ["Outbound List", `GET ${apiPath(`/outbound/${model.name}`)}`],
                    ["Outbound By Key", `GET ${apiPath(`/outbound/${model.name}/{primary_key_value}`)}`],
                  ]
                : [
                    ["Model", model.name],
                    ["Type", "Type A"],
                    ["Inbound Endpoint", `POST ${apiPath(`/inbound/${model.name}`)}`],
                    ["Outbound List", `GET ${apiPath(`/outbound/${model.name}`)}`],
                    ["Outbound By Key", `GET ${apiPath(`/outbound/${model.name}/{primary_key_value}`)}`],
                  ]
            }
          />
        </DrawerSection>
        {renderPreviewForResult(result)}
      </div>
    );
  }

  function renderPreviewForResult(result: ModelPreview | null) {
    const rows = previewRows(result).map((row) => {
      const copy = { ...row };
      delete copy.raw_payload;
      return copy;
    });
    const cols = Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).filter((column) => column !== "raw_payload");
    return (
      <DrawerSection title="Preview Rows" subtitle={result ? `${rows.length} row(s)` : undefined}>
        {!result ? (
          <p className="text-sm text-neutral-500">No preview loaded.</p>
        ) : rows.length === 0 ? (
          <p className="rounded-md border border-dashed border-neutral-200 px-4 py-8 text-center text-sm text-neutral-500">
            No rows found. Use the endpoint examples above to ingest or query data.
          </p>
        ) : (
          <Table className="table-fixed text-xs">
            <colgroup>
              {cols.map((column) => <col key={column} className="w-[180px]" />)}
            </colgroup>
            <THead>
              <TR>
                {cols.map((column) => <TH key={column}>{column}</TH>)}
              </TR>
            </THead>
            <TBody>
              {rows.map((row, index) => (
                <TR key={index}>
                  {cols.map((column) => (
                    <TD key={column} className="truncate font-mono text-xs" title={cellText(row[column])}>
                      {cellText(row[column]) || "-"}
                    </TD>
                  ))}
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </DrawerSection>
    );
  }
}
