"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Boxes, Plug, Repeat, Cable, Database, AlertTriangle } from "lucide-react";
import {
  getTransactionStats,
  listApiKeys,
  listConnections,
  listDataModels,
  listTables,
} from "@/lib/api";

type Stats = {
  modelsTotal: number;
  modelsA: number;
  modelsB: number;
  modelsActive: number;
  apiKeysActive: number;
  connectionsActive: number;
  // All-time transaction counts from /transactions/stats (no 500 cap). null = stats call failed.
  tx: { total: number; success: number; failed: number } | null;
  stagingTables: number;
};

function Stat({
  href,
  icon,
  label,
  value,
  sub,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
}) {
  return (
    <Link href={href}>
      <Card className="h-full transition-shadow hover:shadow-md">
        <CardBody>
          <div className="flex items-center gap-2 text-neutral-400">
            {icon}
            <span className="text-sm">{label}</span>
          </div>
          <p className="mt-2 text-3xl font-bold tabular-nums text-neutral-900">{value}</p>
          {sub && <div className="mt-1 text-xs text-neutral-500">{sub}</div>}
        </CardBody>
      </Card>
    </Link>
  );
}

export default function DashboardPage() {
  const [s, setS] = useState<Stats | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        // Transaction counts come from /transactions/stats (all-time, no 500 cap). Its own catch
        // keeps a stats outage from breaking the rest of the Dashboard (cards then show "-").
        const [models, keys, conns, txStats, staging] = await Promise.all([
          listDataModels().catch(() => []),
          listApiKeys().catch(() => []),
          listConnections().catch(() => []),
          getTransactionStats().catch(() => null),
          listTables("mdp_staging").catch(() => []),
        ]);
        setS({
          modelsTotal: models.length,
          modelsA: models.filter((m) => m.type === "A").length,
          modelsB: models.filter((m) => m.type === "B").length,
          modelsActive: models.filter((m) => m.status === "active").length,
          apiKeysActive: keys.filter((k) => k.is_active).length,
          connectionsActive: conns.filter((c) => c.status === "active").length,
          tx: txStats
            ? {
                total: txStats.total,
                success: txStats.by_status?.success ?? 0,
                failed: txStats.by_status?.failed ?? 0,
              }
            : null,
          stagingTables: staging.length,
        });
      } catch (e) {
        setErr(String(e));
      }
    })();
  }, []);

  const v = (n: number | undefined) => (s ? n : "…");
  // All-time transaction cards: reuse the shared loading placeholder while loading; "-" if the
  // stats call failed (s.tx === null) so a stats outage never breaks the Dashboard.
  const txStat = (n: number | undefined) => (s ? (s.tx ? n : "-") : v(n));

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Avenue MDP — Manufacturing Data Platform." />
      {err && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Stat
          href="/object-manager"
          icon={<Boxes size={20} />}
          label="Data Models"
          value={v(s?.modelsTotal)}
          sub={
            s && (
              <span className="flex gap-1">
                <Badge tone="success">A: {s.modelsA}</Badge>
                <Badge tone="info">B: {s.modelsB}</Badge>
                <Badge tone="neutral">active: {s.modelsActive}</Badge>
              </span>
            )
          }
        />
        <Stat href="/apis" icon={<Plug size={20} />} label="Active API Keys" value={v(s?.apiKeysActive)} />
        <Stat
          href="/connections"
          icon={<Cable size={20} />}
          label="Active Connections"
          value={v(s?.connectionsActive)}
        />
        <Stat
          href="/transactions"
          icon={<Repeat size={20} />}
          label="Transactions (all-time)"
          value={txStat(s?.tx?.total)}
          sub={s && s.tx && <span>success: {s.tx.success} / failed: {s.tx.failed}</span>}
        />
        <Stat
          href="/transactions"
          icon={<AlertTriangle size={20} />}
          label="Failed (all-time)"
          value={txStat(s?.tx?.failed)}
        />
        <Stat
          href="/jde"
          icon={<Database size={20} />}
          label="JDE staging tables"
          value={v(s?.stagingTables)}
          sub={s && (s.stagingTables > 0 ? <Badge tone="success">seeded</Badge> : <Badge tone="warning">empty</Badge>)}
        />
      </div>
    </>
  );
}
