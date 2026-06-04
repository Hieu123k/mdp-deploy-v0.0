"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ClipboardList, Eye, Pencil, Power, RotateCcw, TableProperties } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { EditableSelect } from "@/components/ui/EditableSelect";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import {
  ApiError,
  apiPath,
  ATTR_TYPES,
  createDataModelFromTemplate,
  createDataModel,
  deleteDataModel,
  getDataModel,
  listDataModelTemplates,
  listColumns,
  listDataModels,
  listSchemas,
  listTables,
  normalizePgType,
  outbound,
  previewSavedTypeBModel,
  previewTypeBMapping,
  updateDataModel,
  validateTypeBMapping,
  type AttrType,
  type DataModel,
  type DataModelAttribute,
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
// Business-process / site-scope / sensitivity / source-system / owner-department options are now
// admin-managed reference lists (see EditableSelect + /reference); the editor reads them live.

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
    .replace(/^_+|_+$/g, "")
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
    attributes: [
      {
        name: "code",
        display_name: "Code",
        data_type: "text",
        required: true,
        is_primary_key: true,
      },
    ],
  };
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
    attributes: (model.attributes || []).map((attribute) => ({ ...attribute })),
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
  return {
    source_schema: attrs.find((attribute) => attribute.source_schema)?.source_schema || "",
    source_table: attrs.find((attribute) => attribute.source_table)?.source_table || "",
  };
}

function previewRows(preview: ModelPreview | null): Record<string, unknown>[] {
  return preview?.data || preview?.records || [];
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function errorMessages(error: unknown): ValidationMessage[] {
  if (error instanceof ApiError && error.body && typeof error.body === "object" && "detail" in error.body) {
    const detail = (error.body as { detail: unknown }).detail;
    if (Array.isArray(detail)) {
      return detail.map((item) => {
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
    return [{ field: "error", message: String(detail) }];
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
  const [confirm, setConfirm] = useState<DataModel | null>(null);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [templates, setTemplates] = useState<DataModelTemplate[]>([]);
  const [selectedTemplateKey, setSelectedTemplateKey] = useState("");
  const [templateForm, setTemplateForm] = useState<TemplateForm>(emptyTemplateForm());
  const [templateLoading, setTemplateLoading] = useState(false);

  const [schemas, setSchemas] = useState<string[]>([]);
  const [sourceSchema, setSourceSchema] = useState("");
  const [tables, setTables] = useState<DbTable[]>([]);
  const [sourceTable, setSourceTable] = useState("");
  const [columns, setColumns] = useState<DbColumn[]>([]);

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
        const next = sourceSchema || (items.includes("mdp_staging") ? "mdp_staging" : items[0] || "");
        if (next) setSourceSchema(next);
      })
      .catch((error) => setFormErrors(errorMessages(error)));
  }, [form.type, mode, schemas.length, sourceSchema]);

  useEffect(() => {
    if (!mode || form.type !== "B" || !sourceSchema) return;
    setTables([]);
    listTables(sourceSchema)
      .then((items) => setTables(items))
      .catch((error) => setFormErrors(errorMessages(error)));
  }, [form.type, mode, sourceSchema]);

  useEffect(() => {
    if (!mode || form.type !== "B" || !sourceSchema || !sourceTable) {
      setColumns([]);
      return;
    }
    listColumns(sourceSchema, sourceTable)
      .then((items) => setColumns(items))
      .catch((error) => setFormErrors(errorMessages(error)));
  }, [form.type, mode, sourceSchema, sourceTable]);

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
    setNotice(null);
  }

  function patchForm(patch: Partial<FormState>) {
    setForm((current) => ({ ...current, ...patch }));
  }

  function patchTemplateForm(patch: Partial<TemplateForm>) {
    setTemplateForm((current) => ({ ...current, ...patch }));
  }

  function updateAttribute(index: number, patch: Partial<DataModelAttribute>) {
    setForm((current) => {
      const attrs = current.attributes.map((attribute, i) =>
        i === index ? { ...attribute, ...patch } : attribute,
      );
      return { ...current, attributes: attrs };
    });
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

  function addAttribute() {
    setForm((current) => ({
      ...current,
      attributes: [
        ...current.attributes,
        {
          name: "",
          display_name: "",
          data_type: "text",
          required: false,
          is_primary_key: false,
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

  function sourceColumnType(name?: string | null): AttrType {
    const column = columns.find((item) => item.column_name === name);
    return normalizePgType(column?.data_type || "text");
  }

  function buildPayload(): DataModelCreate {
    const attributes = form.attributes
      .filter((attribute) => attribute.name.trim())
      .map((attribute) => {
        const name = snake(attribute.name);
        return {
          ...attribute,
          name,
          display_name: emptyToNull(attribute.display_name || "") || titleize(name),
          description: emptyToNull(attribute.description || ""),
          sensitivity: emptyToNull(attribute.sensitivity || ""),
          source_schema: form.type === "B" ? sourceSchema : attribute.source_schema || undefined,
          source_table: form.type === "B" ? sourceTable : attribute.source_table || undefined,
          source_column: form.type === "B" ? attribute.source_column || undefined : attribute.source_column || undefined,
          is_primary_key: attribute.is_primary_key || name === form.primary_key,
        };
      });
    const primary = form.primary_key || attributes.find((attribute) => attribute.is_primary_key)?.name || "";
    return {
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
    payload.attributes.forEach((attribute, index) => {
      if (!/^[a-z][a-z0-9_]*$/.test(attribute.name)) {
        errors.push({ field: `attributes[${index}].name`, message: "Attribute name must be lowercase snake_case." });
      }
      if (SYSTEM_COLS.has(attribute.name)) {
        errors.push({ field: `attributes[${index}].name`, message: "Reserved platform system column name." });
      }
      if (payload.type === "B" && (!attribute.source_schema || !attribute.source_table || !attribute.source_column)) {
        errors.push({ field: `attributes[${index}].source_column`, message: "Type B attributes require source mapping." });
      }
    });
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
    const next = initialForm();
    setForm(next);
    setMode("create");
    if (!schemas.length) {
      try {
        const items = await listSchemas();
        setSchemas(items);
        setSourceSchema(items.includes("mdp_staging") ? "mdp_staging" : items[0] || "");
      } catch (error) {
        setFormErrors(errorMessages(error));
      }
    } else {
      setSourceSchema(schemas.includes("mdp_staging") ? "mdp_staging" : schemas[0] || "");
    }
    setSourceTable("");
    setColumns([]);
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
    const detail = await loadModel(model.id);
    if (!detail) return;
    setSelected(detail);
    const next = formFromModel(detail);
    setForm(next);
    const source = typeBSource(detail);
    setSourceSchema(source.source_schema || (schemas.includes("mdp_staging") ? "mdp_staging" : schemas[0] || ""));
    setSourceTable(source.source_table);
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
      return false;
    }
    if (payload.type !== "B") {
      setFormErrors([]);
      setWarnings([]);
      return true;
    }
    setSaving(true);
    try {
      const result = await validateTypeBMapping(payload);
      setValidation(result);
      setWarnings(result.warnings || []);
      setFormErrors([]);
      return true;
    } catch (error) {
      setValidation(null);
      setWarnings([]);
      setFormErrors(errorMessages(error));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function runUnsavedPreview() {
    const ok = await runValidate();
    if (!ok) return;
    setPreviewLoading(true);
    try {
      const result = await previewTypeBMapping(buildPayload(), 20);
      setPreview(result);
      setWarnings(result.warnings || []);
    } catch (error) {
      setPreview(null);
      setFormErrors(errorMessages(error));
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
            <Button variant="secondary" onClick={openTemplateCreate}>
              <ClipboardList size={16} />
              Create from Template
            </Button>
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
                  <Button variant="secondary" onClick={runValidate} disabled={saving}>Validate Mapping</Button>
                  <Button variant="secondary" onClick={runUnsavedPreview} disabled={saving || previewLoading}>
                    {previewLoading ? "Previewing..." : "Preview Mapping"}
                  </Button>
                </>
              )}
              <Button onClick={saveModel} disabled={saving}>{saving ? "Saving..." : mode === "edit" ? "Save Changes" : "Save Model"}</Button>
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
              onClick={() => patchForm({ type: "A", source_layer: "generated_table", attributes: initialForm().attributes })}
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
            <Input label="Display name" value={form.display_name} onChange={(event) => patchForm({ display_name: event.target.value })} />
            <Input
              label="Name"
              value={form.name}
              disabled={mode === "edit"}
              onChange={(event) => patchForm({ name: snake(event.target.value) })}
              hint="Lowercase snake_case."
            />
            <label className="md:col-span-2 block">
              <span className="mb-1.5 block text-sm font-medium text-neutral-700">Description</span>
              <textarea
                value={form.description}
                onChange={(event) => patchForm({ description: event.target.value })}
                className="min-h-20 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
              />
            </label>
          </div>
        </DrawerSection>

        <DrawerSection
          title="Classification & Namespace"
          subtitle="Namespace helps future catalog, semantic search, IIoT hierarchy, and AI access."
        >
          <div className="grid gap-3 md:grid-cols-3">
            <EditableSelect listKey="domains" label="Domain" value={form.domain} onChange={(v) => patchForm({ domain: v, category: v })} includeEmpty="-" format={titleize} />
            <Input label="Entity type" value={form.entity_type} onChange={(event) => patchForm({ entity_type: snake(event.target.value) })} />
            <EditableSelect listKey="business_processes" label="Business process" value={form.business_process} onChange={(v) => patchForm({ business_process: v })} includeEmpty="-" format={titleize} />
            <Input className="font-mono" label="Namespace" value={form.namespace} onChange={(event) => patchForm({ namespace: event.target.value })} />
            <EditableSelect listKey="source_layers" label="Source layer" value={form.source_layer} onChange={(v) => patchForm({ source_layer: v })} includeEmpty="Infer automatically" format={titleize} />
            <EditableSelect listKey="canonical_statuses" label="Canonical status" value={form.canonical_status} onChange={(v) => patchForm({ canonical_status: v })} includeEmpty="-" format={titleize} />
            <EditableSelect listKey="site_scopes" label="Site scope" value={form.site_scope} onChange={(v) => patchForm({ site_scope: v })} includeEmpty="-" format={titleize} />
          </div>
        </DrawerSection>

        <DrawerSection title="Ownership & Governance">
          <div className="grid gap-3 md:grid-cols-3">
            <EditableSelect listKey="source_systems" label="Source system" value={form.source_system} onChange={(v) => patchForm({ source_system: v })} includeEmpty="-" />
            <EditableSelect listKey="owner_departments" label="Owner department" value={form.owner_department} onChange={(v) => patchForm({ owner_department: v })} includeEmpty="-" />
            <EditableSelect listKey="sensitivity_levels" label="Sensitivity" value={form.sensitivity_level} onChange={(v) => patchForm({ sensitivity_level: v })} format={titleize} />
            <Input label="Refresh policy" value={form.refresh_policy} onChange={(event) => patchForm({ refresh_policy: event.target.value })} />
            <Select label="Status" value={form.status} onChange={(event) => patchForm({ status: event.target.value })}>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </Select>
            <label className="flex items-end gap-2 pb-2 text-sm text-neutral-700">
              <input type="checkbox" checked={form.ai_enabled} onChange={(event) => patchForm({ ai_enabled: event.target.checked })} />
              AI enabled
            </label>
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
        subtitle="Updating attributes does not alter the existing generated physical table in this MVP."
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
        <div className="mb-3 grid gap-3 md:grid-cols-2">
          <Select label="Source schema" value={sourceSchema} onChange={(event) => { setSourceSchema(event.target.value); setSourceTable(""); }}>
            <option value="">- schema -</option>
            {schemas.map((schema) => <option key={schema} value={schema}>{schema}</option>)}
          </Select>
          <Select label="Source table / view" value={sourceTable} onChange={(event) => setSourceTable(event.target.value)}>
            <option value="">- table or view -</option>
            {tables.map((table) => (
              <option key={table.table_name} value={table.table_name}>
                {table.table_name} - {table.table_type}
              </option>
            ))}
          </Select>
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Button size="sm" variant="secondary" onClick={generateAttributes} disabled={!columns.length}>
            Generate Attributes from Source Columns
          </Button>
          <Button size="sm" variant="ghost" onClick={addAttribute}>Add Attribute</Button>
          <span className="text-xs text-neutral-500">Reserved system columns are automatically renamed with source_ prefix.</span>
        </div>
        {renderAttributesTable(true)}
      </DrawerSection>
    );
  }

  function renderAttributesTable(typeB: boolean) {
    return (
      <Table className="table-fixed text-xs">
        <colgroup>
          <col className="w-[170px]" />
          <col className="w-[190px]" />
          <col className="w-[130px]" />
          {typeB && <col className="w-[260px]" />}
          <col className="w-[80px]" />
          <col className="w-[80px]" />
          {!typeB && <col className="w-[220px]" />}
          <col className="w-[82px]" />
        </colgroup>
        <THead>
          <TR>
            <TH>Attribute</TH>
            <TH>Display Name</TH>
            <TH>Data Type</TH>
            {typeB && <TH>Source Column</TH>}
            <TH className="text-center">Required</TH>
            <TH className="text-center">Primary</TH>
            {!typeB && <TH>Description</TH>}
            <TH className="text-center">Actions</TH>
          </TR>
        </THead>
        <TBody>
          {form.attributes.map((attribute, index) => (
            // Key by position only — keying by `attribute.name` (which the first input edits)
            // remounted the row on every keystroke, so the field lost focus after one character.
            <TR key={index}>
              <TD>
                <Input
                  aria-label="Attribute name"
                  value={attribute.name}
                  onChange={(event) => updateAttribute(index, { name: snake(event.target.value) })}
                  className="h-8 font-mono text-xs"
                />
              </TD>
              <TD>
                <Input
                  aria-label="Display name"
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
              {typeB && (
                <TD>
                  <Select
                    aria-label="Source column"
                    value={attribute.source_column || ""}
                    onChange={(event) => {
                      const source_column = event.target.value;
                      updateAttribute(index, {
                        source_column,
                        source_schema: sourceSchema,
                        source_table: sourceTable,
                        data_type: sourceColumnType(source_column),
                      });
                    }}
                    className="h-8 font-mono text-xs"
                  >
                    <option value="">- column -</option>
                    {columns.map((column) => (
                      <option key={column.column_name} value={column.column_name}>
                        {column.column_name}
                      </option>
                    ))}
                  </Select>
                </TD>
              )}
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
                  checked={!!attribute.is_primary_key || form.primary_key === attribute.name}
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
