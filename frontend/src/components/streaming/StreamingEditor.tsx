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
  streamingRunOnce,
  streamingStatus,
  streamingUpdateConfig,
  type StreamingTable,
} from "@/lib/api";

type StreamDraft = { enabled: boolean; granularity: string; poll_interval_sec: number; lookback_days: number };

/** Format an ISO timestamp as a readable local datetime, e.g. "2026-06-09 11:48:51". */
function fmtRunAt(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** Streaming (watermark-incremental) per-table editor: enable → auto-migrates; "Run every (s)" is
 * the single cadence (min 2s). Edits go to a local draft until Apply. Shows cursor / status /
 * last_error. Used by the /streaming tab (relocated out of Settings). */
export function StreamingEditor() {
  const [streaming, setStreaming] = useState<StreamingTable[] | null>(null);
  const [avail, setAvail] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, StreamDraft>>({});

  const load = useCallback(async () => {
    try {
      const s = await streamingStatus();
      setStreaming(s.tables);
      setDrafts(
        Object.fromEntries(
          s.tables.map((t) => [
            t.source_view,
            { enabled: t.enabled, granularity: t.granularity, poll_interval_sec: t.poll_interval_sec, lookback_days: t.lookback_days },
          ]),
        ),
      );
      setAvail(true);
    } catch {
      setAvail(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const draftOf = (t: StreamingTable): StreamDraft =>
    drafts[t.source_view] ?? {
      enabled: t.enabled,
      granularity: t.granularity,
      poll_interval_sec: t.poll_interval_sec,
      lookback_days: t.lookback_days,
    };
  const setDraft = (view: string, partial: Partial<StreamDraft>) =>
    setDrafts((d) => ({ ...d, [view]: { ...d[view], ...partial } }));
  const isDirty = (t: StreamingTable): boolean => {
    const d = drafts[t.source_view];
    return (
      !!d &&
      (d.enabled !== t.enabled ||
        d.granularity !== t.granularity ||
        d.poll_interval_sec !== t.poll_interval_sec ||
        d.lookback_days !== t.lookback_days)
    );
  };

  const apply = async (t: StreamingTable) => {
    const d = draftOf(t);
    setBusy(t.source_view);
    setMsg(null);
    try {
      await streamingUpdateConfig(t.source_view, {
        enabled: d.enabled,
        granularity: d.granularity,
        poll_interval_sec: d.poll_interval_sec,
        lookback_days: d.lookback_days,
      });
      setMsg(
        `${t.source_view}: applied — ${d.enabled ? "enabled" : "disabled"}, ${d.granularity}, every ${d.poll_interval_sec}s.` +
          (d.enabled ? " The background loop picks it up within one tick." : ""),
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
            <Radio size={16} /> Streaming (watermark-incremental)
          </span>
        }
        subtitle="Enable a table and it auto-migrates. 'Run every' is the single cadence (min 2s). Timestamp unlocks only when the view exposes a time column (UPMT)."
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
                  <TH>Granularity</TH>
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
                      <TD>
                        <Select
                          value={d.granularity}
                          disabled={busy === t.source_view}
                          onChange={(e) => setDraft(t.source_view, { granularity: e.target.value })}
                        >
                          <option value="day">day</option>
                          <option value="timestamp" disabled={!t.has_ts_time_col}>
                            timestamp{t.has_ts_time_col ? "" : " (no time col)"}
                          </option>
                        </Select>
                      </TD>
                      <TD>
                        <Input
                          type="number"
                          min={2}
                          value={d.poll_interval_sec}
                          className="max-w-[6rem]"
                          onChange={(e) => setDraft(t.source_view, { poll_interval_sec: Math.max(2, Number(e.target.value) || 2) })}
                        />
                      </TD>
                      <TD>
                        <Input
                          type="number"
                          min={0}
                          value={d.lookback_days}
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
