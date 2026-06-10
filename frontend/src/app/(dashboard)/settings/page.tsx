"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Palette, ShieldCheck, SlidersHorizontal, UserRound, Users as UsersIcon } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/Table";
import { useAuth } from "@/components/auth/AuthProvider";
import { NAV_ITEMS } from "@/lib/nav";
import {
  ApiError,
  getUserPreferences,
  listUsers,
  setUserPreferences,
  type NavConfig,
  type User,
} from "@/lib/api";
// Relocated into Settings as sub-tabs (the old top-level nav items were removed).
import UsersPage from "@/app/(dashboard)/users/page";
import ProfilePage from "@/app/(dashboard)/profile/page";
import DesignSystemPage from "@/app/(dashboard)/design-system/page";
import { RolePermissionsTab } from "@/components/settings/RolePermissionsTab";

type TabRow = { href: string; label: string; baseLabel: string; visible: boolean };
type Section = "access" | "users" | "role" | "profile" | "design";

function buildRows(navConfig: NavConfig): TabRow[] {
  const rows = NAV_ITEMS.map((it) => {
    const o = navConfig[it.href];
    return { href: it.href, baseLabel: it.label, label: o?.label ?? it.label, visible: o?.visible !== false };
  });
  rows.sort((a, b) => {
    const oa = navConfig[a.href]?.order;
    const ob = navConfig[b.href]?.order;
    if (oa == null && ob == null) return 0;
    if (oa == null) return 1;
    if (ob == null) return -1;
    return oa - ob;
  });
  return rows;
}

export default function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [section, setSection] = useState<Section>("profile");

  // landing sub-tab: ?tab= deep-link (e.g. avatar → /settings?tab=profile), else admins start on
  // "access", others on "profile". window.location avoids useSearchParams' Suspense requirement.
  useEffect(() => {
    let tab: string | null = null;
    try {
      tab = new URLSearchParams(window.location.search).get("tab");
    } catch {
      /* ignore */
    }
    if (tab && ["access", "users", "role", "profile", "design"].includes(tab)) {
      setSection(tab as Section);
    } else {
      setSection(isAdmin ? "access" : "profile");
    }
  }, [isAdmin]);

  // ---- Tabs & access (per user) — admin ----
  const [users, setUsers] = useState<User[]>([]);
  const [targetId, setTargetId] = useState<string>("");
  const [rows, setRows] = useState<TabRow[]>([]);
  const [tabMsg, setTabMsg] = useState<string | null>(null);
  const [tabErr, setTabErr] = useState<string | null>(null);
  const [savingTabs, setSavingTabs] = useState(false);

  useEffect(() => {
    if (!isAdmin) return;
    listUsers()
      .then((u) => {
        setUsers(u);
        setTargetId((cur) => cur || (u[0]?.id ?? ""));
      })
      .catch((e) => setTabErr(e instanceof ApiError ? e.message : "Failed to load users"));
  }, [isAdmin]);

  const loadTarget = useCallback(async (uid: string) => {
    if (!uid) return;
    setTabMsg(null);
    setTabErr(null);
    try {
      const pref = await getUserPreferences(uid);
      setRows(buildRows(pref.nav_config || {}));
    } catch (e) {
      setTabErr(e instanceof ApiError ? e.message : "Failed to load preferences");
    }
  }, []);

  useEffect(() => {
    if (targetId) void loadTarget(targetId);
  }, [targetId, loadTarget]);

  const move = (idx: number, dir: -1 | 1) => {
    setRows((rs) => {
      const next = [...rs];
      const j = idx + dir;
      if (j < 0 || j >= next.length) return rs;
      [next[idx], next[j]] = [next[j], next[idx]];
      return next;
    });
  };

  const saveTabs = async () => {
    if (!targetId) return;
    setSavingTabs(true);
    setTabMsg(null);
    setTabErr(null);
    const navConfig: NavConfig = {};
    rows.forEach((r, idx) => {
      navConfig[r.href] = { visible: r.visible, label: r.label, order: idx };
    });
    try {
      await setUserPreferences(targetId, { nav_config: navConfig });
      setTabMsg("Saved. The user sees these tabs on next load.");
    } catch (e) {
      setTabErr(e instanceof ApiError ? e.message : "Save failed");
    } finally {
      setSavingTabs(false);
    }
  };

  const targetUser = useMemo(() => users.find((u) => u.id === targetId), [users, targetId]);

  const TABS: { key: Section; label: string; icon: typeof UsersIcon; adminOnly?: boolean }[] = [
    { key: "access", label: "Tabs & access", icon: SlidersHorizontal, adminOnly: true },
    { key: "users", label: "Users", icon: UsersIcon, adminOnly: true },
    { key: "role", label: "Role", icon: ShieldCheck, adminOnly: true },
    { key: "profile", label: "Profile", icon: UserRound },
    { key: "design", label: "Design System", icon: Palette },
  ];
  const visibleTabs = TABS.filter((t) => !t.adminOnly || isAdmin);

  return (
    <div className="space-y-4">
      <PageHeader title="Settings" subtitle="Tabs & access, Users, Profile, Design System — and theme (sidebar toggle)." />

      {/* sub-tab bar */}
      <div className="flex flex-wrap items-center gap-1 border-b border-neutral-200 dark:border-neutral-800">
        {visibleTabs.map((t) => {
          const Icon = t.icon;
          const active = section === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setSection(t.key)}
              className={
                "inline-flex items-center gap-2 rounded-t-md px-3 py-2 text-sm font-medium transition-colors " +
                (active
                  ? "border-b-2 border-brand text-brand"
                  : "text-neutral-600 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800")
              }
            >
              <Icon size={15} /> {t.label}
            </button>
          );
        })}
      </div>

      {section === "access" && isAdmin && (
        <Card>
          <CardHeader
            title={
              <span className="inline-flex items-center gap-2">
                <SlidersHorizontal size={16} /> Tabs & access (per user)
              </span>
            }
            subtitle="Show/hide, rename and reorder a user's sidebar tabs. Admin-only routes are also enforced by the backend (403)."
            action={
              <Select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.username} ({u.role})
                  </option>
                ))}
              </Select>
            }
          />
          <CardBody>
            {tabErr ? <p className="mb-2 text-sm text-danger">{tabErr}</p> : null}
            {tabMsg ? <p className="mb-2 text-sm text-success">{tabMsg}</p> : null}
            <Table>
              <THead>
                <TR>
                  <TH>Order</TH>
                  <TH>Route</TH>
                  <TH>Visible</TH>
                  <TH>Display label</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((r, idx) => (
                  <TR key={r.href}>
                    <TD>
                      <div className="flex items-center gap-1">
                        <button
                          className="rounded p-1 text-neutral-400 hover:bg-neutral-100 disabled:opacity-30 dark:hover:bg-neutral-800"
                          onClick={() => move(idx, -1)}
                          disabled={idx === 0}
                          title="Move up"
                        >
                          <ArrowUp size={14} />
                        </button>
                        <button
                          className="rounded p-1 text-neutral-400 hover:bg-neutral-100 disabled:opacity-30 dark:hover:bg-neutral-800"
                          onClick={() => move(idx, 1)}
                          disabled={idx === rows.length - 1}
                          title="Move down"
                        >
                          <ArrowDown size={14} />
                        </button>
                      </div>
                    </TD>
                    <TD className="font-mono text-xs text-neutral-500">{r.href}</TD>
                    <TD>
                      <input
                        type="checkbox"
                        checked={r.visible}
                        onChange={(e) =>
                          setRows((rs) => rs.map((x) => (x.href === r.href ? { ...x, visible: e.target.checked } : x)))
                        }
                      />
                    </TD>
                    <TD>
                      <Input
                        value={r.label}
                        onChange={(e) =>
                          setRows((rs) => rs.map((x) => (x.href === r.href ? { ...x, label: e.target.value } : x)))
                        }
                        className="max-w-[14rem]"
                      />
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <div className="mt-3">
              <Button onClick={saveTabs} disabled={savingTabs || !targetId}>
                {savingTabs ? "Saving…" : `Save tabs for ${targetUser?.username ?? "user"}`}
              </Button>
            </div>
          </CardBody>
        </Card>
      )}

      {section === "users" && isAdmin && <UsersPage />}
      {section === "role" && isAdmin && <RolePermissionsTab />}
      {section === "profile" && <ProfilePage />}
      {section === "design" && <DesignSystemPage />}
    </div>
  );
}
