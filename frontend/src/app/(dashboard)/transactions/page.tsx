"use client";

import { useCallback, useEffect, useState } from "react";
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

export default function TransactionsPage() {
  const [items, setItems] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [direction, setDirection] = useState("");
  const [status, setStatus] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setItems(
        await listTransactions({
          limit: 100,
          direction: direction || undefined,
          status: status || undefined,
        }),
      );
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [direction, status]);
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
          subtitle={`${items.length} shown`}
          action={
            <div className="flex gap-2">
              <Select value={direction} onChange={(e) => setDirection(e.target.value)}>
                <option value="">all directions</option>
                <option value="inbound">inbound</option>
                <option value="outbound">outbound</option>
              </Select>
              <Select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">all status</option>
                <option value="success">success</option>
                <option value="error">error</option>
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
