"use client";

import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import { Modal } from "@/components/ui/Modal";

// Full literal class strings (Tailwind JIT does not pick up dynamically-composed classes).
const BRAND = [
  { k: "50", c: "bg-brand-50" },
  { k: "100", c: "bg-brand-100" },
  { k: "200", c: "bg-brand-200" },
  { k: "300", c: "bg-brand-300" },
  { k: "400", c: "bg-brand-400" },
  { k: "500", c: "bg-brand-500" },
  { k: "600", c: "bg-brand-600" },
  { k: "700", c: "bg-brand-700" },
];
const NEUTRAL = [
  { k: "50", c: "bg-neutral-50" },
  { k: "100", c: "bg-neutral-100" },
  { k: "200", c: "bg-neutral-200" },
  { k: "300", c: "bg-neutral-300" },
  { k: "400", c: "bg-neutral-400" },
  { k: "500", c: "bg-neutral-500" },
  { k: "600", c: "bg-neutral-600" },
  { k: "700", c: "bg-neutral-700" },
  { k: "800", c: "bg-neutral-800" },
  { k: "900", c: "bg-neutral-900" },
];
const STATUS = [
  { name: "success", c: "bg-success" },
  { name: "warning", c: "bg-warning" },
  { name: "danger", c: "bg-danger" },
  { name: "info", c: "bg-info" },
];
const BADGES: { tone: BadgeTone; label: string }[] = [
  { tone: "success", label: "connected / updated" },
  { tone: "warning", label: "migrating / pending" },
  { tone: "danger", label: "error" },
  { tone: "info", label: "running" },
  { tone: "neutral", label: "idle" },
];

function Swatch({ className, label }: { className: string; label: string }) {
  return (
    <div className="text-center">
      <div className={`h-12 w-full rounded-md border border-neutral-200 ${className}`} />
      <span className="mt-1 block text-[11px] text-neutral-500">{label}</span>
    </div>
  );
}

export default function DesignSystemPage() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Design System"
        subtitle="UI source of truth — brand color #E01E26, Inter typography, sample components."
        action={<Badge tone="info">v1</Badge>}
      />

      <div className="space-y-6">
        {/* Colors */}
        <Card>
          <CardHeader title="Colors" subtitle="Brand #E01E26 · Neutral #A7A9AC · Status" />
          <CardBody className="space-y-5">
            <div>
              <p className="mb-2 text-sm font-medium text-neutral-700">Brand</p>
              <div className="grid grid-cols-4 gap-3 sm:grid-cols-8">
                {BRAND.map((s) => (
                  <Swatch key={s.k} className={s.c} label={s.k} />
                ))}
              </div>
            </div>
            <div>
              <p className="mb-2 text-sm font-medium text-neutral-700">Neutral</p>
              <div className="grid grid-cols-5 gap-3 sm:grid-cols-10">
                {NEUTRAL.map((s) => (
                  <Swatch key={s.k} className={s.c} label={s.k} />
                ))}
              </div>
            </div>
            <div>
              <p className="mb-2 text-sm font-medium text-neutral-700">Status</p>
              <div className="grid grid-cols-4 gap-3">
                {STATUS.map((s) => (
                  <Swatch key={s.name} className={s.c} label={s.name} />
                ))}
              </div>
            </div>
          </CardBody>
        </Card>

        {/* Typography */}
        <Card>
          <CardHeader title="Typography" subtitle="Inter (next/font) · numbers use tabular-nums" />
          <CardBody className="space-y-2">
            <h1 className="text-3xl font-bold">Heading 1 - Avenue MDP</h1>
            <h2 className="text-2xl font-semibold">Heading 2</h2>
            <h3 className="text-lg font-semibold">Heading 3</h3>
            <p className="text-sm text-neutral-600">
              Body text — manage object types, map source columns, build dynamic APIs.
            </p>
            <p className="tabular-nums text-sm text-neutral-700">
              Numbers: 1,234,567 · 12,500 · 99,000 · 6,250,000
            </p>
          </CardBody>
        </Card>

        {/* Buttons */}
        <Card>
          <CardHeader title="Button" subtitle="primary · secondary · ghost · destructive" />
          <CardBody className="flex flex-wrap items-center gap-3">
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="destructive">Destructive</Button>
            <Button variant="primary" size="sm">Small</Button>
            <Button variant="primary" disabled>Disabled</Button>
            <Button variant="secondary" onClick={() => setOpen(true)}>Open Modal</Button>
          </CardBody>
        </Card>

        {/* Inputs */}
        <Card>
          <CardHeader title="Input" subtitle="MUTED placeholder (neutral-400) — MoM #4" />
          <CardBody className="grid max-w-xl grid-cols-1 gap-4 sm:grid-cols-2">
            <Input label="Object Type ID" placeholder="invoice_inbound" />
            <Input label="Mapping name" placeholder="default_mapping" hint="Placeholder shown muted" />
          </CardBody>
        </Card>

        {/* Badges */}
        <Card>
          <CardHeader title="Status badges" />
          <CardBody className="flex flex-wrap gap-3">
            {BADGES.map((b) => (
              <Badge key={b.tone} tone={b.tone}>{b.label}</Badge>
            ))}
          </CardBody>
        </Card>

        {/* Table */}
        <Card>
          <CardHeader title="Table" subtitle="header bg-neutral-50 · hover row" />
          <CardBody>
            <Table>
              <THead>
                <TR>
                  <TH>#</TH>
                  <TH>JDE</TH>
                  <TH>PG Table</TH>
                  <TH>Rows</TH>
                  <TH>Status</TH>
                </TR>
              </THead>
              <TBody>
                <TR>
                  <TD>1</TD>
                  <TD>F4311</TD>
                  <TD>v2_pro_f4311</TD>
                  <TD className="tabular-nums">12</TD>
                  <TD><Badge tone="success">updated</Badge></TD>
                </TR>
                <TR>
                  <TD>2</TD>
                  <TD>F0911</TD>
                  <TD>v2_pro_f0911</TD>
                  <TD className="tabular-nums">0</TD>
                  <TD><Badge tone="neutral">idle</Badge></TD>
                </TR>
              </TBody>
            </Table>
          </CardBody>
        </Card>
      </div>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Sample modal"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={() => setOpen(false)}>Confirm</Button>
          </>
        }
      >
        <p className="text-sm text-neutral-600">
          Overlay <code>bg-black/40</code>, panel <code>rounded-lg</code>. Close with
          Esc, the X button, or by clicking the backdrop.
        </p>
      </Modal>
    </>
  );
}
