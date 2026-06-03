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

export default function DbBrowserPage() {
  const [schemas, setSchemas] = useState<string[]>([]);
  const [schema, setSchema] = useState<string>("");
  const [tables, setTables] = useState<DbTable[]>([]);
  const [selectedTable, setSelectedTable] = useState<string>("");
  const [preview, setPreview] = useState<DbPreview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loadingTables, setLoadingTables] = useState(false);
  const [loadingPreview, setLoadingPreview] = useState(false);

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

  async function openPreview(t: string) {
    setSelectedTable(t);
    setPreview(null);
    setLoadingPreview(true);
    setErr(null);
    try {
      setPreview(await previewTable(schema, t, 50));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoadingPreview(false);
    }
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
            subtitle={preview ? `${preview.count} rows (limit ${preview.limit})` : undefined}
          />
          <CardBody>
            {!selectedTable && <p className="text-sm text-neutral-400">Pick a table to preview rows.</p>}
            {loadingPreview && <p className="text-sm text-neutral-400">Loading preview...</p>}
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
          </CardBody>
        </Card>
      </div>
    </>
  );
}
