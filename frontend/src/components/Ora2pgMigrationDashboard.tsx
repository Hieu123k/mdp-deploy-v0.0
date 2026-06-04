"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, Database, Download, Play, Plus, RefreshCw, Settings, Terminal, Trash2 } from "lucide-react";
import { useAuth } from "@/components/auth/AuthProvider";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import {
  ApiError,
  createReferenceOption,
  deleteReferenceOption,
  getReferenceList,
  ora2pgConfigPreview,
  ora2pgDownloadReconciliation,
  ora2pgGetRun,
  ora2pgInfo,
  ora2pgListTables,
  ora2pgRepair,
  ora2pgStart,
  ora2pgStreamRun,
  ora2pgVerify,
  type Ora2pgInfo,
  type Ora2pgProgress,
  type Ora2pgTable,
  type ReferenceOption,
} from "@/lib/api";

function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("en-US");
}

function fmtDur(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return "—";
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const pad = (x: number) => String(x).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(ss)}` : `${m}:${pad(ss)}`;
}

function statusTone(status?: string): BadgeTone {
  switch (status) {
    case "success":
      return "success";
    case "failed":
      return "danger";
    case "running":
      return "info";
    default:
      return "neutral";
  }
}

function validationTone(status?: string | null): BadgeTone {
  switch (status) {
    case "MATCH":
      return "success";
    case "MISMATCH":
      return "danger";
    case "PENDING":
      return "warning";
    default:
      return "neutral";
  }
}

export function Ora2pgMigrationDashboard() {
  const [info, setInfo] = useState<Ora2pgInfo | null>(null);
  const [tables, setTables] = useState<Ora2pgTable[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [testRows, setTestRows] = useState<string>("0");
  const [progress, setProgress] = useState<Ora2pgProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conf, setConf] = useState<string | null>(null);
  const [loadingConf, setLoadingConf] = useState(false);

  const abortRef = useRef<(() => void) | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [verifying, setVerifying] = useState<string | null>(null);
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [managingTables, setManagingTables] = useState(false);

  const loadTables = useCallback(async () => {
    try {
      const r = await ora2pgListTables();
      setTables(r.tables);
      setSelected((cur) => cur || (r.tables[0]?.table ?? ""));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load tables");
    }
  }, []);

  const onVerify = useCallback(
    async (table: string) => {
      setVerifying(table);
      setError(null);
      try {
        await ora2pgVerify(table); // recount target + write verdict
        await loadTables(); // refresh Source/Missed/Verify columns
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Verify failed");
      } finally {
        setVerifying(null);
      }
    },
    [loadTables],
  );

  const onDownloadLog = useCallback(async (format: "json" | "csv") => {
    try {
      await ora2pgDownloadReconciliation(format);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Download failed");
    }
  }, []);

  useEffect(() => {
    ora2pgInfo().then(setInfo).catch(() => {});
    loadTables();
    return () => {
      abortRef.current?.();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadTables]);

  const stopWatchers = () => {
    abortRef.current?.();
    abortRef.current = null;
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const finishRun = useCallback(() => {
    stopWatchers();
    setBusy(false);
    loadTables();
  }, [loadTables]);

  const watchRun = (runId: string) => {
    stopWatchers();
    // Live SSE stream
    abortRef.current = ora2pgStreamRun(
      runId,
      (p) => {
        setProgress(p);
        if (p.status === "success" || p.status === "failed") finishRun();
      },
      () => {
        /* stream ended; poll fallback below confirms terminal state */
      },
    );
    // Poll fallback (covers SSE drops / proxy buffering)
    pollRef.current = setInterval(async () => {
      try {
        const p = await ora2pgGetRun(runId);
        setProgress((cur) => (cur && cur.status === "running" && p.status === "running" ? cur : p));
        if (p.status === "success" || p.status === "failed") finishRun();
      } catch {
        /* ignore */
      }
    }, 2500);
  };

  const onStart = async () => {
    if (!selected) return;
    setError(null);
    setBusy(true);
    setProgress({
      run_id: "",
      status: "pending",
      rows_done: 0,
      rows_total: null,
      pct: 0,
      rows_per_sec: 0,
      elapsed_sec: 0,
      eta_sec: null,
      message: "Submitting…",
    });
    try {
      const res = await ora2pgStart(selected, Number(testRows) || 0);
      watchRun(res.run_id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to start migration");
      setProgress(null);
      setBusy(false);
    }
  };

  const onRepair = async (t: Ora2pgTable) => {
    setError(null);
    let opts: { mode?: "pk" | "watermark" | "full"; cutoff?: string };
    if (t.pk_columns && t.pk_columns.length > 0) {
      // Phase 2 precise repair — re-pull source, INSERT ON CONFLICT DO NOTHING (no prompt).
      opts = { mode: "pk" };
    } else if (t.ts_col) {
      const entered = window.prompt(
        `Repair ${t.table} by watermark ${t.ts_col} >= cutoff (JDE Julian date, e.g. 124001). ` +
          `Leave blank = full reload.`,
        "",
      );
      if (entered === null) return; // cancelled
      opts = entered.trim() ? { mode: "watermark", cutoff: entered.trim() } : { mode: "full" };
    } else {
      if (!window.confirm(`No PK/watermark known for ${t.table} — full reload?`)) return;
      opts = { mode: "full" };
    }
    setBusy(true);
    setProgress({
      run_id: "",
      status: "pending",
      rows_done: 0,
      rows_total: null,
      pct: 0,
      rows_per_sec: 0,
      elapsed_sec: 0,
      eta_sec: null,
      message: `Submitting ${opts.mode} repair for ${t.table}…`,
    });
    try {
      const res = await ora2pgRepair(t.table, opts);
      setSelected(t.table);
      watchRun(res.run_id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Repair failed");
      setProgress(null);
      setBusy(false);
    }
  };

  const onPreviewConf = async () => {
    if (!selected) return;
    setLoadingConf(true);
    setConf(null);
    try {
      const r = await ora2pgConfigPreview(selected);
      setConf(r.conf_redacted);
    } catch (e) {
      setConf(e instanceof ApiError ? `Error: ${e.message}` : "Failed to load config");
    } finally {
      setLoadingConf(false);
    }
  };

  // Group tables by Module (preserving the catalog/JSON order) for <optgroup> + status rows.
  const moduleGroups = useMemo(() => {
    const order: string[] = [];
    const byModule = new Map<string, Ora2pgTable[]>();
    for (const t of tables) {
      const mod = t.module || "Other";
      if (!byModule.has(mod)) {
        byModule.set(mod, []);
        order.push(mod);
      }
      byModule.get(mod)!.push(t);
    }
    return order.map((mod) => ({ module: mod, items: byModule.get(mod)! }));
  }, [tables]);

  const pct = Math.min(100, Math.max(0, progress?.pct ?? 0));

  // The table whose run is currently live — used to render an inline progress bar in its row.
  const activeTable =
    progress && (progress.status === "running" || progress.status === "pending")
      ? progress.table || selected
      : null;

  return (
    <Card className="mb-4 border-brand/30">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Database size={18} className="text-brand" />
            ora2pg Migration Dashboard
            <Badge tone="info">{info?.version ?? "v0.0"}</Badge>
          </span>
        }
        subtitle="Trigger real ora2pg loads (Oracle JDE → MDP postgres mdp_staging) and watch live progress."
        action={
          <Button variant="secondary" size="sm" onClick={loadTables} disabled={busy}>
            <RefreshCw size={14} /> Refresh
          </Button>
        }
      />
      <CardBody className="space-y-4">
        {info && !info.oracle_configured && (
          <p className="rounded-md bg-warning/10 px-3 py-2 text-xs text-warning ring-1 ring-inset ring-warning/20">
            Oracle source not configured in this environment — triggers will fail gracefully
            (real connect runs where Oracle is reachable). Container: <code>{info.ora2pg_container}</code>.
          </p>
        )}

        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[260px] flex-1">
            <Select
              label="Source table"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              disabled={busy}
            >
              {moduleGroups.map((g) => (
                <optgroup key={g.module} label={g.module}>
                  {g.items.map((t) => (
                    <option key={t.table} value={t.table}>
                      {t.label} · {t.table}
                      {t.ts_col ? ` (ts: ${t.ts_col})` : ""}
                    </option>
                  ))}
                </optgroup>
              ))}
            </Select>
          </div>
          <div className="w-32">
            <Input
              label="Test rows (0=full)"
              type="number"
              min={0}
              value={testRows}
              onChange={(e) => setTestRows(e.target.value)}
              disabled={busy}
            />
          </div>
          <Button onClick={onStart} disabled={busy || !selected}>
            <Play size={16} /> {busy ? "Running…" : "Start migration"}
          </Button>
          <Button variant="ghost" size="md" onClick={onPreviewConf} disabled={loadingConf || !selected}>
            <Terminal size={16} /> ora2pg.conf
          </Button>
          {isAdmin && (
            <Button variant="ghost" size="md" onClick={() => setManagingTables((m) => !m)}>
              <Settings size={16} /> Manage tables
            </Button>
          )}
        </div>

        {isAdmin && managingTables && <ManageOra2pgTables onChanged={loadTables} />}

        {error && (
          <p className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger ring-1 ring-inset ring-danger/20">
            {error}
          </p>
        )}

        {progress && (
          <div className="rounded-md border border-neutral-200 p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-neutral-800">
                {progress.table ?? selected}{" "}
                <span className="text-neutral-400">→ mdp_staging.{progress.target_table ?? ""}</span>
              </span>
              <Badge tone={statusTone(progress.status)}>
                {progress.status}
                {progress.phase && progress.phase !== progress.status ? ` · ${progress.phase}` : ""}
              </Badge>
            </div>
            <div className="h-3 w-full overflow-hidden rounded-full bg-neutral-100">
              <div
                className={
                  "h-full rounded-full transition-all duration-500 " +
                  (progress.status === "failed"
                    ? "bg-danger"
                    : progress.status === "success"
                      ? "bg-success"
                      : "bg-brand")
                }
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
              <Stat label="Rows" value={`${fmtInt(progress.rows_done)} / ${fmtInt(progress.rows_total)}`} />
              <Stat label="Percent" value={`${pct.toFixed(1)}%`} />
              <Stat label="Rows/sec" value={fmtInt(Math.round(progress.rows_per_sec))} />
              <Stat label="Elapsed" value={fmtDur(progress.elapsed_sec)} />
              <Stat label="ETA" value={fmtDur(progress.eta_sec ?? undefined)} />
            </div>
            {progress.message && (
              <p className="mt-3 break-words font-mono text-xs text-neutral-500">{progress.message}</p>
            )}
          </div>
        )}

        {(loadingConf || conf) && (
          <details className="rounded-md border border-neutral-200" open>
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-neutral-700">
              Generated ora2pg.conf (secrets redacted)
            </summary>
            <pre className="overflow-x-auto px-3 pb-3 text-xs leading-relaxed text-neutral-600">
              {loadingConf ? "Loading…" : conf}
            </pre>
          </details>
        )}

        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h4 className="text-sm font-semibold text-neutral-700">
              Target table status &amp; reconciliation (mdp_staging)
            </h4>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={() => onDownloadLog("csv")}>
                <Download size={14} /> Log .csv
              </Button>
              <Button variant="ghost" size="sm" onClick={() => onDownloadLog("json")}>
                <Download size={14} /> Log .json
              </Button>
            </div>
          </div>
          <Table>
            <THead>
              <TR>
                <TH>Module</TH>
                <TH>Table</TH>
                <TH>Target</TH>
                <TH>Current rows</TH>
                <TH>Source</TH>
                <TH>Missed</TH>
                <TH>Duration</TH>
                <TH>Verify</TH>
                <TH>Last run</TH>
                <TH> </TH>
              </TR>
            </THead>
            <TBody>
              {tables.map((t) => (
                <Fragment key={t.table}>
                <TR>
                  <TD className="text-neutral-500">{t.module}</TD>
                  <TD className="font-medium text-neutral-800">
                    {t.table}
                    {t.pk_columns && t.pk_columns.length > 0 && (
                      <span className="ml-1.5" title={`PK: ${t.pk_columns.join(", ")}`}>
                        <Badge tone="info">PK</Badge>
                      </span>
                    )}
                  </TD>
                  <TD className="text-neutral-500">
                    {t.target_schema}.{t.target_table}
                  </TD>
                  <TD>{fmtInt(t.current_rows)}</TD>
                  <TD>{fmtInt(t.last_source_rows)}</TD>
                  <TD
                    className={
                      t.last_missed && t.last_missed > 0 ? "font-semibold text-danger" : "text-neutral-500"
                    }
                  >
                    {fmtInt(t.last_missed)}
                  </TD>
                  <TD className="text-neutral-500">{fmtDur(t.last_run_duration_sec)}</TD>
                  <TD>
                    {t.last_validation_status ? (
                      <Badge tone={validationTone(t.last_validation_status)}>
                        {t.last_validation_status}
                      </Badge>
                    ) : (
                      <span className="text-neutral-400">—</span>
                    )}
                  </TD>
                  <TD>
                    {t.last_run_status ? (
                      <Badge tone={statusTone(t.last_run_status)}>{t.last_run_status}</Badge>
                    ) : (
                      <span className="text-neutral-400">never</span>
                    )}
                  </TD>
                  <TD>
                    <div className="flex items-center gap-1.5">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => onVerify(t.table)}
                        disabled={verifying === t.table}
                      >
                        <CheckCircle2 size={13} /> {verifying === t.table ? "…" : "Verify"}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onRepair(t)}
                        disabled={busy}
                        title={
                          t.pk_columns && t.pk_columns.length > 0
                            ? `PK repair (INSERT ON CONFLICT) on ${t.pk_columns.join(", ")}`
                            : t.ts_col
                              ? `Repair-delta by watermark (${t.ts_col})`
                              : "No PK/watermark — repair falls back to full reload"
                        }
                      >
                        <RefreshCw size={13} /> Repair
                      </Button>
                    </div>
                  </TD>
                </TR>
                {activeTable === t.table && progress && (
                  <TR>
                    <TD colSpan={10} className="bg-brand/5">
                      <div className="flex items-center gap-3 px-1 py-1">
                        <Badge tone={statusTone(progress.status)}>
                          {progress.status}
                          {progress.phase && progress.phase !== progress.status ? ` · ${progress.phase}` : ""}
                        </Badge>
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-neutral-200">
                          <div
                            className="h-full rounded-full bg-brand transition-all duration-500"
                            style={{ width: `${Math.min(100, Math.max(0, progress.pct))}%` }}
                          />
                        </div>
                        <span className="whitespace-nowrap font-mono text-xs text-neutral-600">
                          {fmtInt(progress.rows_done)}/{fmtInt(progress.rows_total)} ·{" "}
                          {Math.min(100, Math.max(0, progress.pct)).toFixed(1)}% ·{" "}
                          {fmtInt(Math.round(progress.rows_per_sec))}/s · {fmtDur(progress.elapsed_sec)} · ETA{" "}
                          {fmtDur(progress.eta_sec ?? undefined)}
                        </span>
                      </div>
                    </TD>
                  </TR>
                )}
                </Fragment>
              ))}
            </TBody>
          </Table>
        </div>
      </CardBody>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-neutral-400">{label}</div>
      <div className="font-mono text-sm font-semibold text-neutral-800">{value}</div>
    </div>
  );
}

// Admin-only inline manager for the ora2pg "Source table" catalog (add / remove tables).
// Persists to /reference/ora2pg_tables, which the dashboard overlays on the JSON catalog.
function ManageOra2pgTables({ onChanged }: { onChanged: () => void | Promise<void> }) {
  const [rows, setRows] = useState<ReferenceOption[]>([]);
  const [view, setView] = useState("");
  const [module, setModule] = useState("");
  const [ts, setTs] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows((await getReferenceList("ora2pg_tables")).options);
    } catch {
      /* ignore */
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const add = async () => {
    const v = view.trim().toUpperCase();
    if (!v) return;
    setError(null);
    try {
      await createReferenceOption("ora2pg_tables", {
        value: v,
        label: `${v.replace(/^V2_PRO_/, "")} — ${module.trim() || "custom"}`,
        extra: { target_table: v.toLowerCase(), module: module.trim() || "Other", ts_col: ts.trim() || null },
      });
      setView("");
      setModule("");
      setTs("");
      await load();
      await onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Add failed");
    }
  };

  const remove = async (id: string, value: string) => {
    if (!window.confirm(`Remove ${value} from the migration catalog?`)) return;
    setError(null);
    try {
      await deleteReferenceOption("ora2pg_tables", id);
      await load();
      await onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Remove failed");
    }
  };

  return (
    <div className="rounded-md border border-neutral-200 bg-neutral-50 p-3 text-xs">
      <div className="mb-2 font-medium text-neutral-700">Manage source tables (admin) · {rows.length} entries</div>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="block">
          <span className="mb-1 block text-neutral-500">Source view</span>
          <input className="h-8 w-44 rounded border border-neutral-300 px-2 font-mono" placeholder="V2_PRO_F9999" value={view} onChange={(e) => setView(e.target.value)} />
        </label>
        <label className="block">
          <span className="mb-1 block text-neutral-500">Module</span>
          <input className="h-8 w-40 rounded border border-neutral-300 px-2" placeholder="Inventory Management" value={module} onChange={(e) => setModule(e.target.value)} />
        </label>
        <label className="block">
          <span className="mb-1 block text-neutral-500">ts_col (optional)</span>
          <input className="h-8 w-28 rounded border border-neutral-300 px-2 font-mono" placeholder="upmj" value={ts} onChange={(e) => setTs(e.target.value)} />
        </label>
        <button type="button" onClick={add} className="inline-flex h-8 items-center gap-1 rounded bg-brand px-2 text-white hover:bg-brand/90">
          <Plus size={13} /> Add table
        </button>
      </div>
      {error && <p className="mb-2 text-danger">{error}</p>}
      <div className="max-h-56 space-y-1 overflow-y-auto">
        {rows.map((o) => (
          <div key={o.id} className="flex items-center gap-2">
            <span className="w-40 truncate font-mono text-neutral-800">{o.value}</span>
            <span className="flex-1 truncate text-neutral-500">
              {(o.extra?.module as string) || "—"}
              {o.extra?.ts_col ? ` · ts:${o.extra.ts_col as string}` : ""}
            </span>
            <button type="button" title="Remove" onClick={() => remove(o.id, o.value)} className="inline-flex h-7 w-7 items-center justify-center rounded border border-neutral-300 text-neutral-600 hover:bg-neutral-100">
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
