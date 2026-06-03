"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Database, Eye, FilePlus2, PlayCircle, RefreshCcw, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import {
  ApiError,
  apiPath,
  createDataModelFromTemplate,
  createMigrationJobFromTemplate,
  createMigrationRun,
  getJdeWorkflowStatus,
  outboundByKey,
  previewSavedTypeBModel,
  seedProcurementStagingData,
  validateMigrationTarget,
  type JdeWorkflowStatus,
  type ModelPreview,
} from "@/lib/api";

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

function tone(value?: string | boolean | null): BadgeTone {
  if (value === true || value === "success" || value === "pass" || value === "active") return "success";
  if (value === false || value === "failed" || value === "fail" || value === "inactive") return "danger";
  if (value === "running" || value === "warning" || value === "pending") return "warning";
  return "neutral";
}

function label(value?: string | boolean | null): string {
  if (typeof value === "boolean") return value ? "ready" : "not ready";
  return value ? value.replace(/_/g, " ") : "none";
}

function rowsFromPreview(preview: ModelPreview | null): Record<string, unknown>[] {
  return preview?.data || preview?.records || [];
}

function PreviewPanel({ title, data }: { title: string; data: unknown }) {
  if (!data) return null;
  return (
    <Card>
      <CardHeader title={title} />
      <CardBody>
        <pre className="max-h-80 overflow-auto rounded-md bg-neutral-950 p-3 text-xs text-neutral-50">
          {JSON.stringify(data, null, 2)}
        </pre>
      </CardBody>
    </Card>
  );
}

export default function JdeDemoPage() {
  const [status, setStatus] = useState<JdeWorkflowStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [result, setResult] = useState<unknown>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStatus(await getJdeWorkflowStatus());
    } catch (err) {
      setError(message(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  async function runAction(name: string, action: () => Promise<unknown>, success: string) {
    setBusy(name);
    setError(null);
    setNotice(null);
    try {
      const output = await action();
      setResult(output);
      setNotice(success);
      await reload();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setNotice("Already exists. You can open the existing job/model.");
        await reload();
      } else {
        setError(message(err));
      }
    } finally {
      setBusy(null);
    }
  }

  const supplier = status?.supplier;
  const poSummary = status?.purchase_order_summary;
  const supplierCount = status?.staging.tables.stg_jde_supplier ?? 0;
  const poCount = status?.staging.tables.stg_jde_po_header ?? 0;

  return (
    <>
      <PageHeader
        title="JDE Procurement Demo Flow"
        subtitle={`Guided UAT flow over ${apiPath("/demo/jde-procurement/workflow-status")}`}
        action={
          <Button variant="secondary" onClick={reload} disabled={loading || !!busy}>
            <RefreshCcw size={16} />
            Refresh
          </Button>
        }
      />

      {error && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
      {notice && <p className="mb-4 rounded-md bg-success/10 px-3 py-2 text-sm text-success">{notice}</p>}

      <Card className="mb-4">
        <CardBody>
          <p className="text-sm text-neutral-600">
            This demo simulates the external ora2pg load by seeding PostgreSQL staging data. In production, ora2pg or another bulk loader runs first; Avenue MDP records the run, validates the target, creates governed Type B models, and exposes outbound APIs.
          </p>
        </CardBody>
      </Card>

      {loading ? (
        <p className="text-sm text-neutral-500">Loading workflow status...</p>
      ) : status && (
        <div className="space-y-4">
          <Card>
            <CardHeader
              title="Step 1 - Staging Data"
              subtitle="Mock migrated JDE procurement tables in mdp_staging"
              action={
                <Button
                  size="sm"
                  onClick={() => runAction("seed", seedProcurementStagingData, "Procurement staging data seeded.")}
                  disabled={!!busy}
                >
                  <Database size={15} />
                  Seed Demo Data
                </Button>
              }
            />
            <CardBody>
              <div className="mb-3 flex items-center gap-2">
                <span className="text-sm text-neutral-600">Readiness</span>
                <Badge tone={tone(status.staging.procurement_staging_seeded)}>
                  {label(status.staging.procurement_staging_seeded)}
                </Badge>
              </div>
              <Table className="table-fixed text-xs">
                <THead>
                  <TR>
                    <TH>Table</TH>
                    <TH className="text-center">Rows</TH>
                  </TR>
                </THead>
                <TBody>
                  {Object.entries(status.staging.tables).map(([table, count]) => (
                    <TR key={table}>
                      <TD className="font-mono">{table}</TD>
                      <TD className="text-center">{count}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </CardBody>
          </Card>

          {supplier && (
            <Card>
              <CardHeader title="Supplier Flow" subtitle="Migration job -> run -> target validation -> Type B model -> outbound API" />
              <CardBody className="space-y-4">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <StatusBox title="Migration Job" value={supplier.migration_job_exists} detail={supplier.migration_job_status} />
                  <StatusBox title="Latest Run" value={supplier.latest_run_status} detail={supplier.latest_run_id} />
                  <StatusBox title="Validation" value={supplier.target_validation_status} detail={`${supplier.target_row_count ?? "-"} target rows`} />
                  <StatusBox title="Type B Model" value={supplier.data_model_exists} detail={supplier.data_model_status} />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => runAction("supplier-job", () => createMigrationJobFromTemplate("jde_supplier_master", {}), "Supplier migration job is ready.")}
                    disabled={!!busy || supplier.migration_job_exists}
                  >
                    <FilePlus2 size={15} />
                    Create Supplier Migration Job
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => runAction("supplier-run", () => {
                      if (!supplier.migration_job_id) throw new Error("Create the supplier migration job first.");
                      return createMigrationRun(supplier.migration_job_id, {
                        run_type: "external_bulk",
                        trigger_type: "external",
                        status: "success",
                        source_row_count: supplierCount,
                        target_row_count: supplierCount,
                        rows_loaded: supplierCount,
                        run_scope: "demo seeded staging data",
                      });
                    }, "Supplier external run recorded.")}
                    disabled={!!busy || !supplier.migration_job_id}
                  >
                    <PlayCircle size={15} />
                    Create External Run Record
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => runAction("supplier-validate", () => {
                      if (!supplier.latest_run_id) throw new Error("Create a supplier run record first.");
                      return validateMigrationTarget(supplier.latest_run_id);
                    }, "Supplier target validation completed.")}
                    disabled={!!busy || !supplier.latest_run_id}
                  >
                    <ShieldCheck size={15} />
                    Validate Supplier Target
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => runAction("supplier-model", () => createDataModelFromTemplate("jde_supplier", {}), "Supplier Type B model is ready.")}
                    disabled={!!busy || supplier.data_model_exists}
                  >
                    <CheckCircle2 size={15} />
                    Create Supplier Type B Model
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => runAction("supplier-preview", async () => {
                      if (!supplier.data_model_id) throw new Error("Create the supplier Type B model first.");
                      const preview = await previewSavedTypeBModel(supplier.data_model_id, 5);
                      return rowsFromPreview(preview);
                    }, "Supplier preview loaded.")}
                    disabled={!!busy || !supplier.data_model_id}
                  >
                    <Eye size={15} />
                    Preview Supplier Model
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => runAction("supplier-outbound", () => outboundByKey("supplier", "SUP-1001"), "Outbound supplier API tested.")}
                    disabled={!!busy || !supplier.outbound_api_available}
                  >
                    Test GET /outbound/supplier/SUP-1001
                  </Button>
                  <Link className="inline-flex h-8 items-center rounded-md border border-neutral-300 px-3 text-sm hover:bg-neutral-50" href="/transactions">
                    Open Transactions
                  </Link>
                </div>
              </CardBody>
            </Card>
          )}

          {poSummary && (
            <Card>
              <CardHeader title="Purchase Order Summary Flow" subtitle="Curated view -> Type B model -> outbound API" />
              <CardBody className="space-y-4">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <StatusBox title="View Job" value={poSummary.migration_job_exists} detail={poSummary.migration_job_status} />
                  <StatusBox title="Latest Run" value={poSummary.latest_run_status} detail={poSummary.latest_run_id} />
                  <StatusBox title="Validation" value={poSummary.target_validation_status} detail={`${poSummary.target_row_count ?? "-"} target rows`} />
                  <StatusBox title="Type B Model" value={poSummary.data_model_exists} detail={poSummary.data_model_status} />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => runAction("po-job", () => createMigrationJobFromTemplate("jde_purchase_order_summary_view", {}), "Purchase order summary validation job is ready.")}
                    disabled={!!busy || poSummary.migration_job_exists}
                  >
                    <FilePlus2 size={15} />
                    Create Summary View Job
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => runAction("po-run", () => {
                      if (!poSummary.migration_job_id) throw new Error("Create the summary view job first.");
                      return createMigrationRun(poSummary.migration_job_id, {
                        run_type: "validation_only",
                        trigger_type: "manual",
                        status: "success",
                        target_row_count: poCount,
                        rows_loaded: poCount,
                        run_scope: "validate curated purchase order summary view",
                      });
                    }, "Purchase order summary run recorded.")}
                    disabled={!!busy || !poSummary.migration_job_id}
                  >
                    <PlayCircle size={15} />
                    Create View Run Record
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => runAction("po-validate", () => {
                      if (!poSummary.latest_run_id) throw new Error("Create a summary view run record first.");
                      return validateMigrationTarget(poSummary.latest_run_id);
                    }, "Purchase order summary target validation completed.")}
                    disabled={!!busy || !poSummary.latest_run_id}
                  >
                    <ShieldCheck size={15} />
                    Validate Summary View
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => runAction("po-model", () => createDataModelFromTemplate("jde_purchase_order_summary", {}), "Purchase order summary Type B model is ready.")}
                    disabled={!!busy || poSummary.data_model_exists}
                  >
                    <CheckCircle2 size={15} />
                    Create Summary Type B Model
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => runAction("po-outbound", () => outboundByKey("purchase_order_summary", "PO-2026-0001"), "Outbound purchase order summary API tested.")}
                    disabled={!!busy || !poSummary.outbound_api_available}
                  >
                    Test GET /outbound/purchase_order_summary/PO-2026-0001
                  </Button>
                </div>
              </CardBody>
            </Card>
          )}

          <PreviewPanel title="Latest Action Result" data={result} />
        </div>
      )}
    </>
  );
}

function StatusBox({ title, value, detail }: { title: string; value?: string | boolean | null; detail?: string | null }) {
  return (
    <div className="rounded-md border border-neutral-100 bg-neutral-50 px-3 py-2">
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</div>
      <Badge tone={tone(value)}>{label(value)}</Badge>
      {detail && <div className="mt-1 truncate text-xs text-neutral-500" title={detail}>{detail}</div>}
    </div>
  );
}
