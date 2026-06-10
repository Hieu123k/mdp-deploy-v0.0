"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Select } from "@/components/ui/Select";
import { Badge } from "@/components/ui/Badge";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import {
  ApiError,
  apiPath,
  listSchemas,
  listTables,
  previewTable,
  type DbTable,
  type DbPreview,
} from "@/lib/api";

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// "All" is capped (a 58M-row table would crash the browser/backend) — it pages this many at a time.
const PREVIEW_ALL_CAP = 10000;
const ROW_OPTIONS: { label: string; value: number }[] = [
  { label: "50", value: 50 },
  { label: "100", value: 100 },
  { label: "500", value: 500 },
  { label: "1000", value: 1000 },
  { label: "All (cap 10k)", value: PREVIEW_ALL_CAP },
];

export default function DbBrowserPage() {
  const [schemas, setSchemas] = useState<string[]>([]);
  const [schema, setSchema] = useState<string>("");
  const [tables, setTables] = useState<DbTable[]>([]);
  const [selectedTable, setSelectedTable] = useState<string>("");
  const [preview, setPreview] = useState<DbPreview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loadingTables, setLoadingTables] = useState(false);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [rowLimit, setRowLimit] = useState(50);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    listSchemas()
      .then((s) => {
        setSchemas(s);
        setSchema(s.includes("mdp_staging") ? "mdp_staging" : s[0] || "");
      })
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, []);

  useEffect(() => {
    if (!schema) return;
    setLoadingTables(true);
    setTables([]);
    setSelectedTable("");
    setPreview(null);
    listTables(schema)
      .then(setTables)
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)))
      .finally(() => setLoadingTables(false));
  }, [schema]);

  async function loadPreview(t: string, limit: number, off: number) {
    setSelectedTable(t);
    setLoadingPreview(true);
    setErr(null);
    try {
      setPreview(await previewTable(schema, t, limit, off));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoadingPreview(false);
    }
  }

  function openPreview(t: string) {
    setOffset(0);
    setPreview(null);
    void loadPreview(t, rowLimit, 0);
  }

  function changeLimit(next: number) {
    setRowLimit(next);
    setOffset(0);
    if (selectedTable) void loadPreview(selectedTable, next, 0);
  }

  function gotoOffset(next: number) {
    const off = Math.max(0, next);
    setOffset(off);
    if (selectedTable) void loadPreview(selectedTable, rowLimit, off);
  }

  return (
    <>
      <PageHeader title="DB Browser" subtitle={`Public API: ${apiPath("/db-browser/schemas")} · Backend route: /db-browser.`} />
      {err && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card>
          <CardHeader title="Schemas & tables" />
          <CardBody className="space-y-3">
            <Select label="Schema" value={schema} onChange={(e) => setSchema(e.target.value)}>
              {schemas.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
            <div className="max-h-[60vh] space-y-1 overflow-y-auto">
              {loadingTables && <p className="text-sm text-neutral-400">Loading...</p>}
              {!loadingTables && tables.length === 0 && (
                <p className="text-sm text-neutral-400">No tables.</p>
              )}
              {tables.map((t) => (
                <button
                  key={t.table_name}
                  onClick={() => openPreview(t.table_name)}
                  className={`flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left hover:bg-neutral-100 ${
                    selectedTable === t.table_name ? "bg-brand/10" : ""
                  }`}
                >
                  <span className="truncate font-mono text-xs text-neutral-700">{t.table_name}</span>
                  <Badge tone={t.table_type === "VIEW" ? "info" : "neutral"}>
                    {t.table_type === "VIEW" ? "view" : "table"}
                  </Badge>
                </button>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title={selectedTable ? `${schema}.${selectedTable}` : "Preview"}
            subtitle={
              preview
                ? `rows ${preview.offset + 1}–${preview.offset + preview.count}` +
                  (preview.total_estimate != null ? ` of ~${preview.total_estimate.toLocaleString()}` : "") +
                  ` · page size ${preview.limit}`
                : undefined
            }
            action={
              selectedTable ? (
                <Select
                  label="Rows"
                  value={String(rowLimit)}
                  onChange={(e) => changeLimit(Number(e.target.value))}
                >
                  {ROW_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </Select>
              ) : undefined
            }
          />
          <CardBody>
            {!selectedTable && <p className="text-sm text-neutral-400">Pick a table to preview rows.</p>}
            {loadingPreview && <p className="text-sm text-neutral-400">Loading preview...</p>}
            {preview &&
              rowLimit === PREVIEW_ALL_CAP &&
              (preview.has_more || (preview.total_estimate ?? 0) > PREVIEW_ALL_CAP) && (
                <p className="mb-2 rounded-md bg-warning/10 px-3 py-2 text-xs text-warning">
                  Showing the first {PREVIEW_ALL_CAP.toLocaleString()} rows — table is larger; use Next/Prev to page through the rest.
                </p>
              )}
            {preview && preview.rows.length === 0 && (
              <p className="text-sm text-neutral-400">(no rows)</p>
            )}
            {preview && preview.rows.length > 0 && (
              <div className="overflow-x-auto">
                <Table>
                  <THead>
                    <TR>
                      {preview.columns.map((c) => (
                        <TH key={c}>{c}</TH>
                      ))}
                    </TR>
                  </THead>
                  <TBody>
                    {preview.rows.map((row, i) => (
                      <TR key={i}>
                        {preview.columns.map((c) => (
                          <TD key={c} className="font-mono text-xs">
                            {fmt(row[c])}
                          </TD>
                        ))}
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
            )}
            {preview && (preview.offset > 0 || preview.has_more) && (
              <div className="mt-3 flex items-center justify-between text-sm">
                <button
                  className="rounded-md border border-neutral-200 px-3 py-1 disabled:opacity-40"
                  disabled={offset === 0 || loadingPreview}
                  onClick={() => gotoOffset(offset - rowLimit)}
                >
                  ← Prev
                </button>
                <span className="text-neutral-500">offset {preview.offset}</span>
                <button
                  className="rounded-md border border-neutral-200 px-3 py-1 disabled:opacity-40"
                  disabled={!preview.has_more || loadingPreview}
                  onClick={() => gotoOffset(offset + rowLimit)}
                >
                  Next →
                </button>
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
