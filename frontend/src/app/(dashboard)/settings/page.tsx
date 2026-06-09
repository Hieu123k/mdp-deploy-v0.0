"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Radio, SlidersHorizontal } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import { useAuth } from "@/components/auth/AuthProvider";
import { NAV_ITEMS } from "@/lib/nav";
import {
  ApiError,
  getUserPreferences,
  listUsers,
  setUserPreferences,
  streamingRunOnce,
  streamingStatus,
  streamingUpdateConfig,
  type NavConfig,
  type StreamingTable,
  type User,
} from "@/lib/api";

type TabRow = { href: string; label: string; baseLabel: string; visible: boolean };

function buildRows(navConfig: NavConfig): TabRow[] {
  const rows = NAV_ITEMS.map((it) => {
    const o = navConfig[it.href];
    return {
      href: it.href,
      baseLabel: it.label,
      label: o?.label ?? it.label,
      visible: o?.visible !== false,
    };
  });
  rows.sort((a, b) => {
    const oa = navConfig[a.href]?.order;
    const ob = navConfig[b.href]?.order;
    if (oa == null && ob == null) return 0;
    if (oa == null) return 1;
    if (ob == null) return -1;
    return oa - ob;
  });
  return rows;
}

export default function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  // ---- Tab config (per user) ----
  const [users, setUsers] = useState<User[]>([]);
  const [targetId, setTargetId] = useState<string>("");
  const [rows, setRows] = useState<TabRow[]>([]);
  const [tabMsg, setTabMsg] = useState<string | null>(null);
  const [tabErr, setTabErr] = useState<string | null>(null);
  const [savingTabs, setSavingTabs] = useState(false);

  useEffect(() => {
    if (!isAdmin) return;
    listUsers()
      .then((u) => {
        setUsers(u);
        setTargetId((cur) => cur || (u[0]?.id ?? ""));
      })
      .catch((e) => setTabErr(e instanceof ApiError ? e.message : "Failed to load users"));
  }, [isAdmin]);

  const loadTarget = useCallback(async (uid: string) => {
    if (!uid) return;
    setTabMsg(null);
    setTabErr(null);
    try {
      const pref = await getUserPreferences(uid);
      setRows(buildRows(pref.nav_config || {}));
    } catch (e) {
      setTabErr(e instanceof ApiError ? e.message : "Failed to load preferences");
    }
  }, []);

  useEffect(() => {
    if (targetId) void loadTarget(targetId);
  }, [targetId, loadTarget]);

  const move = (idx: number, dir: -1 | 1) => {
    setRows((rs) => {
      const next = [...rs];
      const j = idx + dir;
      if (j < 0 || j >= next.length) return rs;
      [next[idx], next[j]] = [next[j], next[idx]];
      return next;
    });
  };

  const saveTabs = async () => {
    if (!targetId) return;
    setSavingTabs(true);
    setTabMsg(null);
    setTabErr(null);
    const navConfig: NavConfig = {};
    rows.forEach((r, idx) => {
      navConfig[r.href] = { visible: r.visible, label: r.label, order: idx };
    });
    try {
      await setUserPreferences(targetId, { nav_config: navConfig });
      setTabMsg("Saved. The user sees these tabs on next load.");
    } catch (e) {
      setTabErr(e instanceof ApiError ? e.message : "Save failed");
    } finally {
      setSavingTabs(false);
    }
  };

  // ---- Streaming config (consume prompt-27 API) ----
  // Edits go to a local draft per table; nothing is saved until "Apply" is clicked.
  type StreamDraft = { enabled: boolean; granularity: string; poll_interval_sec: number; lookback_days: number };
  const [streaming, setStreaming] = useState<StreamingTable[] | null>(null);
  const [streamingAvail, setStreamingAvail] = useState<boolean>(true);
  const [streamMsg, setStreamMsg] = useState<string | null>(null);
  const [streamBusy, setStreamBusy] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, StreamDraft>>({});

  const loadStreaming = useCallback(async () => {
    try {
      const s = await streamingStatus();
      setStreaming(s.tables);
      setDrafts(
        Object.fromEntries(
          s.tables.map((t) => [
            t.source_view,
            {
              enabled: t.enabled,
              granularity: t.granularity,
              poll_interval_sec: t.poll_interval_sec,
              lookback_days: t.lookback_days,
            },
          ]),
        ),
      );
      setStreamingAvail(true);
    } catch {
      setStreamingAvail(false);
    }
  }, []);

  useEffect(() => {
    void loadStreaming();
  }, [loadStreaming]);

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

  const applyStreaming = async (t: StreamingTable) => {
    const d = draftOf(t);
    setStreamBusy(t.source_view);
    setStreamMsg(null);
    try {
      await streamingUpdateConfig(t.source_view, {
        enabled: d.enabled,
        granularity: d.granularity,
        poll_interval_sec: d.poll_interval_sec,
        lookback_days: d.lookback_days,
      });
      setStreamMsg(
        `${t.source_view}: applied — ${d.enabled ? "enabled" : "disabled"}, ${d.granularity}, every ${d.poll_interval_sec}s. ` +
          (d.enabled ? "The background loop picks it up within one tick." : ""),
      );
      await loadStreaming();
    } catch (e) {
      setStreamMsg(e instanceof ApiError ? e.message : "Apply failed");
    } finally {
      setStreamBusy(null);
    }
  };

  const runOnce = async (t: StreamingTable) => {
    setStreamBusy(t.source_view);
    setStreamMsg(null);
    try {
      const r = await streamingRunOnce(t.source_view);
      setStreamMsg(
        r.ok ? `${t.source_view}: +${r.rows_added ?? 0} (cursor ${r.cursor ?? "—"})` : `${t.source_view}: ${r.error}`,
      );
      await loadStreaming();
    } catch (e) {
      setStreamMsg(e instanceof ApiError ? e.message : "Run-once failed");
    } finally {
      setStreamBusy(null);
    }
  };

  const targetUser = useMemo(() => users.find((u) => u.id === targetId), [users, targetId]);

  if (!isAdmin) {
    return (
      <div className="space-y-4">
        <PageHeader title="Settings" subtitle="Admin only" />
        <Card>
          <CardBody>
            <p className="text-sm text-danger">You need the admin role to view Settings.</p>
          </CardBody>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" subtitle="Tab visibility & layout per user, theme, and streaming config" />

      {/* Tab config per user */}
      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <SlidersHorizontal size={16} /> Tabs & access (per user)
            </span>
          }
          subtitle="Show/hide, rename and reorder a user's sidebar tabs. Admin-only routes are also enforced by the backend (403)."
          action={
            <Select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username} ({u.role})
                </option>
              ))}
            </Select>
          }
        />
        <CardBody>
          {tabErr ? <p className="mb-2 text-sm text-danger">{tabErr}</p> : null}
          {tabMsg ? <p className="mb-2 text-sm text-success">{tabMsg}</p> : null}
          <Table>
            <THead>
              <TR>
                <TH>Order</TH>
                <TH>Route</TH>
                <TH>Visible</TH>
                <TH>Display label</TH>
              </TR>
            </THead>
            <TBody>
              {rows.map((r, idx) => (
                <TR key={r.href}>
                  <TD>
                    <div className="flex items-center gap-1">
                      <button
                        className="rounded p-1 text-neutral-400 hover:bg-neutral-100 disabled:opacity-30 dark:hover:bg-neutral-800"
                        onClick={() => move(idx, -1)}
                        disabled={idx === 0}
                        title="Move up"
                      >
                        <ArrowUp size={14} />
                      </button>
                      <button
                        className="rounded p-1 text-neutral-400 hover:bg-neutral-100 disabled:opacity-30 dark:hover:bg-neutral-800"
                        onClick={() => move(idx, 1)}
                        disabled={idx === rows.length - 1}
                        title="Move down"
                      >
                        <ArrowDown size={14} />
                      </button>
                    </div>
                  </TD>
                  <TD className="font-mono text-xs text-neutral-500">{r.href}</TD>
                  <TD>
                    <input
                      type="checkbox"
                      checked={r.visible}
                      onChange={(e) =>
                        setRows((rs) => rs.map((x) => (x.href === r.href ? { ...x, visible: e.target.checked } : x)))
                      }
                    />
                  </TD>
                  <TD>
                    <Input
                      value={r.label}
                      onChange={(e) =>
                        setRows((rs) => rs.map((x) => (x.href === r.href ? { ...x, label: e.target.value } : x)))
                      }
                      className="max-w-[14rem]"
                    />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          <div className="mt-3 flex items-center gap-2">
            <Button onClick={saveTabs} disabled={savingTabs || !targetId}>
              {savingTabs ? "Saving…" : `Save tabs for ${targetUser?.username ?? "user"}`}
            </Button>
          </div>
        </CardBody>
      </Card>

      {/* Streaming config */}
      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <Radio size={16} /> Streaming (watermark-incremental)
            </span>
          }
          subtitle="Enable a table and it auto-migrates. 'Run every' is the single cadence (min 2s). The timestamp option unlocks only when the view exposes a time column (UPMT)."
          action={
            <Button variant="secondary" size="sm" onClick={() => void loadStreaming()}>
              Refresh
            </Button>
          }
        />
        <CardBody>
          {!streamingAvail ? (
            <p className="text-sm text-neutral-500">
              Streaming API not available on this backend (deploy the streaming feature to enable).
            </p>
          ) : (
            <>
              {streamMsg ? <p className="mb-2 text-sm text-neutral-600 dark:text-neutral-300">{streamMsg}</p> : null}
              <Table>
                <THead>
                  <TR>
                    <TH>Table</TH>
                    <TH>Enabled</TH>
                    <TH>Granularity</TH>
                    <TH>Run every (s)</TH>
                    <TH>Lookback (d)</TH>
                    <TH>Cursor</TH>
                    <TH> </TH>
                  </TR>
                </THead>
                <TBody>
                  {(streaming ?? []).map((t) => {
                    const d = draftOf(t);
                    const dirty = isDirty(t);
                    return (
                    <TR key={t.source_view}>
                      <TD className="font-medium">
                        {t.source_view}
                        {dirty ? <span className="ml-1.5 text-xs text-warning">unsaved</span> : null}
                      </TD>
                      <TD>
                        <input
                          type="checkbox"
                          checked={d.enabled}
                          disabled={streamBusy === t.source_view}
                          onChange={(e) => setDraft(t.source_view, { enabled: e.target.checked })}
                        />
                      </TD>
                      <TD>
                        <Select
                          value={d.granularity}
                          disabled={streamBusy === t.source_view}
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
                          value={d.poll_interval_sec}
                          className="max-w-[6rem]"
                          onChange={(e) => setDraft(t.source_view, { poll_interval_sec: Number(e.target.value) })}
                        />
                      </TD>
                      <TD>
                        <Input
                          type="number"
                          value={d.lookback_days}
                          className="max-w-[5rem]"
                          onChange={(e) => setDraft(t.source_view, { lookback_days: Number(e.target.value) })}
                        />
                      </TD>
                      <TD className="font-mono text-xs text-neutral-500">
                        {t.last_watermark ?? "—"}
                        {t.last_watermark_time ? `:${t.last_watermark_time}` : ""}
                        {t.last_status ? <Badge tone={t.last_status === "ok" ? "success" : "danger"}>{t.last_status}</Badge> : null}
                      </TD>
                      <TD>
                        <div className="flex items-center gap-1.5">
                          <Button
                            size="sm"
                            disabled={streamBusy === t.source_view || !dirty}
                            onClick={() => void applyStreaming(t)}
                            title="Save this table's streaming config"
                          >
                            {streamBusy === t.source_view ? "Applying…" : "Apply"}
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={streamBusy === t.source_view}
                            onClick={() => void runOnce(t)}
                            title="Run one streaming cycle now"
                          >
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
    </div>
  );
}
