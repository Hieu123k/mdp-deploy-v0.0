"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Database, Play, RefreshCw, Terminal } from "lucide-react";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import {
  ApiError,
  ora2pgConfigPreview,
  ora2pgGetRun,
  ora2pgInfo,
  ora2pgListTables,
  ora2pgStart,
  ora2pgStreamRun,
  type Ora2pgInfo,
  type Ora2pgProgress,
  type Ora2pgTable,
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

  const loadTables = useCallback(async () => {
    try {
      const r = await ora2pgListTables();
      setTables(r.tables);
      setSelected((cur) => cur || (r.tables[0]?.table ?? ""));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load tables");
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
      const runId = res.run_id;
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
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to start migration");
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
          <h4 className="mb-2 text-sm font-semibold text-neutral-700">Target table status (mdp_staging)</h4>
          <Table>
            <THead>
              <TR>
                <TH>Module</TH>
                <TH>Table</TH>
                <TH>Target</TH>
                <TH>Current rows</TH>
                <TH>Cursor</TH>
                <TH>Last run</TH>
              </TR>
            </THead>
            <TBody>
              {tables.map((t) => (
                <TR key={t.table}>
                  <TD className="text-neutral-500">{t.module}</TD>
                  <TD className="font-medium text-neutral-800">{t.table}</TD>
                  <TD className="text-neutral-500">
                    {t.target_schema}.{t.target_table}
                  </TD>
                  <TD>{fmtInt(t.current_rows)}</TD>
                  <TD className="text-neutral-500">{t.cursor ?? "—"}</TD>
                  <TD>
                    {t.last_run_status ? (
                      <Badge tone={statusTone(t.last_run_status)}>{t.last_run_status}</Badge>
                    ) : (
                      <span className="text-neutral-400">never</span>
                    )}
                  </TD>
                </TR>
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
