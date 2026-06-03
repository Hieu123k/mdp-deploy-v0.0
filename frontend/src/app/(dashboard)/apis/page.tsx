"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import {
  API_DIRECTIONS,
  ApiError,
  apiPath,
  createApiKey,
  deleteApiKey,
  listApiKeys,
  updateApiKey,
  type ApiKey,
} from "@/lib/api";

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<{ name: string; key: string } | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setKeys(await listApiKeys());
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    reload();
  }, [reload]);

  const [name, setName] = useState("");
  const [source, setSource] = useState("");
  const [dirs, setDirs] = useState<string[]>(["outbound"]);
  const [models, setModels] = useState("");
  const [busy, setBusy] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);

  function openNew() {
    setName("");
    setSource("");
    setDirs(["outbound"]);
    setModels("");
    setFormErr(null);
    setOpen(true);
  }
  function toggleDir(d: string) {
    setDirs((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d]));
  }

  async function save() {
    setFormErr(null);
    if (!name.trim()) {
      setFormErr("Name is required.");
      return;
    }
    if (dirs.length === 0) {
      setFormErr("Pick at least one direction.");
      return;
    }
    setBusy(true);
    try {
      const allowed_models = models.trim()
        ? models.split(",").map((s) => s.trim()).filter(Boolean)
        : null;
      const res = await createApiKey({
        name: name.trim(),
        source_system: source.trim() || undefined,
        allowed_directions: dirs,
        allowed_models,
      });
      setOpen(false);
      setCreated({ name: res.name, key: res.api_key });
      await reload();
    } catch (e) {
      setFormErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(k: ApiKey) {
    try {
      await updateApiKey(k.id, { is_active: !k.is_active });
      await reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }
  async function remove(k: ApiKey) {
    try {
      await deleteApiKey(k.id);
      await reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <>
      <PageHeader
        title="API Keys"
        subtitle={`Public API: ${apiPath("/api-keys")} · Backend route: /api-keys.`}
        action={<Button onClick={openNew}>New API Key</Button>}
      />
      {err && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
      <Card>
        <CardHeader title="All keys" subtitle={`${keys.length} total`} />
        <CardBody>
          {loading ? (
            <p className="text-sm text-neutral-400">Loading...</p>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Source</TH>
                  <TH>Prefix</TH>
                  <TH>Directions</TH>
                  <TH>Models</TH>
                  <TH>Status</TH>
                  <TH>Actions</TH>
                </TR>
              </THead>
              <TBody>
                {keys.map((k) => (
                  <TR key={k.id}>
                    <TD className="font-medium">{k.name}</TD>
                    <TD>{k.source_system || "-"}</TD>
                    <TD className="font-mono text-xs">{k.key_prefix}...</TD>
                    <TD>
                      <div className="flex gap-1">
                        {k.allowed_directions.map((d) => (
                          <Badge key={d} tone="info">
                            {d}
                          </Badge>
                        ))}
                      </div>
                    </TD>
                    <TD className="text-xs">{k.allowed_models?.join(", ") || "all"}</TD>
                    <TD>
                      <Badge tone={k.is_active ? "success" : "neutral"}>
                        {k.is_active ? "active" : "disabled"}
                      </Badge>
                    </TD>
                    <TD>
                      <div className="flex gap-2">
                        <Button size="sm" variant="secondary" onClick={() => toggleActive(k)}>
                          {k.is_active ? "Disable" : "Enable"}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => remove(k)}>
                          Delete
                        </Button>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>

      {/* Create modal */}
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="New API Key"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={save} disabled={busy}>
              {busy ? "Creating..." : "Create"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {formErr && <p className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{formErr}</p>}
          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="erp-integration" />
          <Input
            label="Source system (optional)"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="sap"
          />
          <div>
            <span className="mb-1 block text-sm text-neutral-700">Allowed directions</span>
            <div className="flex gap-4">
              {API_DIRECTIONS.map((d) => (
                <label key={d} className="flex items-center gap-2 text-sm text-neutral-700">
                  <input type="checkbox" checked={dirs.includes(d)} onChange={() => toggleDir(d)} /> {d}
                </label>
              ))}
            </div>
          </div>
          <Input
            label="Allowed models (comma-separated; blank = all)"
            value={models}
            onChange={(e) => setModels(e.target.value)}
            placeholder="demo_supplier, demo_widget"
          />
        </div>
      </Modal>

      {/* One-time key reveal */}
      <Modal
        open={created !== null}
        onClose={() => setCreated(null)}
        title="API key created"
        footer={
          <Button onClick={() => setCreated(null)}>Done</Button>
        }
      >
        <div className="space-y-3">
          <div className="flex items-center gap-2 rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
            Copy this key now - it is shown <strong>only once</strong> and cannot be retrieved later.
          </div>
          <p className="text-sm text-neutral-500">Key for <span className="font-semibold">{created?.name}</span>:</p>
          <code className="block break-all rounded-md bg-neutral-900 px-3 py-2 font-mono text-xs text-white">
            {created?.key}
          </code>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              if (created) navigator.clipboard?.writeText(created.key).catch(() => {});
            }}
          >
            Copy
          </Button>
        </div>
      </Modal>
    </>
  );
}
