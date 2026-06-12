"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import {
  ApiError,
  createDataModel,
  listColumns,
  listDataModels,
  listTables,
  normalizePgType,
  previewTable,
  type DataModel,
  type DataModelAttribute,
  type DbColumn,
  type DbPreview,
} from "@/lib/api";

const SCHEMA = "mdp_staging";
const SYSTEM_COLS = new Set(["id", "raw_payload", "created_at", "updated_at"]);
const attrName = (c: string) => (SYSTEM_COLS.has(c) ? `source_${c}` : c);

export default function JdeTypeBPage() {
  const [tables, setTables] = useState<{ table_name: string; table_type: string }[]>([]);
  const [table, setTable] = useState("");
  const [cols, setCols] = useState<DbColumn[]>([]);
  const [included, setIncluded] = useState<Record<string, boolean>>({});
  const [pkCol, setPkCol] = useState("");
  const [preview, setPreview] = useState<DbPreview | null>(null);
  const [name, setName] = useState("");
  const [typeBModels, setTypeBModels] = useState<DataModel[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reloadModels = useCallback(async () => {
    try {
      const all = await listDataModels();
      setTypeBModels(all.filter((m) => m.type === "B"));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    listTables(SCHEMA)
      .then(setTables)
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
    reloadModels();
  }, [reloadModels]);

  useEffect(() => {
    if (!table) return;
    setCols([]);
    setIncluded({});
    setPkCol("");
    setPreview(null);
    setName("");
    Promise.all([listColumns(SCHEMA, table), previewTable(SCHEMA, table, 10)])
      .then(([c, p]) => {
        setCols(c);
        const inc: Record<string, boolean> = {};
        c.forEach((col) => (inc[col.column_name] = true));
        setIncluded(inc);
        setPkCol(c[0]?.column_name || "");
        setPreview(p);
        setName(table.replace(/^stg_jde_/, "").replace(/^vw_jde_/, "vw_"));
      })
      .catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, [table]);

  async function save() {
    setErr(null);
    setMsg(null);
    const slug = name.trim().toLowerCase();
    if (!/^[a-z][a-z0-9_]*$/.test(slug)) {
      setErr("Model name must be snake_case.");
      return;
    }
    const chosen = cols.filter((c) => included[c.column_name]);
    if (chosen.length === 0 || !pkCol || !included[pkCol]) {
      setErr("Pick columns and a primary key.");
      return;
    }
    const attributes: DataModelAttribute[] = chosen.map((c) => ({
      name: attrName(c.column_name),
      data_type: normalizePgType(c.data_type),
      source_schema: SCHEMA,
      source_table: table,
      source_column: c.column_name,
      is_primary_key: c.column_name === pkCol,
    }));
    setBusy(true);
    try {
      const m = await createDataModel({
        name: slug,
        display_name: slug,
        type: "B",
        category: "procurement",
        primary_key: attrName(pkCol),
        attributes,
      });
      setMsg(`Created Type B model "${m.name}" over ${SCHEMA}.${table} (${attributes.length} attributes).`);
      setTable("");
      await reloadModels();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Demo Data"
        subtitle="Build governed Type B models from mock JDE procurement staging data."
      />
      {err && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
      {msg && <p className="mb-4 rounded-md bg-success/10 px-3 py-2 text-sm text-success">{msg}</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="1 — Pick a staging source" subtitle={SCHEMA} />
          <CardBody className="space-y-3">
            <Select label="Source table / view" requiredMark value={table} onChange={(e) => setTable(e.target.value)}>
              <option value="">— pick —</option>
              {tables.map((t) => (
                <option key={t.table_name} value={t.table_name}>
                  {t.table_name} {t.table_type === "VIEW" ? "(view)" : ""}
                </option>
              ))}
            </Select>
            {cols.length > 0 && (
              <>
                <Input label="New model name (snake_case)" requiredMark value={name} onChange={(e) => setName(e.target.value)} />
                <div className="max-h-56 space-y-1 overflow-y-auto rounded-md border border-neutral-200 p-2">
                  <p className="px-1 text-xs text-neutral-500">Columns (✓ include · ● primary key):</p>
                  {cols.map((c) => (
                    <div key={c.column_name} className="flex items-center gap-2 px-1 text-sm">
                      <input
                        type="checkbox"
                        checked={!!included[c.column_name]}
                        onChange={(e) => setIncluded((p) => ({ ...p, [c.column_name]: e.target.checked }))}
                      />
                      <input type="radio" name="pk" checked={pkCol === c.column_name} onChange={() => setPkCol(c.column_name)} />
                      <span className="flex-1 truncate font-mono text-xs">{c.column_name}</span>
                      <Badge tone="neutral">{normalizePgType(c.data_type)}</Badge>
                    </div>
                  ))}
                </div>
                <Button onClick={save} disabled={busy}>
                  {busy ? "Creating…" : "Generate Type B model"}
                </Button>
              </>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Source preview"
            subtitle={preview ? `${preview.count} rows` : table ? "loading…" : "pick a source"}
          />
          <CardBody>
            {preview && preview.rows.length > 0 ? (
              <div className="max-h-72 overflow-auto">
                <Table>
                  <THead>
                    <TR>
                      {preview.columns.slice(0, 6).map((c) => (
                        <TH key={c}>{c}</TH>
                      ))}
                    </TR>
                  </THead>
                  <TBody>
                    {preview.rows.map((row, i) => (
                      <TR key={i}>
                        {preview.columns.slice(0, 6).map((c) => (
                          <TD key={c} className="font-mono text-xs">
                            {row[c] === null || row[c] === undefined ? "" : String(row[c])}
                          </TD>
                        ))}
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
            ) : (
              <p className="text-sm text-neutral-400">No preview.</p>
            )}
          </CardBody>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader title="Existing Type B models" subtitle={`${typeBModels.length} total`} />
        <CardBody>
          {typeBModels.length === 0 ? (
            <p className="text-sm text-neutral-400">None yet.</p>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Source</TH>
                  <TH>Attributes</TH>
                  <TH>Status</TH>
                </TR>
              </THead>
              <TBody>
                {typeBModels.map((m) => (
                  <TR key={m.id}>
                    <TD className="font-mono text-xs">{m.name}</TD>
                    <TD className="font-mono text-xs">
                      {m.source_schema && m.source_table ? `${m.source_schema}.${m.source_table}` : "—"}
                    </TD>
                    <TD className="tabular-nums">{m.attributes?.length ?? 0}</TD>
                    <TD>
                      <Badge tone={m.status === "active" ? "success" : "neutral"}>{m.status}</Badge>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>
    </>
  );
}
