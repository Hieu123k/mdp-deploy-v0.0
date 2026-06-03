"use client";

import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { useAuth } from "@/components/auth/AuthProvider";
import { apiPath } from "@/lib/api";
import { ShieldCheck, LogOut } from "lucide-react";

export default function ProfilePage() {
  const { user, logout } = useAuth();
  const router = useRouter();

  async function onLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <>
      <PageHeader
        title="Profile"
        subtitle={`Public API: ${apiPath("/auth/me")} · Backend route: /auth/me.`}
      />
      <Card className="max-w-md">
        <CardBody className="space-y-4">
          <div className="flex items-center gap-2 rounded-md bg-success/10 px-3 py-2 text-sm text-success">
            <ShieldCheck size={16} /> Authenticated
          </div>
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-brand text-xl font-bold text-white">
              {(user?.username || "?").slice(0, 1).toUpperCase()}
            </div>
            <div>
              <p className="text-lg font-semibold text-neutral-900">{user?.full_name || user?.username || "—"}</p>
              <p className="text-sm text-neutral-500">{user?.email || "—"}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-neutral-500">Role:</span>
            <Badge tone="info">{user?.role || "—"}</Badge>
          </div>
          <div className="border-t border-neutral-100 pt-4">
            <Button variant="destructive" onClick={onLogout}>
              <LogOut size={16} /> Log out
            </Button>
          </div>
        </CardBody>
      </Card>
    </>
  );
}
