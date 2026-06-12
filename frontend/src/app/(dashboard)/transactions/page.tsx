"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Select } from "@/components/ui/Select";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import { ApiError, apiPath, listTransactions, type Transaction } from "@/lib/api";

function statusTone(s: string): BadgeTone {
  if (s === "success") return "success";
  return "danger";
}

// Clamp the typed count to the backend cap (1..500); blank/<=0/non-numeric falls back to 100.
// Number() (not parseInt) so exponent forms like "1e9" parse as 1e9 -> clamped to 500, not 1.
const LIMIT_MAX = 500;
function clampLimit(value: string): number {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 1) return 100;
  return Math.min(Math.floor(n), LIMIT_MAX);
}

export default function TransactionsPage() {
  const [items, setItems] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [direction, setDirection] = useState("");
  const [status, setStatus] = useState("");
  // limitInput is the free-text field; limit is the COMMITTED value (applied on blur/Enter, not on
  // every keystroke) that actually drives the query - so typing a count does not fire a request per
  // digit and never flickers the table mid-typing.
  const [limitInput, setLimitInput] = useState("100");
  const [limit, setLimit] = useState(100);
  const reqSeq = useRef(0);

  const commitLimit = useCallback(() => {
    const clamped = clampLimit(limitInput);
    setLimitInput(String(clamped));
    setLimit(clamped);
  }, [limitInput]);

  const reload = useCallback(async () => {
    // Sequence guard: only the latest request's response is applied, so a slow earlier request can
    // never overwrite the table with stale rows (out-of-order responses).
    const seq = ++reqSeq.current;
    setLoading(true);
    setErr(null);
    try {
      const data = await listTransactions({
        limit,
        direction: direction || undefined,
        status: status || undefined,
      });
      if (seq === reqSeq.current) setItems(data);
    } catch (e) {
      if (seq === reqSeq.current) setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [direction, status, limit]);
  useEffect(() => {
    reload();
  }, [reload]);

  return (
    <>
      <PageHeader
        title="Transactions"
        subtitle={`Public API: ${apiPath("/transactions")} · Backend route: /transactions.`}
        action={<Button variant="secondary" onClick={reload}>Refresh</Button>}
      />
      {err && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
      <Card>
        <CardHeader
          title="Recent transactions"
          subtitle={`${items.length} shown (max ${LIMIT_MAX} per load)`}
          action={
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col text-xs text-neutral-500">
                Number of transactions to load
                <input
                  type="number"
                  min={1}
                  max={LIMIT_MAX}
                  aria-label="Number of transactions to load"
                  value={limitInput}
                  onChange={(e) => setLimitInput(e.target.value)}
                  onBlur={commitLimit}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitLimit();
                  }}
                  className="mt-1 h-10 w-44 rounded-md border border-neutral-300 bg-white px-3 text-sm text-neutral-900 focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
                />
              </label>
              <Select value={direction} onChange={(e) => setDirection(e.target.value)}>
                <option value="">all directions</option>
                <option value="inbound">inbound</option>
                <option value="outbound">outbound</option>
              </Select>
              <Select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">all status</option>
                <option value="success">success</option>
                <option value="failed">failed</option>
              </Select>
            </div>
          }
        />
        <CardBody>
          {loading ? (
            <p className="text-sm text-neutral-400">Loading...</p>
          ) : items.length === 0 ? (
            <p className="text-sm text-neutral-400">
              No transactions yet. They appear after an inbound ingest or outbound query.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <THead>
                  <TR>
                    <TH>Time</TH>
                    <TH>Direction</TH>
                    <TH>Protocol</TH>
                    <TH>Endpoint</TH>
                    <TH>Auth</TH>
                    <TH>Source</TH>
                    <TH>Status</TH>
                  </TR>
                </THead>
                <TBody>
                  {items.map((t) => (
                    <TR key={t.id}>
                      <TD className="whitespace-nowrap text-xs">{t.created_at?.replace("T", " ").slice(0, 19)}</TD>
                      <TD>
                        <Badge tone={t.direction === "inbound" ? "info" : "neutral"}>{t.direction}</Badge>
                      </TD>
                      <TD className="text-xs">{t.protocol}</TD>
                      <TD className="font-mono text-xs">{t.endpoint || "-"}</TD>
                      <TD className="text-xs">{t.auth_type || "-"}</TD>
                      <TD className="text-xs">{t.source_system || "-"}</TD>
                      <TD>
                        <Badge tone={statusTone(t.status)}>{t.status}</Badge>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          )}
        </CardBody>
      </Card>
    </>
  );
}
