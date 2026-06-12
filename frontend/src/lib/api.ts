/**
 * Avenue MDP API client for the FastAPI backend.
 *
 * Local development sets NEXT_PUBLIC_API_URL=http://localhost:8000 and calls
 * backend root routes directly, such as /auth/login.
 *
 * Production leaves NEXT_PUBLIC_API_URL empty so the browser calls same-origin
 * /api/* routes. Caddy strips /api before forwarding to the backend.
 */
const configuredBase = process.env.NEXT_PUBLIC_API_URL?.trim();
export const API_BASE_URL =
  configuredBase && configuredBase !== "undefined"
    ? configuredBase.replace(/\/+$/, "")
    : "/api";

function canonicalBackendPath(path: string): string {
  const withSlash = path.startsWith("/") ? path : `/${path}`;
  if (withSlash === "/api") return "/";
  if (withSlash.startsWith("/api/")) return withSlash.slice(4);
  return withSlash;
}

export function apiPath(path: string): string {
  const backendPath = canonicalBackendPath(path);
  return `${API_BASE_URL}${backendPath}`;
}

// Token storage
const TOKEN_KEY = "mdp_token";
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* ignore */
  }
}
export function clearToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/**
 * Internal/FE routes return FastAPI errors `{detail: string}` or `{detail: [{msg,...}]}`.
 * Integration routes (/inbound, /outbound) return the envelope `{code, message, data}`
 * where validation errors live under `data.errors: [{field, msg}]`. Handle both so the
 * human-readable cause is surfaced on either surface.
 */
function messageFromBody(data: unknown, fallback: string): string {
  if (data && typeof data === "object") {
    const o = data as Record<string, unknown>;
    // FastAPI raw errors (internal/FE routes) — keep first so non-enveloped routes are unchanged.
    if ("detail" in o) {
      const d = o.detail;
      if (typeof d === "string") return d;
      if (Array.isArray(d)) {
        return d
          .map((e) => {
            if (typeof e === "string") return e;
            if (e && typeof e === "object" && "msg" in e)
              return String((e as { msg: unknown }).msg);
            return JSON.stringify(e);
          })
          .join("; ");
      }
    }
    // Envelope validation errors: {code:1005, message, data:{errors:[{field,msg}]}}
    const envData = o.data;
    if (
      envData &&
      typeof envData === "object" &&
      Array.isArray((envData as { errors?: unknown }).errors)
    ) {
      const errs = (envData as { errors: unknown[] }).errors;
      if (errs.length) {
        return errs
          .map((e) => {
            if (e && typeof e === "object") {
              const eo = e as Record<string, unknown>;
              const field = typeof eo.field === "string" ? eo.field : "";
              const msg = String(eo.msg ?? eo.message ?? JSON.stringify(e));
              return field ? `${field}: ${msg}` : msg;
            }
            return String(e);
          })
          .join("; ");
      }
    }
    // Envelope top-level human message: {code, message, data:null}
    if (typeof o.message === "string" && o.message) return o.message;
  }
  return fallback;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    throw new ApiError(
      res.status,
      messageFromBody(data, res.statusText || `HTTP ${res.status}`),
      data,
    );
  }
  return data as T;
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const token = getToken();
  try {
    return await fetch(apiPath(path), {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers || {}),
      },
    });
  } catch {
    throw new ApiError(0, `Cannot reach backend (${API_BASE_URL}).`);
  }
}

// Auth
export type AuthUser = {
  id: string;
  username: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
};

type TokenResponse = { access_token: string; token_type: string };

/** POST /auth/login stores the JWT. Throws ApiError(401) on bad credentials. */
export async function authLogin(username: string, password: string): Promise<void> {
  const r = await req<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  setToken(r.access_token);
}

export const authMe = () => req<AuthUser>("/auth/me");

/** MDP has no logout endpoint (stateless JWT) -> just drop the token. */
export function authLogout(): void {
  clearToken();
}

// Data Models
export type AttrType =
  | "text"
  | "integer"
  | "float"
  | "boolean"
  | "date"
  | "datetime"
  | "json";
export const ATTR_TYPES: AttrType[] = [
  "text",
  "integer",
  "float",
  "boolean",
  "date",
  "datetime",
  "json",
];

export type DataModelAttribute = {
  name: string;
  display_name?: string | null;
  data_type: AttrType;
  required?: boolean;
  description?: string | null;
  sensitivity?: string | null;
  is_primary_key?: boolean;
  source_path?: string | null;
  // Type B mapping (one source table per model):
  source_schema?: string | null;
  source_table?: string | null;
  source_column?: string | null;
};

/** Type B multi-table join (prompt 38). The base table = the primary-key attribute's table; each
 * join brings in a table on its (unique, unless allow_fanout) key. */
export type TypeBJoin = {
  type: "left" | "inner";
  left: { table: string; column: string };
  right: { schema: string; table: string; column: string };
  allow_fanout?: boolean;
};

export type DataModel = {
  id: string;
  name: string;
  display_name: string | null;
  type: "A" | "B";
  relationships?: TypeBJoin[] | null;
  category?: string | null;
  namespace?: string | null;
  entity_type?: string | null;
  business_process?: string | null;
  source_layer?: string | null;
  canonical_status?: string | null;
  site_scope?: string | null;
  description?: string | null;
  business_definition?: string | null;
  owner_department?: string | null;
  source_system?: string | null;
  domain?: string | null;
  primary_key?: string | null;
  sensitivity_level?: string | null;
  ai_enabled?: boolean;
  refresh_policy?: string | null;
  generated_table?: string | null;
  attributes: DataModelAttribute[];
  source_schema?: string | null; // computed (Type B)
  source_table?: string | null; // computed (Type B)
  latest_only?: boolean; // computed (Type B dedup, prompt 50)
  recency_column?: string | null; // computed (Type B dedup, prompt 50)
  status: string;
  created_at: string;
  updated_at: string;
};

export type DataModelTemplate = {
  template_key: string;
  display_name: string;
  description: string;
  category: string;
  domain: string;
  entity_type: string;
  business_process: string;
  source_system: string;
  source_layer: string;
  canonical_status: string;
  site_scope: string;
  model_name: string;
  model_display_name: string;
  model_type: "B";
  primary_key: string;
  source_schema: string;
  source_table: string;
  attributes: DataModelAttribute[];
  related_migration_template_key?: string | null;
  related_migration_target_table?: string | null;
  config?: Record<string, unknown> | null;
};

export type DataModelTemplateCreateResponse = {
  status: string;
  data_model: DataModel;
  warnings: ValidationMessage[];
};

export type DataModelCreate = {
  name: string;
  display_name?: string;
  type: "A" | "B";
  relationships?: TypeBJoin[] | null;
  category?: string | null;
  namespace?: string | null;
  domain?: string | null;
  entity_type?: string | null;
  business_process?: string | null;
  source_layer?: string | null;
  canonical_status?: string | null;
  site_scope?: string | null;
  description?: string | null;
  business_definition?: string | null;
  owner_department?: string | null;
  source_system?: string | null;
  primary_key?: string | null;
  refresh_policy?: string | null;
  sensitivity_level?: string | null;
  ai_enabled?: boolean;
  status?: string | null;
  attributes: DataModelAttribute[];
  // Type B "latest version only" dedup (prompt 50). Omitted => off / default behaviour.
  latest_only?: boolean;
  recency_column?: string | null;
};

export const listDataModels = () => req<DataModel[]>("/data-models");
export const getDataModel = (id: string) => req<DataModel>(`/data-models/${id}`);
export const createDataModel = (body: DataModelCreate) =>
  req<DataModel>("/data-models", { method: "POST", body: JSON.stringify(body) });
export const updateDataModel = (id: string, body: Partial<DataModelCreate>) =>
  req<DataModel>(`/data-models/${id}`, { method: "PUT", body: JSON.stringify(body) });
/** Soft-deactivate (status=inactive); returns the model. */
export const deleteDataModel = (id: string) =>
  req<DataModel>(`/data-models/${id}`, { method: "DELETE" });
/** Admin-only HARD delete of the model record. Does NOT drop the generated mdp_data.dm_* table. */
export const purgeDataModel = (id: string) =>
  req<void>(`/data-models/${id}/record`, { method: "DELETE" });
export const listDataModelTemplates = () =>
  req<DataModelTemplate[]>("/data-model-templates");
export const getDataModelTemplate = (templateKey: string) =>
  req<DataModelTemplate>(`/data-model-templates/${encodeURIComponent(templateKey)}`);
export const createDataModelFromTemplate = (templateKey: string, body: Record<string, unknown>) =>
  req<DataModelTemplateCreateResponse>(
    `/data-model-templates/${encodeURIComponent(templateKey)}/create-model`,
    { method: "POST", body: JSON.stringify(body) },
  );

export type ValidationMessage = { field: string; message: string };
export type TypeBValidationResult = {
  status: string;
  message: string;
  warnings?: ValidationMessage[];
  source_schema?: string;
  source_table?: string;
  mapped_columns?: Array<{
    attribute: string;
    source_column: string;
    source_data_type: string;
    model_data_type: string;
  }>;
};
export type ModelPreview = {
  status?: string;
  model?: string;
  type?: "A" | "B";
  source_schema?: string;
  source_table?: string;
  warnings?: ValidationMessage[];
  count?: number;
  limit?: number;
  offset?: number;
  data?: Record<string, unknown>[];
  records?: Record<string, unknown>[];
};

export const validateTypeBMapping = (body: DataModelCreate) =>
  req<TypeBValidationResult>("/data-models/type-b/validate-mapping", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const previewTypeBMapping = (body: DataModelCreate, limit = 20) =>
  req<ModelPreview>(`/data-models/type-b/preview?limit=${limit}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
export const previewSavedTypeBModel = (id: string, limit = 20) =>
  req<ModelPreview>(`/data-models/${id}/mapped-preview?limit=${limit}`);

// Type B SQL surface (prompt 52). parse-sql NEVER executes the SQL - it only maps a subset SELECT
// to the builder plan; generate-sql renders the plan back to canonical SQL text.
export type TypeBSqlPlan = {
  status: string;
  selected_tables: { schema: string; table: string }[];
  base: { schema: string; table: string };
  relationships: TypeBJoin[];
  attributes: DataModelAttribute[];
  primary_key: string | null;
  latest_only: boolean;
  recency_column: string | null;
  warnings: { field: string; message: string }[];
};
export const parseTypeBSql = (body: {
  sql: string;
  primary_key?: string | null;
  latest_only?: boolean;
  recency_column?: string | null;
}) =>
  req<TypeBSqlPlan>("/data-models/type-b/parse-sql", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const generateTypeBSql = (body: {
  base?: { schema: string; table: string } | null;
  attributes: DataModelAttribute[];
  relationships?: TypeBJoin[] | null;
  primary_key?: string | null;
  latest_only?: boolean;
  recency_column?: string | null;
}) =>
  req<{ sql: string }>("/data-models/type-b/generate-sql", {
    method: "POST",
    body: JSON.stringify(body),
  });

// DB Browser
export type DbTable = { table_name: string; table_type: string };
export type DbColumn = {
  column_name: string;
  data_type: string;
  is_nullable?: string;
  ordinal_position?: number;
};
export type DbPreview = {
  schema: string;
  table: string;
  limit: number;
  offset: number;
  count: number;
  has_more?: boolean;
  total_estimate?: number | null;
  max_limit?: number;
  columns: string[];
  rows: Record<string, unknown>[];
};

export const listSchemas = () =>
  req<{ schemas: string[] }>("/db-browser/schemas").then((r) => r.schemas);
export const listTables = (schema: string) =>
  req<{ schema: string; tables: DbTable[] }>(
    `/db-browser/schemas/${encodeURIComponent(schema)}/tables`,
  ).then((r) => r.tables);
export const listColumns = (schema: string, table: string) =>
  req<{ columns: DbColumn[] }>(
    `/db-browser/schemas/${encodeURIComponent(schema)}/tables/${encodeURIComponent(table)}/columns`,
  ).then((r) => r.columns);
export const previewTable = (schema: string, table: string, limit = 50, offset = 0) =>
  req<DbPreview>(
    `/db-browser/schemas/${encodeURIComponent(schema)}/tables/${encodeURIComponent(table)}/preview?limit=${limit}&offset=${offset}`,
  );

// ---- RBAC: role → permission matrix (admin-only) ----
export type PermissionMatrix = {
  permission_keys: string[];
  admin_only: string[];
  roles: Record<string, Record<string, boolean>>;
};
export const getRolePermissions = () => req<PermissionMatrix>("/roles/permissions");
export const saveRolePermissions = (roles: Record<string, Record<string, boolean>>) =>
  req<PermissionMatrix>("/roles/permissions", { method: "PUT", body: JSON.stringify({ roles }) });

/** Map a raw Postgres data_type -> one of the 7 platform types (mirrors backend). */
export function normalizePgType(raw: string): AttrType {
  const t = (raw || "").toLowerCase().split("(")[0].trim();
  if (["text", "character varying", "varchar", "char", "character", "name", "citext"].includes(t))
    return "text";
  if (["integer", "int", "int4", "bigint", "int8", "smallint", "int2"].includes(t))
    return "integer";
  if (["numeric", "decimal", "double precision", "real", "float", "float4", "float8"].includes(t))
    return "float";
  if (["boolean", "bool"].includes(t)) return "boolean";
  if (t === "date") return "date";
  if (t.startsWith("timestamp")) return "datetime";
  if (["json", "jsonb"].includes(t)) return "json";
  return "text";
}

// Users
export type User = {
  id: string;
  username: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};
export const USER_ROLES = ["admin", "data_engineer", "api_manager", "viewer"];

export const listUsers = () => req<User[]>("/users");
export const createUser = (body: {
  username: string;
  email: string;
  password: string;
  full_name?: string;
  role: string;
  is_active: boolean;
}) => req<User>("/users", { method: "POST", body: JSON.stringify(body) });
export const updateUser = (
  id: string,
  body: { email?: string; full_name?: string; role?: string; is_active?: boolean; password?: string },
) => req<User>(`/users/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteUser = (id: string) =>
  req<void>(`/users/${id}`, { method: "DELETE" });

// API Keys
export const API_DIRECTIONS = ["inbound", "outbound"] as const;
export type ApiKey = {
  id: string;
  name: string;
  description: string | null;
  key_prefix: string;
  source_system: string | null;
  allowed_directions: string[];
  allowed_models: string[] | null;
  is_active: boolean;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
};
export type ApiKeyCreated = ApiKey & { api_key: string };
export const listApiKeys = () => req<ApiKey[]>("/api-keys");
export const createApiKey = (body: {
  name: string;
  description?: string;
  source_system?: string;
  allowed_directions: string[];
  allowed_models?: string[] | null;
}) => req<ApiKeyCreated>("/api-keys", { method: "POST", body: JSON.stringify(body) });
export const updateApiKey = (
  id: string,
  body: { is_active?: boolean; name?: string; allowed_directions?: string[]; allowed_models?: string[] | null },
) => req<ApiKey>(`/api-keys/${id}`, { method: "PUT", body: JSON.stringify(body) });
/** Hard-delete the key (backend de-references its transactions to keep the audit log). 204. */
export const deleteApiKey = (id: string) =>
  req<void>(`/api-keys/${id}`, { method: "DELETE" });

// Connections
export const CONNECTION_TYPES = ["postgresql", "oracle", "sqlserver", "rest_api", "mqtt"] as const;
export type ConnType = (typeof CONNECTION_TYPES)[number];
export type Connection = {
  id: string;
  name: string;
  type: ConnType;
  description: string | null;
  host: string | null;
  port: number | null;
  database_name: string | null;
  username: string | null;
  base_url: string | null;
  mqtt_topic_prefix: string | null;
  config?: Record<string, unknown> | null;
  status: string;
  created_at: string;
  updated_at: string;
  last_test_status: string | null;
  last_test_message: string | null;
  last_test_at: string | null;
};
export type ConnectionTestResult = { id: string; status: string; message: string; tested_at: string };
export const listConnections = () => req<Connection[]>("/connections");
export const createConnection = (body: Record<string, unknown>) =>
  req<Connection>("/connections", { method: "POST", body: JSON.stringify(body) });
export const updateConnection = (id: string, body: Record<string, unknown>) =>
  req<Connection>(`/connections/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteConnection = (id: string) =>
  req<Connection>(`/connections/${id}`, { method: "DELETE" });
export const testConnection = (id: string) =>
  req<ConnectionTestResult>(`/connections/${id}/test`, { method: "POST" });

// Migration Jobs
export const MIGRATION_TOOLS = ["ora2pg", "manual", "external_tool", "native_small_table"] as const;
export const MIGRATION_SOURCE_TYPES = ["oracle", "postgresql", "sqlserver", "external"] as const;
export const MIGRATION_LOAD_MODES = ["full_load", "incremental", "external_bulk", "validation_only"] as const;
export const MIGRATION_RUN_STATUSES = ["pending", "running", "success", "failed", "cancelled"] as const;
export const MIGRATION_INITIAL_LOAD_STRATEGIES = ["full_table", "row_limited", "time_window", "external_defined"] as const;
export const MIGRATION_INCREMENTAL_STRATEGIES = ["none", "greater_than_last_watermark", "greater_equal_last_watermark_with_overlap", "external_defined"] as const;
export const MIGRATION_WATERMARK_TYPES = ["date", "datetime", "number", "jde_julian_date", "text", "unknown"] as const;
export const MIGRATION_VALIDATION_LEVELS = ["none", "basic", "key_integrity", "source_target_count", "checksum_sample", "full_reconciliation"] as const;
export const MIGRATION_RUN_VALIDATION_STATUSES = ["not_validated", "pass", "warning", "fail"] as const;
export type MigrationJob = {
  id: string;
  name: string;
  description: string | null;
  source_system: string | null;
  source_connection_id: string | null;
  source_type: string;
  migration_tool: string;
  source_schema: string | null;
  source_table: string | null;
  target_schema: string;
  target_table: string;
  estimated_rows: number | null;
  estimated_size_gb: number | null;
  primary_key_columns: string[] | null;
  load_mode: string;
  initial_load_strategy: string | null;
  max_rows_per_run: number | null;
  time_window_column: string | null;
  time_window_column_type: string | null;
  time_window_start: string | null;
  time_window_end: string | null;
  incremental_strategy: string | null;
  watermark_column: string | null;
  watermark_column_type: string | null;
  last_successful_watermark: string | null;
  last_successful_run_at: string | null;
  last_run_at: string | null;
  lookback_window_days: number | null;
  lookback_window_minutes: number | null;
  validation_level: string | null;
  status: string;
  config: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  latest_run_status?: string | null;
  latest_target_row_count?: number | null;
};
export type MigrationRun = {
  id: string;
  migration_job_id: string;
  run_type: string;
  trigger_type: string;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  source_row_count: number | null;
  target_row_count: number | null;
  rows_loaded: number | null;
  duration_seconds: number | null;
  run_scope: string | null;
  from_watermark: string | null;
  to_watermark: string | null;
  source_min_watermark: string | null;
  source_max_watermark: string | null;
  target_min_watermark: string | null;
  target_max_watermark: string | null;
  validation_status: string | null;
  log_text: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};
export type MigrationValidation = {
  id: string;
  migration_run_id: string;
  check_name: string;
  source_value: string | null;
  target_value: string | null;
  status: string;
  message: string | null;
  created_at: string;
};
export type TargetValidationResult = {
  status: string;
  validation_status: string;
  migration_run_id: string;
  target_schema: string;
  target_table: string;
  source_row_count: number | null;
  target_row_count: number | null;
  row_count_match: boolean | null;
  validations: MigrationValidation[];
  sample_rows: Record<string, unknown>[];
};
export type MigrationTemplate = {
  template_key: string;
  display_name: string;
  description: string;
  group: string;
  template_type: string;
  source_system: string;
  source_type: string;
  migration_tool: string;
  source_schema_suggestion: string | null;
  source_table: string | null;
  related_source_tables: string[] | null;
  target_schema: string;
  target_table: string;
  primary_key_columns: string[];
  load_mode: string;
  initial_load_strategy: string | null;
  incremental_strategy: string | null;
  watermark_column: string | null;
  watermark_column_type: string | null;
  lookback_window_days: number | null;
  validation_level: string;
  estimated_rows: number | null;
  estimated_size_gb: number | null;
  config: Record<string, unknown> | null;
};
export const listMigrationJobs = () => req<MigrationJob[]>("/migration-jobs");
export const getMigrationJob = (id: string) => req<MigrationJob>(`/migration-jobs/${id}`);
export const createMigrationJob = (body: Record<string, unknown>) =>
  req<MigrationJob>("/migration-jobs", { method: "POST", body: JSON.stringify(body) });
export const updateMigrationJob = (id: string, body: Record<string, unknown>) =>
  req<MigrationJob>(`/migration-jobs/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteMigrationJob = (id: string) =>
  req<MigrationJob>(`/migration-jobs/${id}`, { method: "DELETE" });
export const listMigrationRuns = (jobId: string) =>
  req<MigrationRun[]>(`/migration-jobs/${jobId}/runs`);
export const createMigrationRun = (jobId: string, body: Record<string, unknown>) =>
  req<MigrationRun>(`/migration-jobs/${jobId}/runs`, { method: "POST", body: JSON.stringify(body) });
export const getMigrationRun = (id: string) => req<MigrationRun>(`/migration-runs/${id}`);
export const updateMigrationRun = (id: string, body: Record<string, unknown>) =>
  req<MigrationRun>(`/migration-runs/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const validateMigrationTarget = (runId: string) =>
  req<TargetValidationResult>(`/migration-runs/${runId}/validate-target`, { method: "POST" });
export const listMigrationTemplates = () => req<MigrationTemplate[]>("/migration-templates");
export const getMigrationTemplate = (templateKey: string) =>
  req<MigrationTemplate>(`/migration-templates/${encodeURIComponent(templateKey)}`);
export const createMigrationJobFromTemplate = (templateKey: string, body: Record<string, unknown>) =>
  req<MigrationJob>(`/migration-templates/${encodeURIComponent(templateKey)}/create-job`, {
    method: "POST",
    body: JSON.stringify(body),
  });

// Transactions
export type Transaction = {
  id: string;
  direction: string;
  protocol: string;
  data_model_id: string | null;
  endpoint: string | null;
  status: string;
  auth_type: string | null;
  source_system: string | null;
  error_message: string | null;
  created_at: string;
};
export const listTransactions = (
  params: { limit?: number; direction?: string; status?: string } = {},
) => {
  const q = new URLSearchParams();
  q.set("limit", String(params.limit ?? 100));
  if (params.direction) q.set("direction", params.direction);
  if (params.status) q.set("status", params.status);
  return req<Transaction[]>(`/transactions?${q.toString()}`);
};

// All-time transaction counts grouped by status (no 500 cap) - powers the Dashboard cards.
export type TransactionStats = { total: number; by_status: Record<string, number> };
export const getTransactionStats = () => req<TransactionStats>("/transactions/stats");

// Inbound / Outbound — these integration routes return the {code,message,data} envelope (prompt 41).
// We UNWRAP `data` here so the FE consumers keep the same raw shape (non-regression).
export type ApiEnvelope<T> = { code: number; message: string; data: T };
export type InboundResult = { status: string; model: string; record_id: string; message: string };
export const inbound = (model: string, payload: Record<string, unknown>) =>
  req<ApiEnvelope<InboundResult>>(`/inbound/${encodeURIComponent(model)}`, {
    method: "POST",
    body: JSON.stringify(payload),
  }).then((e) => e.data);
export const outbound = (model: string, params: { limit?: number; include_meta?: boolean } = {}) => {
  const q = new URLSearchParams();
  q.set("limit", String(params.limit ?? 50));
  if (params.include_meta) q.set("include_meta", "true");
  return req<ApiEnvelope<ModelPreview>>(
    `/outbound/${encodeURIComponent(model)}?${q.toString()}`,
  ).then((e) => e.data);
};
export const outboundByKey = (model: string, key: string) =>
  req<ApiEnvelope<{ status?: string; model?: string; type?: "A" | "B"; key?: string; data?: Record<string, unknown> }>>(
    `/outbound/${encodeURIComponent(model)}/${encodeURIComponent(key)}`,
  ).then((e) => e.data);

// Admin demo
export const procurementStagingSummary = () =>
  req<{ tables?: Record<string, number> } & Record<string, unknown>>(
    "/admin/demo/procurement-staging-summary",
  );
export const seedProcurementStagingData = () =>
  req<{ status: string; message: string; tables: Record<string, number> }>(
    "/admin/demo/seed-procurement-staging",
    { method: "POST" },
  );

export type JdeWorkflowSubjectStatus = {
  migration_job_exists: boolean;
  migration_job_id: string | null;
  migration_job_status: string | null;
  latest_run_id: string | null;
  latest_run_status: string | null;
  target_validation_status: string | null;
  target_row_count: number | null;
  data_model_exists: boolean;
  data_model_id: string | null;
  data_model_status: string | null;
  outbound_api_available: boolean;
  source_schema: string;
  source_table: string;
  outbound_sample_key: string;
};
export type JdeWorkflowStatus = {
  status: string;
  staging: {
    procurement_staging_seeded: boolean;
    tables: Record<string, number>;
  };
  supplier: JdeWorkflowSubjectStatus;
  purchase_order_summary: JdeWorkflowSubjectStatus;
};
export const getJdeWorkflowStatus = () =>
  req<JdeWorkflowStatus>("/demo/jde-procurement/workflow-status");

// ---- Migration Dashboard v0.0 (ora2pg control + live progress) ----
export type Ora2pgInfo = {
  version: string;
  ora2pg_container: string;
  target_schema: string;
  oracle_configured: boolean;
  table_count: number;
};
export type Ora2pgTable = {
  table: string;
  ts_col: string | null;
  label: string;
  module: string;
  target_table: string;
  target_schema: string;
  current_rows: number | null;
  current_rows_estimated?: boolean | null;
  cursor: string | null;
  last_run_id: string | null;
  last_run_status: string | null;
  last_run_at: string | null;
  last_source_rows: number | null;
  last_target_rows: number | null;
  last_missed: number | null;
  last_validation_status: string | null;
  last_run_duration_sec: number | null;
  pk_columns: string[] | null;
  pk_source: string | null; // reference | manual | scanned
  pk_warning: string | null; // name-mismatch / surrogate UKID / column not in view
  // Source-count cache (background estimate + on-demand exact); populated on page load.
  source_count: number | null;
  source_count_mode: string | null; // estimate | exact
  source_count_at: string | null;
  source_approximate: boolean | null;
  source_stale: boolean;
  source_missed: number | null;
  source_verdict: string | null; // MATCH | MISMATCH | ESTIMATE | PENDING
};
export type Ora2pgVerifyResult = {
  table: string;
  target_table: string;
  source_rows: number | null;
  target_rows: number | null;
  missed: number | null;
  validation_status: string;
  source_available: boolean;
  last_run_id: string | null;
  message: string;
};
export type Ora2pgStatusItem = {
  table: string;
  module: string;
  target: string;
  current_rows: number | null;
  cursor: string | null;
  last_run_status: string | null;
  last_run_rows: number | null;
  last_run_at: string | null;
  last_run_duration_sec: number | null;
};
export type Ora2pgProgress = {
  run_id: string;
  table?: string;
  target_table?: string;
  status: string; // pending | running | success | failed
  phase?: string;
  rows_done: number;
  rows_total: number | null;
  pct: number;
  rows_per_sec: number;
  elapsed_sec: number;
  eta_sec: number | null;
  message?: string;
  started_at?: string | null;
  updated_at?: string | null;
};
export const ora2pgInfo = () => req<Ora2pgInfo>("/ora2pg/info");
export const ora2pgListTables = () =>
  req<{ version: string; tables: Ora2pgTable[] }>("/ora2pg/tables");
export const ora2pgConfigPreview = (table: string) =>
  req<{ table: string; target: string; conf_redacted: string }>(
    `/ora2pg/tables/${encodeURIComponent(table)}/config-preview`,
  );
export const ora2pgStart = (table: string, testRows = 0) =>
  req<{ run_id: string; table: string; status: string; stream_url?: string; message?: string }>(
    `/ora2pg/tables/${encodeURIComponent(table)}/start?test_rows=${testRows}`,
    { method: "POST" },
  );
export const ora2pgGetRun = (runId: string) =>
  req<Ora2pgProgress>(`/ora2pg/runs/${encodeURIComponent(runId)}`);
export const ora2pgStatus = () =>
  req<{ version: string; schema: string; tables: Ora2pgStatusItem[] }>("/ora2pg/status");
export const ora2pgVerify = (table: string) =>
  req<Ora2pgVerifyResult>(
    `/ora2pg/tables/${encodeURIComponent(table)}/verify`,
    { method: "POST" },
  );
export const ora2pgRepair = (
  table: string,
  opts: { mode?: "pk" | "watermark" | "full"; cutoff?: string } = {},
) => {
  const qs = new URLSearchParams();
  if (opts.mode) qs.set("mode", opts.mode);
  if (opts.cutoff) qs.set("cutoff", opts.cutoff);
  const q = qs.toString();
  return req<{ run_id: string; table: string; mode: string; status: string; stream_url?: string; message?: string }>(
    `/ora2pg/tables/${encodeURIComponent(table)}/repair${q ? `?${q}` : ""}`,
    { method: "POST" },
  );
};
export type Ora2pgKeyItem = {
  table: string;
  module: string;
  target_table: string;
  pk_columns: string[] | null;
  repair_mode: string;
};
export const ora2pgKeys = () =>
  req<{ version: string; with_pk: number; total: number; tables: Ora2pgKeyItem[] }>("/ora2pg/keys");
export const ora2pgDiscoverKeys = () =>
  req<{ available: boolean; message: string | null; persisted: number; results: unknown[] }>(
    "/ora2pg/discover-keys",
    { method: "POST" },
  );
export const ora2pgDiscoverKeysTable = (table: string) =>
  req<{ available: boolean; message: string | null; persisted: number; results: unknown[] }>(
    `/ora2pg/discover-keys?table=${encodeURIComponent(table)}`,
    { method: "POST" },
  );
export type Ora2pgPkResult = {
  table: string;
  pk_columns: string[];
  index_rebuilt: boolean;
  index_error: string | null;
  message: string;
};
export const ora2pgSetPrimaryKey = (table: string, pk_columns: string[]) =>
  req<Ora2pgPkResult>(`/ora2pg/tables/${encodeURIComponent(table)}/primary-key`, {
    method: "PUT",
    body: JSON.stringify({ pk_columns }),
  });
/** Clear PK (admin/pk.edit): empties pk + DROPs the unique index. Keeps all data. → streaming full-reload. */
export const ora2pgClearPrimaryKey = (table: string) =>
  req<{ table: string; index_dropped: boolean; message: string }>(
    `/ora2pg/tables/${encodeURIComponent(table)}/primary-key`,
    { method: "DELETE" },
  );

/** Download the reconciliation log (json|csv) via an authed fetch + blob. */
export async function ora2pgDownloadReconciliation(format: "json" | "csv"): Promise<void> {
  const res = await apiFetch(`/ora2pg/reconciliation?format=${format}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `reconciliation.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * Open the SSE progress stream for a run (auth via Bearer header, so we read the
 * body stream manually instead of EventSource). Calls onEvent for each progress
 * snapshot. Returns an abort function.
 */
export function ora2pgStreamRun(
  runId: string,
  onEvent: (p: Ora2pgProgress) => void,
  onDone?: () => void,
): () => void {
  const ctrl = new AbortController();
  (async () => {
    try {
      const res = await apiFetch(`/ora2pg/runs/${encodeURIComponent(runId)}/stream`, {
        signal: ctrl.signal,
        headers: { Accept: "text/event-stream" },
      });
      if (!res.body) return;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, nl);
          buf = buf.slice(nl + 2);
          for (const line of frame.split("\n")) {
            if (line.startsWith("data:")) {
              try {
                onEvent(JSON.parse(line.slice(5).trim()) as Ora2pgProgress);
              } catch {
                /* ignore malformed frame */
              }
            }
          }
        }
      }
    } catch {
      /* aborted or network error -> caller polls as fallback */
    } finally {
      onDone?.();
    }
  })();
  return () => ctrl.abort();
}

// --- User preferences (theme + per-user nav/RBAC tab config) --------------------------------

export type NavOverride = { visible?: boolean; label?: string; order?: number };
export type NavConfig = Record<string, NavOverride>;
export type Preferences = { user_id?: string; theme: string; nav_config: NavConfig };

export const getMyPreferences = () => req<Preferences>("/preferences/me");
export const updateMyPreferences = (body: { theme?: string; nav_config?: NavConfig }) =>
  req<Preferences>("/preferences/me", { method: "PUT", body: JSON.stringify(body) });

export type UserPreferenceRow = {
  user_id: string;
  username: string;
  role: string;
  is_active?: boolean;
  theme: string;
  nav_config: NavConfig;
};
export const listUserPreferences = () => req<{ users: UserPreferenceRow[] }>("/preferences/users");
export const getUserPreferences = (userId: string) =>
  req<UserPreferenceRow>(`/preferences/users/${userId}`);
export const setUserPreferences = (
  userId: string,
  body: { theme?: string; nav_config?: NavConfig },
) => req<UserPreferenceRow>(`/preferences/users/${userId}`, { method: "PUT", body: JSON.stringify(body) });

// --- Multi-Verify (sequential queue) --------------------------------------------------------

export type VerifyBatchTable = {
  status: "queued" | "running" | "done" | "error";
  verdict?: string | null;
  target_rows?: number | null;
  source_count?: number | null;
  missed?: number | null;
  error?: string | null;
};
export type VerifyBatchStatus = {
  batch_id: string;
  order: string[];
  tables: Record<string, VerifyBatchTable>;
  total: number;
  completed: number;
  finished: boolean;
};

export const verifyBatch = (tables: string[]) =>
  req<{ batch_id: string; queued: string[]; status_url: string }>("/ora2pg/verify-batch", {
    method: "POST",
    body: JSON.stringify({ tables }),
  });
export const verifyBatchStatus = (batchId: string) =>
  req<VerifyBatchStatus>(`/ora2pg/verify-batch/${batchId}`);

// --- Streaming config (consume prompt-27 API; degrades to 404 if backend lacks it) ----------

export type StreamingTable = {
  source_view: string;
  target_table: string;
  label: string;
  enabled: boolean;
  ts_col: string | null;
  ts_time_col: string | null;
  ts_kind: string | null; // date | sequence
  granularity: string;
  poll_interval_sec: number;
  lookback_days: number;
  primary_key_columns: string[] | null;
  effective_upsert_key: string[] | null; // PK, or the sequence marker itself, or null (full-reload)
  upsert_key_kind?: string | null; // primary_key | marker | null
  mode?: string; // incremental | full
  min_interval_sec?: number;
  last_watermark: string | null;
  last_watermark_time: string | null;
  last_run_at: string | null;
  last_rows_added: number | null;
  last_status: string | null;
  last_error: string | null;
  has_ts_time_col: boolean;
};
export type StreamingStatus = {
  loop: { enabled: boolean; running: boolean };
  tables: StreamingTable[];
};
export type StreamingConfigUpdate = Partial<{
  enabled: boolean;
  granularity: string;
  poll_interval_sec: number;
  lookback_days: number;
  ts_col: string;
  ts_time_col: string;
  ts_kind: string;
}>;
export type StreamingProbe = { table: string; columns: string[]; upmt_candidates: string[]; error: string | null };
export const streamingProbe = (table: string) =>
  req<StreamingProbe>(`/streaming/probe/${encodeURIComponent(table)}`);
export type StreamingRunResult = {
  ok: boolean;
  rows_added: number | null;
  cursor: string | null;
  error: string | null;
};

export const streamingStatus = () => req<StreamingStatus>("/streaming/status");
export const streamingUpdateConfig = (table: string, body: StreamingConfigUpdate) =>
  req<StreamingTable>(`/streaming/config/${encodeURIComponent(table)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
export const streamingRunOnce = (table: string) =>
  req<StreamingRunResult>(`/streaming/run-once/${encodeURIComponent(table)}`, { method: "POST" });
