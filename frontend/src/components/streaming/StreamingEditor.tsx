"use client";

import { useCallback, useEffect, useState } from "react";
import { Radio } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import { useAuth } from "@/components/auth/AuthProvider";
import {
  ApiError,
  ora2pgClearPrimaryKey,
  ora2pgDiscoverKeysTable,
  ora2pgSetPrimaryKey,
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

  // PK config moved here from Migration Jobs (prompt 36): PK is the streaming upsert key, so it is
  // configured next to the marker. Reuses the auth-gated ora2pg PK endpoints (require pk.edit) — which
  // the backend grants to admin AND data_engineer (DEFAULT_ROLE_PERMISSIONS), so gate the controls on
  // the same parity rather than admin-only (else an empowered data_engineer sees no PK controls).
  const { user } = useAuth();
  const canEditPk = user?.role === "admin" || user?.role === "data_engineer";
  const [pkEdit, setPkEdit] = useState<string | null>(null);
  const [pkDraft, setPkDraft] = useState<string>("");
  const [pkBusy, setPkBusy] = useState<string | null>(null);

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

  const savePk = useCallback(
    async (view: string) => {
      const cols2 = pkDraft.split(",").map((c) => c.trim()).filter(Boolean);
      if (cols2.length === 0) {
        setMsg("Enter at least one PK column (comma-separated)");
        return;
      }
      setPkBusy(view);
      setMsg(null);
      try {
        const r = await ora2pgSetPrimaryKey(view, cols2);
        setMsg(`${view}: ${r.message}${r.index_error ? ` — index: ${r.index_error}` : ""}`);
        setPkEdit(null);
        await load();
      } catch (e) {
        setMsg(e instanceof ApiError ? e.message : "Save PK failed");
      } finally {
        setPkBusy(null);
      }
    },
    [pkDraft, load],
  );

  const clearPk = useCallback(
    async (view: string) => {
      if (
        !window.confirm(
          `Clear the primary key for ${view}?\n\nDROPS the unique index only — ALL ROWS ARE KEPT. ` +
            `With no PK, an incremental sync needs a sequence marker as its key; otherwise the table full-reloads.`,
        )
      )
        return;
      setPkBusy(view);
      setMsg(null);
      try {
        const r = await ora2pgClearPrimaryKey(view);
        setMsg(`${view}: ${r.message}`);
        await load();
      } catch (e) {
        setMsg(e instanceof ApiError ? e.message : "Clear PK failed");
      } finally {
        setPkBusy(null);
      }
    },
    [load],
  );

  const scanPk = useCallback(
    async (view: string) => {
      setPkBusy(view);
      setMsg(null);
      try {
        const r = await ora2pgDiscoverKeysTable(view);
        setMsg(
          r.available
            ? `${view}: PK ${r.persisted ? "updated from Oracle" : "not found"}.`
            : `${view}: ${r.message ?? "Oracle unreachable"}`,
        );
        await load();
      } catch (e) {
        setMsg(e instanceof ApiError ? e.message : "Scan PK failed");
      } finally {
        setPkBusy(null);
      }
    },
    [load],
  );

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
    // Effective mode (prompt 36): full unless there's a marker AND a usable key (PK, or a sequence
    // marker that is its own key). Mirrors the backend clamp so the floor isn't a surprise on reload.
    const hasPk = (t.primary_key_columns?.length ?? 0) > 0;
    const full = !d.ts_col || (!hasPk && d.ts_kind !== "sequence");
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
        subtitle="Configure the marker (watermark) and the upsert key (PK) per table. Incremental needs a key: a PK, or a sequence marker (unique id, e.g. ILUKID) that doubles as its own key. A date marker with no PK can't dedup → full-reload (atomic swap, min 12h)."
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
                  <TH>Primary key / upsert key</TH>
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
                  const pkCols = t.primary_key_columns ?? [];
                  const hasPk = pkCols.length > 0;
                  const seq = d.ts_kind === "sequence";
                  // Effective upsert key under the live draft (prompt 36): PK wins; else a sequence
                  // marker is its own key; a date marker with no PK has no key → full-reload.
                  const keyKind: "primary_key" | "marker" | null = hasPk
                    ? "primary_key"
                    : d.ts_col && seq
                      ? "marker"
                      : null;
                  const full = !d.ts_col || !keyKind;
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
                            {full
                              ? "full reload (≥12h)"
                              : keyKind === "marker"
                                ? `incremental (ts:${d.ts_col}, key=marker)`
                                : `incremental (ts:${d.ts_col}, key=PK)`}
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
                          {d.ts_col && (
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
                          {d.ts_col && !seq && !hasPk && (
                            <span className="text-[10px] text-warning" title="A date marker can't dedup without a PK — set a PK or use a sequence marker for incremental.">
                              date + no PK → full
                            </span>
                          )}
                        </div>
                      </TD>
                      <TD className="min-w-[13rem]">
                        {pkEdit === t.source_view ? (
                          <div className="flex items-center gap-1">
                            <Input
                              value={pkDraft}
                              onChange={(e) => setPkDraft(e.target.value)}
                              className="max-w-[10rem]"
                              placeholder="gldoc, glkco"
                            />
                            <Button size="sm" disabled={pkBusy === t.source_view} onClick={() => void savePk(t.source_view)}>
                              {pkBusy === t.source_view ? "…" : "Save"}
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => setPkEdit(null)} title="Cancel">
                              ✕
                            </Button>
                          </div>
                        ) : (
                          <div className="flex flex-wrap items-center gap-1.5">
                            {hasPk ? (
                              <span className="font-mono text-xs text-neutral-700 dark:text-neutral-300">{pkCols.join(", ")}</span>
                            ) : keyKind === "marker" ? (
                              <span className="font-mono text-xs text-neutral-500" title="No PK — the sequence marker is the upsert key">
                                marker:{d.ts_col}
                              </span>
                            ) : (
                              <span className="text-neutral-400" title="No upsert key — table full-reloads">—</span>
                            )}
                            {canEditPk && (
                              <>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  disabled={pkBusy === t.source_view}
                                  onClick={() => {
                                    setPkEdit(t.source_view);
                                    setPkDraft(pkCols.join(", "));
                                  }}
                                  title="Edit PK (admin)"
                                >
                                  Edit
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  disabled={pkBusy === t.source_view}
                                  onClick={() => void scanPk(t.source_view)}
                                  title="Scan PK from Oracle (discover-keys)"
                                >
                                  {pkBusy === t.source_view ? "…" : "Scan"}
                                </Button>
                                {hasPk && (
                                  <Button
                                    size="sm"
                                    variant="destructive"
                                    disabled={pkBusy === t.source_view}
                                    onClick={() => void clearPk(t.source_view)}
                                    title="Clear PK — drops the unique index (keeps data)"
                                  >
                                    Clear
                                  </Button>
                                )}
                              </>
                            )}
                          </div>
                        )}
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
