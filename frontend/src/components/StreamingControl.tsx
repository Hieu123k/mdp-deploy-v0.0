"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Radio } from "lucide-react";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Select } from "@/components/ui/Select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import {
  ApiError,
  streamingRunOnce,
  streamingStatus,
  streamingUpdateConfig,
  type StreamingStatus,
  type StreamingTable,
} from "@/lib/api";

/**
 * Minimal streaming-watermark control (per the streaming feature build). Enough to enable/disable
 * a table, pick day/timestamp granularity, see the cursor, and run one cycle on demand. A polished
 * Settings tab is a later prompt — this panel will move there.
 */
function statusTone(s?: string | null): BadgeTone {
  if (s === "ok") return "success";
  if (s === "error") return "danger";
  if (s === "skipped") return "warning";
  return "neutral";
}

export function StreamingControl() {
  const [data, setData] = useState<StreamingStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await streamingStatus());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load streaming status");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const update = useCallback(
    async (t: StreamingTable, patch: Parameters<typeof streamingUpdateConfig>[1]) => {
      setBusy(t.source_view);
      setNote(null);
      try {
        await streamingUpdateConfig(t.source_view, patch);
        await load();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Update failed");
      } finally {
        setBusy(null);
      }
    },
    [load],
  );

  const runOnce = useCallback(
    async (t: StreamingTable) => {
      setBusy(t.source_view);
      setNote(null);
      try {
        const r = await streamingRunOnce(t.source_view);
        setNote(
          r.ok
            ? `${t.source_view}: +${r.rows_added ?? 0} rows (cursor ${r.cursor ?? "—"})`
            : `${t.source_view}: ${r.error ?? "failed"}`,
        );
        await load();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Run-once failed");
      } finally {
        setBusy(null);
      }
    },
    [load],
  );

  const loop = data?.loop;
  const tables = data?.tables ?? [];

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <Radio size={16} /> Streaming (watermark-incremental)
          </span>
        }
        action={
          <div className="flex items-center gap-2">
            <Badge tone={loop?.enabled ? (loop?.running ? "info" : "neutral") : "neutral"}>
              loop {loop?.enabled ? (loop?.running ? "running" : "enabled") : "off"}
            </Badge>
            <Button variant="secondary" size="sm" onClick={() => void load()}>
              <RefreshCw size={14} /> Refresh
            </Button>
          </div>
        }
      />
      <CardBody>
        {error ? <p className="mb-2 text-sm text-danger">{error}</p> : null}
        {note ? <p className="mb-2 text-sm text-neutral-600">{note}</p> : null}
        <Table>
          <THead>
            <TR>
              <TH>Table</TH>
              <TH>Enabled</TH>
              <TH>Granularity</TH>
              <TH>ts_col</TH>
              <TH>Cursor</TH>
              <TH>Last +rows</TH>
              <TH>Status</TH>
              <TH />
            </TR>
          </THead>
          <TBody>
            {tables.map((t) => (
              <TR key={t.source_view}>
                <TD className="font-medium">{t.source_view}</TD>
                <TD>
                  <input
                    type="checkbox"
                    checked={t.enabled}
                    disabled={busy === t.source_view}
                    onChange={(e) => void update(t, { enabled: e.target.checked })}
                  />
                </TD>
                <TD>
                  <Select
                    value={t.granularity}
                    disabled={busy === t.source_view}
                    onChange={(e) => void update(t, { granularity: e.target.value })}
                  >
                    <option value="day">day</option>
                    <option value="timestamp" disabled={!t.has_ts_time_col}>
                      timestamp{t.has_ts_time_col ? "" : " (no time col)"}
                    </option>
                  </Select>
                </TD>
                <TD className="text-neutral-500">{t.ts_col ?? "—"}</TD>
                <TD>{t.last_watermark ?? "—"}</TD>
                <TD>{t.last_rows_added ?? "—"}</TD>
                <TD>
                  <Badge tone={statusTone(t.last_status)}>{t.last_status ?? "—"}</Badge>
                </TD>
                <TD>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={busy === t.source_view}
                    onClick={() => void runOnce(t)}
                  >
                    Run once
                  </Button>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardBody>
    </Card>
  );
}
