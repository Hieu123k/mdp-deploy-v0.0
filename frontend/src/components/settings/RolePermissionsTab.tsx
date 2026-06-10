"use client";

import { useEffect, useState } from "react";
import { Lock } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import { ApiError, getRolePermissions, saveRolePermissions, type PermissionMatrix } from "@/lib/api";

const ROLE_ORDER = ["admin", "data_engineer", "api_manager", "viewer"];

/** Settings → Role: the role × permission grid (admin-only). This is the role→can-do layer enforced
 *  by the backend (403); admin is implicit-full (locked). users.manage / role.manage are admin-only
 *  (locked off for other roles) so the UI can't escalate — the backend rejects it too. */
export function RolePermissionsTab() {
  const [matrix, setMatrix] = useState<PermissionMatrix | null>(null);
  const [draft, setDraft] = useState<Record<string, Record<string, boolean>>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getRolePermissions()
      .then((m) => {
        setMatrix(m);
        setDraft(JSON.parse(JSON.stringify(m.roles)));
      })
      .catch((e) => setMsg(e instanceof ApiError ? e.message : String(e)));
  }, []);

  if (!matrix) {
    return (
      <Card>
        <CardBody>{msg ?? "Loading…"}</CardBody>
      </Card>
    );
  }

  const roles = ROLE_ORDER.filter((r) => r in matrix.roles);
  const adminOnly = new Set(matrix.admin_only);
  const toggle = (role: string, key: string, val: boolean) =>
    setDraft((d) => ({ ...d, [role]: { ...d[role], [key]: val } }));

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      // Only send editable (non-admin) roles — admin is implicit-full and never written.
      const payload = Object.fromEntries(roles.filter((r) => r !== "admin").map((r) => [r, draft[r]]));
      const m = await saveRolePermissions(payload);
      setMatrix(m);
      setDraft(JSON.parse(JSON.stringify(m.roles)));
      setMsg("Saved. Backend enforces these on the next request (403 when missing).");
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Role permissions"
        subtitle="What each role may do — enforced by the backend (403), not just hidden in the UI. Admin = full. 'users.manage' / 'role.manage' are admin-only."
        action={
          <Button onClick={() => void save()} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        }
      />
      <CardBody>
        {msg && <p className="mb-2 text-sm text-neutral-600 dark:text-neutral-300">{msg}</p>}
        <div className="overflow-x-auto">
          <Table>
            <THead>
              <TR>
                <TH>Permission</TH>
                {roles.map((r) => (
                  <TH key={r} className="text-center capitalize">
                    {r.replace("_", " ")}
                  </TH>
                ))}
              </TR>
            </THead>
            <TBody>
              {matrix.permission_keys.map((key) => (
                <TR key={key}>
                  <TD className="whitespace-nowrap font-mono text-xs">
                    {key}
                    {adminOnly.has(key) && (
                      <span className="ml-1 inline-flex items-center align-middle text-warning" title="admin-only — cannot be granted to other roles">
                        <Lock size={11} />
                      </span>
                    )}
                  </TD>
                  {roles.map((role) => {
                    const locked = role === "admin" || adminOnly.has(key);
                    const checked = role === "admin" ? true : !!draft[role]?.[key];
                    return (
                      <TD key={role} className="text-center">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={locked}
                          onChange={(e) => toggle(role, key, e.target.checked)}
                          aria-label={`${role} ${key}`}
                        />
                      </TD>
                    );
                  })}
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      </CardBody>
    </Card>
  );
}
