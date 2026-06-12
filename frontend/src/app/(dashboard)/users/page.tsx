"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import { useAuth } from "@/components/auth/AuthProvider";
import {
  ApiError,
  apiPath,
  createUser,
  deleteUser,
  listUsers,
  updateUser,
  USER_ROLES,
  type User,
} from "@/lib/api";

type Mode = "new" | "edit" | null;

export default function UsersPage() {
  const { user } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>(null);
  const [editing, setEditing] = useState<User | null>(null);
  const [delUser, setDelUser] = useState<User | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setUsers(await listUsers());
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    reload();
  }, [reload]);

  const [fUsername, setFUsername] = useState("");
  const [fEmail, setFEmail] = useState("");
  const [fFull, setFFull] = useState("");
  const [fRole, setFRole] = useState("viewer");
  const [fActive, setFActive] = useState(true);
  const [fPwd, setFPwd] = useState("");
  const [busy, setBusy] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);

  function openNew() {
    setEditing(null);
    setFUsername("");
    setFEmail("");
    setFFull("");
    setFRole("viewer");
    setFActive(true);
    setFPwd("");
    setFormErr(null);
    setMode("new");
  }
  function openEdit(u: User) {
    setEditing(u);
    setFUsername(u.username);
    setFEmail(u.email);
    setFFull(u.full_name || "");
    setFRole(u.role);
    setFActive(u.is_active);
    setFPwd("");
    setFormErr(null);
    setMode("edit");
  }

  async function save() {
    setFormErr(null);
    if (mode === "new") {
      if (!fUsername.trim()) {
        setFormErr("Username is required.");
        return;
      }
      if (fPwd.length < 6) {
        setFormErr("Password must be at least 6 characters.");
        return;
      }
    } else if (fPwd && fPwd.length < 6) {
      setFormErr("Password must be at least 6 characters.");
      return;
    }
    setBusy(true);
    try {
      if (mode === "new") {
        await createUser({
          username: fUsername.trim(),
          email: fEmail.trim(),
          password: fPwd,
          full_name: fFull.trim() || undefined,
          role: fRole,
          is_active: fActive,
        });
      } else if (editing) {
        await updateUser(editing.id, {
          email: fEmail.trim(),
          full_name: fFull.trim() || undefined,
          role: fRole,
          is_active: fActive,
          ...(fPwd ? { password: fPwd } : {}),
        });
      }
      setMode(null);
      await reload();
    } catch (e) {
      setFormErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function doDelete() {
    if (!delUser) return;
    setBusy(true);
    try {
      await deleteUser(delUser.id);
      setDelUser(null);
      await reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Users"
        subtitle={`Public API: ${apiPath("/users")} · Backend route: /users.`}
        action={<Button onClick={openNew}>New User</Button>}
      />
      {err && <p className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
      <Card>
        <CardHeader title="All users" subtitle={`${users.length} total`} />
        <CardBody>
          {loading ? (
            <p className="text-sm text-neutral-400">Loading...</p>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>User Name</TH>
                  <TH>Full name</TH>
                  <TH>Email</TH>
                  <TH>Role</TH>
                  <TH>Status</TH>
                  <TH>Actions</TH>
                </TR>
              </THead>
              <TBody>
                {users.map((u) => (
                  <TR key={u.id}>
                    <TD className="font-medium">{u.username}</TD>
                    <TD>{u.full_name || "-"}</TD>
                    <TD>{u.email}</TD>
                    <TD>
                      <Badge tone="info">{u.role}</Badge>
                    </TD>
                    <TD>
                      <Badge tone={u.is_active ? "success" : "neutral"}>
                        {u.is_active ? "active" : "disabled"}
                      </Badge>
                    </TD>
                    <TD>
                      <div className="flex gap-2">
                        <Button size="sm" variant="secondary" onClick={() => openEdit(u)}>
                          Edit
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setDelUser(u)}
                          disabled={u.id === user?.id}
                        >
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
        open={mode !== null}
        onClose={() => setMode(null)}
        title={mode === "new" ? "New User" : "Edit User"}
        footer={
          <>
            <Button variant="ghost" onClick={() => setMode(null)}>
              Cancel
            </Button>
            <Button onClick={save} disabled={busy}>
              {busy ? "Saving..." : "Save"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {formErr && <p className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{formErr}</p>}
          <Input
            label="User Name"
            requiredMark
            value={fUsername}
            disabled={mode === "edit"}
            onChange={(e) => setFUsername(e.target.value)}
            placeholder="jdoe"
          />
          <Input
            label="Full name"
            value={fFull}
            onChange={(e) => setFFull(e.target.value)}
            placeholder="John Doe"
          />
          <Input
            label="Email"
            requiredMark
            value={fEmail}
            onChange={(e) => setFEmail(e.target.value)}
            placeholder="jdoe@avenue.local"
          />
          <Select label="Role" value={fRole} onChange={(e) => setFRole(e.target.value)}>
            {USER_ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Select>
          <Input
            label={mode === "edit" ? "Password (blank = keep current)" : "Password"}
            requiredMark={mode !== "edit"}
            type="password"
            value={fPwd}
            onChange={(e) => setFPwd(e.target.value)}
            placeholder="********"
          />
          <label className="flex items-center gap-2 text-sm text-neutral-700">
            <input type="checkbox" checked={fActive} onChange={(e) => setFActive(e.target.checked)} />
            Account enabled
          </label>
        </div>
      </Modal>

      <Modal
        open={delUser !== null}
        onClose={() => setDelUser(null)}
        title="Delete user"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDelUser(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={doDelete} disabled={busy}>
              Delete
            </Button>
          </>
        }
      >
        <p className="text-sm text-neutral-600">
          Delete <span className="font-semibold">{delUser?.username}</span>? This cannot be undone.
        </p>
      </Modal>
    </>
  );
}
