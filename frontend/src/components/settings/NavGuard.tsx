"use client";

import { useEffect, useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import { NAV_ITEMS } from "@/lib/nav";
import { useAuth } from "@/components/auth/AuthProvider";
import { usePreferences } from "@/components/settings/PreferencesProvider";

/**
 * Client route-guard: if the current route maps to a tab that is hidden for this user (per-user
 * nav config) or admin-only and the user is not an admin, redirect to the dashboard. This is the
 * UX layer; the security layer is `require_role` on the backend (which 403s regardless of the UI).
 */
export function NavGuard({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const { prefs, loaded } = usePreferences();
  const pathname = usePathname();
  const router = useRouter();

  const blocked = useMemo(() => {
    if (!loaded || !user) return false;
    const item = NAV_ITEMS.find(
      (i) => pathname === i.href || pathname.startsWith(i.href + "/"),
    );
    if (!item) return false;
    if (item.adminOnly && user.role !== "admin") return true;
    if (prefs.nav_config?.[item.href]?.visible === false) return true;
    return false;
  }, [pathname, prefs, loaded, user]);

  useEffect(() => {
    if (blocked) router.replace("/");
  }, [blocked, router]);

  if (blocked) return null;
  return <>{children}</>;
}
