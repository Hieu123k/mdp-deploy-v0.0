"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, Database, Download, ListChecks, Play, RefreshCw, Terminal } from "lucide-react";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import {
  ApiError,
  ora2pgConfigPreview,
  ora2pgDownloadReconciliation,
  ora2pgGetRun,
  ora2pgInfo,
  ora2pgListTables,
  ora2pgRepair,
  ora2pgStart,
  ora2pgStreamRun,
  ora2pgVerify,
  verifyBatch,
  verifyBatchStatus,
  type Ora2pgInfo,
  type Ora2pgProgress,
  type Ora2pgTable,
  type VerifyBatchTable,
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

function batchQueueTone(status?: string): BadgeTone {
  switch (status) {
    case "done":
      return "success";
    case "error":
      return "danger";
    case "running":
      return "info";
    default:
      return "neutral"; // queued
  }
}

function validationTone(status?: string | null): BadgeTone {
  switch (status) {
    case "MATCH":
      return "success";
    case "MISMATCH":
      return "danger";
    case "ESTIMATE":
      return "warning"; // estimate is NOT a (red) mismatch
    default:
      return "neutral"; // PENDING / unknown
  }
}

function verdictLabel(v?: string | null): string {
  switch (v) {
    case "ESTIMATE":
      return "≈ estimate";
    case "PENDING":
      return "Awaiting Verify";
    default:
      return v || "—";
  }
}

function fmtClock(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
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

  // Multi-Verify: selected tables + the active sequential batch's per-table queue status.
  const [verifySel, setVerifySel] = useState<Set<string>>(new Set());
  const [batchStatus, setBatchStatus] = useState<Record<string, VerifyBatchTable>>({});
  const [batchRunning, setBatchRunning] = useState(false);
  const batchPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadTables = useCallback(async () => {
    try {
      const r = await ora2pgListTables();
      setTables(r.tables);
      setSelected((cur) => cur || (r.tables[0]?.table ?? ""));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load tables");
    }
  }, []);

  // Primary Key here is READ-ONLY (prompt 36): the column shows the PK + its source badge so an
  // operator can see the upsert key at a glance, but ALL editing (set / scan / clear) lives in the
  // Streaming tab — PK is the streaming upsert key, so it is configured where streaming is.

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

  const toggleVerifySel = useCallback((table: string) => {
    setVerifySel((cur) => {
      const next = new Set(cur);
      if (next.has(table)) next.delete(table);
      else next.add(table);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setVerifySel((cur) => (cur.size === tables.length ? new Set() : new Set(tables.map((t) => t.table))));
  }, [tables]);

  const stopBatchPoll = useCallback(() => {
    if (batchPollRef.current) {
      clearInterval(batchPollRef.current);
      batchPollRef.current = null;
    }
  }, []);

  const onVerifySelected = useCallback(async () => {
    const sel = Array.from(verifySel);
    if (sel.length === 0) return;
    setError(null);
    setBatchRunning(true);
    setBatchStatus(Object.fromEntries(sel.map((t) => [t, { status: "queued" as const }])));
    try {
      const { batch_id } = await verifyBatch(sel);
      stopBatchPoll();
      let failures = 0;
      batchPollRef.current = setInterval(async () => {
        try {
          const st = await verifyBatchStatus(batch_id);
          failures = 0;
          setBatchStatus(st.tables);
          if (st.finished) {
            stopBatchPoll();
            setBatchRunning(false);
            await loadTables(); // refresh verdicts / counts after the batch completes
          }
        } catch (e) {
          // A 404 is terminal (batch evicted / backend restarted) — stop so the UI never strands.
          if (e instanceof ApiError && e.status === 404) {
            stopBatchPoll();
            setBatchRunning(false);
            setError("Verify batch is no longer available (server restarted?). Re-run if needed.");
            return;
          }
          if (++failures >= 10) {
            stopBatchPoll();
            setBatchRunning(false);
            setError("Lost contact with the verify batch — please retry.");
          }
        }
      }, 1000);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Verify-selected failed");
      setBatchRunning(false);
    }
  }, [verifySel, loadTables, stopBatchPoll]);

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
      if (batchPollRef.current) clearInterval(batchPollRef.current);
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
    // Poll fallback (~2s) — covers SSE drops / proxy buffering. When both the live SSE value and the
    // poll are "running", keep whichever shows MORE rows_done (the freshest), so a stalled SSE never
    // freezes the bar — the poll keeps it moving.
    pollRef.current = setInterval(async () => {
      try {
        const p = await ora2pgGetRun(runId);
        setProgress((cur) => {
          if (!cur || p.status !== "running") return p;
          return (p.rows_done ?? 0) >= (cur.rows_done ?? 0) ? p : cur;
        });
        if (p.status === "success" || p.status === "failed") finishRun();
      } catch {
        /* ignore */
      }
    }, 2000);
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
              requiredMark
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
        </div>

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
              <Button
                variant="secondary"
                size="sm"
                onClick={onVerifySelected}
                disabled={batchRunning || verifySel.size === 0}
                title="Verify the ticked tables — runs in the background, one at a time"
              >
                <ListChecks size={14} />{" "}
                {batchRunning ? "Verifying…" : `Verify selected${verifySel.size ? ` (${verifySel.size})` : ""}`}
              </Button>
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
                <TH>
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    checked={tables.length > 0 && verifySel.size === tables.length}
                    ref={(el) => {
                      if (el) el.indeterminate = verifySel.size > 0 && verifySel.size < tables.length;
                    }}
                    onChange={toggleSelectAll}
                  />
                </TH>
                <TH>Module</TH>
                <TH>Table</TH>
                <TH>Primary Key</TH>
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
                  <TD>
                    <input
                      type="checkbox"
                      aria-label={`Select ${t.table}`}
                      checked={verifySel.has(t.table)}
                      onChange={() => toggleVerifySel(t.table)}
                    />
                  </TD>
                  <TD className="text-neutral-500">{t.module}</TD>
                  <TD className="font-medium text-neutral-800">{t.table}</TD>
                  <TD>
                    {/* READ-ONLY (prompt 36): view the PK + source here; edit it in the Streaming tab. */}
                    <div className="flex items-center gap-1.5">
                      {t.pk_columns && t.pk_columns.length > 0 ? (
                        <span className="font-mono text-xs text-neutral-700 dark:text-neutral-300">
                          {t.pk_columns.join(", ")}
                        </span>
                      ) : (
                        <span className="text-neutral-400" title="No PK — set it in the Streaming tab">—</span>
                      )}
                      {t.pk_source && (
                        <Badge tone={t.pk_source === "manual" ? "info" : t.pk_source === "scanned" ? "success" : "neutral"}>
                          {t.pk_source}
                        </Badge>
                      )}
                      {t.pk_warning && (
                        <span className="cursor-help text-warning" title={t.pk_warning}>
                          ⚠ verify
                        </span>
                      )}
                    </div>
                  </TD>
                  <TD className="text-neutral-500">
                    {t.target_schema}.{t.target_table}
                  </TD>
                  <TD className="whitespace-nowrap">
                    {t.current_rows == null ? (
                      <span className="text-neutral-400" title="not analyzed yet — run Verify for an exact count">?</span>
                    ) : (
                      <>
                        {fmtInt(t.current_rows)}
                        {t.current_rows_estimated && (
                          <span className="ml-1 text-xs text-warning" title="planner estimate (reltuples) — Verify for exact">≈</span>
                        )}
                      </>
                    )}
                  </TD>
                  {/* Source = cached Oracle count (estimate refreshed in background, or exact via Verify) */}
                  <TD
                    title={
                      t.source_count_at
                        ? `as of ${fmtClock(t.source_count_at)} (${t.source_count_mode ?? "?"})${t.source_stale ? " — stale" : ""}`
                        : "no source count yet (enable refresher on .63)"
                    }
                  >
                    {fmtInt(t.source_count)}
                    {t.source_count != null && t.source_count_mode === "estimate" && (
                      <span className="ml-1 text-xs text-warning" title="estimate (Oracle stats)">≈</span>
                    )}
                    {t.source_stale && t.source_count != null && (
                      <span className="ml-1 text-xs text-neutral-400">stale</span>
                    )}
                  </TD>
                  <TD
                    className={
                      t.source_verdict === "MISMATCH" && t.source_missed ? "font-semibold text-danger" : "text-neutral-500"
                    }
                  >
                    {t.source_verdict === "ESTIMATE" ? "≈" : fmtInt(t.source_missed)}
                  </TD>
                  <TD className="text-neutral-500">{fmtDur(t.last_run_duration_sec)}</TD>
                  <TD>
                    <div className="flex flex-col items-start gap-1">
                      {t.source_verdict ? (
                        <Badge tone={validationTone(t.source_verdict)}>{verdictLabel(t.source_verdict)}</Badge>
                      ) : (
                        <span className="text-neutral-400">—</span>
                      )}
                      {batchStatus[t.table] && (
                        <Badge tone={batchQueueTone(batchStatus[t.table].status)}>
                          {batchStatus[t.table].status}
                        </Badge>
                      )}
                    </div>
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
                    <TD colSpan={12} className="bg-brand/5">
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
