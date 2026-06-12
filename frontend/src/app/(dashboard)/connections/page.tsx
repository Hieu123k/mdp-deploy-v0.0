"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import {
  ApiError,
  apiPath,
  CONNECTION_TYPES,
  createConnection,
  deleteConnection,
  listConnections,
  testConnection,
  type ConnType,
  type Connection,
} from "@/lib/api";

const DB_TYPES = ["postgresql", "oracle", "sqlserver"];

function testTone(s: string | null): BadgeTone {
  if (s === "success") return "success";
  if (s === "error") return "danger";
  return "neutral";
}

export default function ConnectionsPage() {
  const [conns, setConns] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setConns(await listConnections());
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
  const [type, setType] = useState<ConnType>("postgresql");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [database, setDatabase] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [configJson, setConfigJson] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);

  function openNew() {
    setName("");
    setType("postgresql");
    setHost("");
    setPort("");
    setDatabase("");
    setUsername("");
    setPassword("");
    setBaseUrl("");
    setConfigJson("");
    setDesc("");
    setFormErr(null);
    setOpen(true);
  }

  const isDb = DB_TYPES.includes(type);
  const isRest = type === "rest_api";
  const isMqtt = type === "mqtt";
  const isOracle = type === "oracle";

  function changeType(next: ConnType) {
    setType(next);
    if (next === "oracle") {
      setPort((current) => current || "1521");
      setConfigJson((current) =>
        current ||
        JSON.stringify(
          {
            oracle_connect_mode: "service_name",
            service_name: "",
            schema: "PRODDTA",
          },
          null,
          2,
        ),
      );
    } else if (next === "postgresql") {
      setPort((current) => current || "5432");
    } else if (next === "sqlserver") {
      setPort((current) => current || "1433");
    } else if (next === "mqtt") {
      setPort((current) => current || "1883");
    }
  }

  async function save() {
    setFormErr(null);
    if (!name.trim()) {
      setFormErr("Name is required.");
      return;
    }
    let parsedConfig: Record<string, unknown> | null = null;
    if (configJson.trim()) {
      try {
        parsedConfig = JSON.parse(configJson);
      } catch {
        setFormErr("Config JSON is invalid.");
        return;
      }
    }
    const body: Record<string, unknown> = { name: name.trim(), type, description: desc.trim() || null };
    if (isDb || isMqtt) {
      body.host = host.trim();
      body.port = port ? Number(port) : null;
    }
    if (isDb) {
      body.database_name = database.trim();
      body.username = username.trim();
      if (password) body.password = password;
    }
    if (parsedConfig) body.config = parsedConfig;
    if (isRest) body.base_url = baseUrl.trim();
    setBusy(true);
    try {
      await createConnection(body);
      setOpen(false);
      await reload();
    } catch (e) {
      setFormErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runTest(c: Connection) {
    setTesting(c.id);
    setErr(null);
    try {
      await testConnection(c.id);
      await reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setTesting(null);
    }
  }
  async function remove(c: Connection) {
    try {
      await deleteConnection(c.id);
      await reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <>
      <PageHeader
        title="Connections"
        subtitle={`Public API: ${apiPath("/connections")} · Backend route: /connections.`}
        action={<Button onClick={openNew}>New Connection</Button>}
      />
      {err && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
      <Card>
        <CardHeader title="All connections" subtitle={`${conns.length} total`} />
        <CardBody>
          {loading ? (
            <p className="text-sm text-neutral-400">Loading...</p>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Type</TH>
                  <TH>Target</TH>
                  <TH>Status</TH>
                  <TH>Last test</TH>
                  <TH>Actions</TH>
                </TR>
              </THead>
              <TBody>
                {conns.map((c) => (
                  <TR key={c.id}>
                    <TD className="font-medium">{c.name}</TD>
                    <TD>
                      <Badge tone="info">{c.type}</Badge>
                    </TD>
                    <TD className="font-mono text-xs">
                      {c.base_url || (c.host ? `${c.host}${c.port ? ":" + c.port : ""}${c.database_name ? "/" + c.database_name : ""}` : "-")}
                    </TD>
                    <TD>
                      <Badge tone={c.status === "active" ? "success" : "neutral"}>{c.status}</Badge>
                    </TD>
                    <TD>
                      <Badge tone={testTone(c.last_test_status)}>{c.last_test_status || "untested"}</Badge>
                      {c.last_test_message && (
                        <span className="ml-2 text-xs text-neutral-400">{c.last_test_message.slice(0, 40)}</span>
                      )}
                    </TD>
                    <TD>
                      <div className="flex gap-2">
                        <Button size="sm" variant="secondary" onClick={() => runTest(c)} disabled={testing === c.id}>
                          {testing === c.id ? "Testing..." : "Test"}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => remove(c)}>
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

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="New Connection"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={save} disabled={busy}>
              {busy ? "Saving..." : "Create"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {formErr && <p className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{formErr}</p>}
          <div className="grid grid-cols-2 gap-3">
            <Input label="Name" requiredMark value={name} onChange={(e) => setName(e.target.value)} placeholder="jde-prod" />
            <Select label="Type" requiredMark value={type} onChange={(e) => changeType(e.target.value as ConnType)}>
              {CONNECTION_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </div>
          {(isDb || isMqtt) && (
            <div className="grid grid-cols-2 gap-3">
              <Input label="Host" requiredMark value={host} onChange={(e) => setHost(e.target.value)} placeholder="10.0.0.5" />
              <Input
                label="Port"
                requiredMark
                value={port}
                onChange={(e) => setPort(e.target.value)}
                placeholder={isMqtt ? "1883" : isOracle ? "1521" : type === "sqlserver" ? "1433" : "5432"}
              />
            </div>
          )}
          {isDb && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Input
                  label={isOracle ? "Service name / Database" : "Database"}
                  requiredMark
                  value={database}
                  onChange={(e) => setDatabase(e.target.value)}
                  placeholder={isOracle ? "JDEPRD" : "prod"}
                  hint={isOracle ? "Default Oracle connect mode uses this as service_name." : undefined}
                />
                <Input label="Username" requiredMark value={username} onChange={(e) => setUsername(e.target.value)} placeholder="reader" />
              </div>
              <Input
                label="Password (write-only)"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="********"
              />
              {isOracle && (
                <p className="rounded-md bg-info/10 px-3 py-2 text-xs text-info">
                  For Oracle JDE, enter host, port 1521, service name, schema such as PRODDTA, username and password.
                  python-oracledb thin mode is used by default.
                </p>
              )}
            </>
          )}
          {isRest && (
            <Input label="Base URL" requiredMark value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com" />
          )}
          {(isDb || isMqtt) && (
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-neutral-700">Config JSON (optional)</span>
              <textarea
                value={configJson}
                onChange={(e) => setConfigJson(e.target.value)}
                placeholder={
                  isOracle
                    ? '{\n  "oracle_connect_mode": "service_name",\n  "service_name": "JDEPRD",\n  "schema": "PRODDTA"\n}'
                    : "{}"
                }
                className="min-h-28 w-full rounded-md border border-neutral-300 bg-white px-3 py-2 font-mono text-xs text-neutral-900 focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
              />
            </label>
          )}
          <Input label="Description (optional)" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="JDE production database" />
        </div>
      </Modal>
    </>
  );
}
