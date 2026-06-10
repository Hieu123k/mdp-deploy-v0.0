"use client";

import { useCallback, useEffect, useState } from "react";
import { Radio } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import {
  ApiError,
  streamingProbe,
  streamingRunOnce,
  streamingStatus,
  streamingUpdateConfig,
  type StreamingTable,
} from "@/lib/api";

const FULL_RELOAD_MIN = 43200; // 12h — backend hard floor for full-reload tables

type StreamDraft = {
  enabled: boolean;
  ts_col: string; // "" → full reload
  ts_kind: string; // date | sequence
  granularity: string;
  poll_interval_sec: number;
  lookback_days: number;
};

/** Format an ISO timestamp as a readable local datetime, e.g. "2026-06-09 11:48:51". */
function fmtRunAt(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

const draftFrom = (t: StreamingTable): StreamDraft => ({
  enabled: t.enabled,
  ts_col: t.ts_col ?? "",
  ts_kind: t.ts_kind ?? "date",
  granularity: t.granularity,
  poll_interval_sec: t.poll_interval_sec,
  lookback_days: t.lookback_days,
});

/** Streaming per-table editor (2-case, prompt 35): pick a watermark column (dropdown of the view's
 * columns) for incremental, or "(none) → full reload" (atomic swap, ≥12h). Edits are a local draft
 * until Apply. */
export function StreamingEditor() {
  const [streaming, setStreaming] = useState<StreamingTable[] | null>(null);
  const [avail, setAvail] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, StreamDraft>>({});
  const [cols, setCols] = useState<Record<string, string[] | "loading">>({});

  const load = useCallback(async () => {
    try {
      const s = await streamingStatus();
      setStreaming(s.tables);
      setDrafts(Object.fromEntries(s.tables.map((t) => [t.source_view, draftFrom(t)])));
      setAvail(true);
    } catch {
      setAvail(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const probeCols = useCallback(async (view: string) => {
    setCols((c) => (c[view] ? c : { ...c, [view]: "loading" }));
    try {
      const r = await streamingProbe(view);
      setCols((c) => ({ ...c, [view]: r.columns ?? [] }));
    } catch {
      setCols((c) => ({ ...c, [view]: [] }));
    }
  }, []);

  const draftOf = (t: StreamingTable): StreamDraft => drafts[t.source_view] ?? draftFrom(t);
  const setDraft = (view: string, partial: Partial<StreamDraft>) =>
    setDrafts((d) => ({ ...d, [view]: { ...(d[view] ?? {}), ...partial } as StreamDraft }));
  const isDirty = (t: StreamingTable): boolean => {
    const d = drafts[t.source_view];
    const o = draftFrom(t);
    return !!d && (Object.keys(o) as (keyof StreamDraft)[]).some((k) => d[k] !== o[k]);
  };

  const apply = async (t: StreamingTable) => {
    const d = draftOf(t);
    const full = !d.ts_col;
    setBusy(t.source_view);
    setMsg(null);
    try {
      await streamingUpdateConfig(t.source_view, {
        enabled: d.enabled,
        ts_col: d.ts_col, // "" clears → full reload
        ts_kind: d.ts_kind,
        granularity: d.granularity,
        poll_interval_sec: full ? Math.max(FULL_RELOAD_MIN, d.poll_interval_sec) : d.poll_interval_sec,
        lookback_days: d.lookback_days,
      });
      setMsg(
        `${t.source_view}: applied — ${d.enabled ? "enabled" : "disabled"}, ` +
          (full ? `FULL reload (≥12h)` : `incremental (ts:${d.ts_col}, ${d.ts_kind})`) + ".",
      );
      await load();
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : "Apply failed");
    } finally {
      setBusy(null);
    }
  };

  const runOnce = async (t: StreamingTable) => {
    setBusy(t.source_view);
    setMsg(null);
    try {
      const r = await streamingRunOnce(t.source_view);
      setMsg(r.ok ? `${t.source_view}: +${r.rows_added ?? 0} (cursor ${r.cursor ?? "—"})` : `${t.source_view}: ${r.error}`);
      await load();
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : "Run-once failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <Radio size={16} /> Streaming (2-case: incremental / full-reload)
          </span>
        }
        subtitle="Pick a watermark column for incremental sync, or '(none)' for full-reload (atomic swap, min 12h). Sequence = monotonic id (e.g. ILUKID); date = Julian UPMJ."
        action={
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            Refresh
          </Button>
        }
      />
      <CardBody>
        {!avail ? (
          <p className="text-sm text-neutral-500">Streaming API not available on this backend.</p>
        ) : (
          <>
            {msg ? <p className="mb-2 text-sm text-neutral-600 dark:text-neutral-300">{msg}</p> : null}
            <Table>
              <THead>
                <TR>
                  <TH>Enabled</TH>
                  <TH>Table</TH>
                  <TH>Watermark / mode</TH>
                  <TH>Run every (s)</TH>
                  <TH>Lookback (d)</TH>
                  <TH>Cursor / status</TH>
                  <TH>Last run</TH>
                  <TH> </TH>
                </TR>
              </THead>
              <TBody>
                {(streaming ?? []).map((t) => {
                  const d = draftOf(t);
                  const dirty = isDirty(t);
                  const full = !d.ts_col;
                  const opts = cols[t.source_view];
                  const colList = Array.isArray(opts) ? opts : [];
                  // keep the currently-selected col visible even before a probe loads
                  const colOptions = Array.from(new Set([...(d.ts_col ? [d.ts_col] : []), ...colList]));
                  const minInt = full ? FULL_RELOAD_MIN : 2;
                  return (
                    <TR key={t.source_view}>
                      <TD>
                        <input
                          type="checkbox"
                          aria-label={`Enable ${t.source_view}`}
                          checked={d.enabled}
                          disabled={busy === t.source_view}
                          onChange={(e) => setDraft(t.source_view, { enabled: e.target.checked })}
                        />
                      </TD>
                      <TD className="font-medium">
                        {t.source_view}
                        {dirty ? <span className="ml-1.5 text-xs text-warning">unsaved</span> : null}
                      </TD>
                      <TD className="min-w-[15rem]">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge tone={full ? "warning" : "success"}>
                            {full ? "full reload (≥12h)" : `incremental (ts:${d.ts_col})`}
                          </Badge>
                          <Select
                            aria-label={`Watermark column for ${t.source_view}`}
                            value={d.ts_col}
                            disabled={busy === t.source_view}
                            onMouseDown={() => void probeCols(t.source_view)}
                            onChange={(e) => setDraft(t.source_view, { ts_col: e.target.value })}
                            className="max-w-[10rem]"
                          >
                            <option value="">(none) → full reload</option>
                            {opts === "loading" && <option disabled>loading columns…</option>}
                            {colOptions.map((c) => (
                              <option key={c} value={c}>
                                {c}
                              </option>
                            ))}
                          </Select>
                          {!full && (
                            <Select
                              aria-label={`Watermark kind for ${t.source_view}`}
                              value={d.ts_kind}
                              disabled={busy === t.source_view}
                              onChange={(e) => setDraft(t.source_view, { ts_kind: e.target.value })}
                              className="max-w-[7rem]"
                            >
                              <option value="date">date (Julian)</option>
                              <option value="sequence">sequence (id)</option>
                            </Select>
                          )}
                        </div>
                      </TD>
                      <TD>
                        <Input
                          type="number"
                          min={minInt}
                          value={d.poll_interval_sec}
                          className="max-w-[7rem]"
                          onChange={(e) =>
                            setDraft(t.source_view, { poll_interval_sec: Math.max(minInt, Number(e.target.value) || minInt) })
                          }
                        />
                        {full && <div className="text-[10px] text-neutral-400">min 12h (43200)</div>}
                      </TD>
                      <TD>
                        <Input
                          type="number"
                          min={0}
                          value={d.lookback_days}
                          disabled={full || d.ts_kind === "sequence"}
                          className="max-w-[5rem]"
                          onChange={(e) => setDraft(t.source_view, { lookback_days: Math.max(0, Number(e.target.value) || 0) })}
                        />
                      </TD>
                      <TD className="max-w-[16rem]">
                        <div className="font-mono text-xs text-neutral-500">
                          {t.last_watermark ?? "—"}
                          {t.last_watermark_time ? `:${t.last_watermark_time}` : ""}{" "}
                          {t.last_status ? (
                            <Badge tone={t.last_status === "ok" ? "success" : "danger"}>{t.last_status}</Badge>
                          ) : null}
                        </div>
                        {t.last_status === "error" && t.last_error ? (
                          <div className="mt-0.5 break-words text-xs text-danger" title={t.last_error}>
                            {t.last_error.slice(0, 120)}
                          </div>
                        ) : null}
                      </TD>
                      <TD className="whitespace-nowrap font-mono text-xs text-neutral-500">
                        {fmtRunAt(t.last_run_at)}
                        {t.last_rows_added != null ? <span className="ml-1 text-neutral-400">(+{t.last_rows_added})</span> : null}
                      </TD>
                      <TD>
                        <div className="flex items-center gap-1.5">
                          <Button size="sm" disabled={busy === t.source_view || !dirty} onClick={() => void apply(t)}>
                            {busy === t.source_view ? "Applying…" : "Apply"}
                          </Button>
                          <Button variant="secondary" size="sm" disabled={busy === t.source_view} onClick={() => void runOnce(t)}>
                            Run once
                          </Button>
                        </div>
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
          </>
        )}
      </CardBody>
    </Card>
  );
}
