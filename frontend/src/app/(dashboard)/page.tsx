"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Boxes, Plug, Repeat, Cable, Database, AlertTriangle, Radio } from "lucide-react";
import {
  listApiKeys,
  listConnections,
  listDataModels,
  listTables,
  listTransactions,
  mqttStatus,
  type MqttStatus,
} from "@/lib/api";

type Stats = {
  modelsTotal: number;
  modelsA: number;
  modelsB: number;
  modelsActive: number;
  apiKeysActive: number;
  connectionsActive: number;
  txToday: number;
  txInToday: number;
  txOutToday: number;
  txFailed: number;
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

function MqttStatusCard() {
  const [m, setM] = useState<MqttStatus | null>(null);
  useEffect(() => {
    const load = () => mqttStatus().then(setM).catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);
  if (!m) return null;
  const tone = !m.configured_enabled ? "neutral" : m.connected ? "success" : "warning";
  const label = !m.configured_enabled ? "disabled" : m.connected ? "connected" : "connecting…";
  return (
    <Card className="mb-4">
      <CardBody>
        <div className="flex flex-wrap items-center gap-3">
          <Radio size={18} className="text-brand" />
          <span className="text-sm font-semibold text-neutral-800">MQTT Consumer (UNS)</span>
          <Badge tone={tone}>{label}</Badge>
          {m.configured_broker && <span className="font-mono text-xs text-neutral-500">{m.configured_broker}</span>}
          <span className="text-xs text-neutral-500">
            topics: {(m.configured_topics || []).join(", ") || "—"}
          </span>
          <Link href="/transactions" className="ml-auto text-xs text-neutral-500 hover:text-brand">
            received {m.messages_received} · ingested {m.messages_ingested} · skipped {m.messages_skipped} →
          </Link>
        </div>
        {m.configured_enabled && !m.connected && m.last_error && (
          <p className="mt-1 font-mono text-xs text-warning">last error: {m.last_error}</p>
        )}
        {!m.configured_enabled && (
          <p className="mt-1 text-xs text-neutral-400">
            Set MQTT_ENABLED=true + MQTT_BROKER_HOST to subscribe (enabled on .63).
          </p>
        )}
      </CardBody>
    </Card>
  );
}

export default function DashboardPage() {
  const [s, setS] = useState<Stats | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const today = new Date().toISOString().slice(0, 10);
        const [models, keys, conns, tx, staging] = await Promise.all([
          listDataModels().catch(() => []),
          listApiKeys().catch(() => []),
          listConnections().catch(() => []),
          listTransactions({ limit: 500 }).catch(() => []),
          listTables("mdp_staging").catch(() => []),
        ]);
        const txToday = tx.filter((t) => (t.created_at || "").slice(0, 10) === today);
        setS({
          modelsTotal: models.length,
          modelsA: models.filter((m) => m.type === "A").length,
          modelsB: models.filter((m) => m.type === "B").length,
          modelsActive: models.filter((m) => m.status === "active").length,
          apiKeysActive: keys.filter((k) => k.is_active).length,
          connectionsActive: conns.filter((c) => c.status === "active").length,
          txToday: txToday.length,
          txInToday: txToday.filter((t) => t.direction === "inbound").length,
          txOutToday: txToday.filter((t) => t.direction === "outbound").length,
          txFailed: tx.filter((t) => t.status !== "success").length,
          stagingTables: staging.length,
        });
      } catch (e) {
        setErr(String(e));
      }
    })();
  }, []);

  const v = (n: number | undefined) => (s ? n : "…");

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Avenue MDP — Manufacturing Data Platform." />
      <MqttStatusCard />
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
          label="Transactions today"
          value={v(s?.txToday)}
          sub={s && <span>in: {s.txInToday} · out: {s.txOutToday}</span>}
        />
        <Stat
          href="/transactions"
          icon={<AlertTriangle size={20} />}
          label="Failed (all-time)"
          value={v(s?.txFailed)}
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
