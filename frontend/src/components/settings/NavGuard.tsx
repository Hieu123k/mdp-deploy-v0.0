"use client";

import { useEffect, useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import { NAV_ITEMS } from "@/lib/nav";
import { useAuth } from "@/components/auth/AuthProvider";
import { usePreferences } from "@/components/settings/PreferencesProvider";

// Routes relocated INTO Settings (report 30): the old top-level routes redirect there so deep
// links and bookmarks land on the new home.
const RELOCATED: Record<string, string> = {
  "/users": "/settings",
  "/profile": "/settings",
  "/design-system": "/settings",
};

/**
 * Client route-guard: if the current route maps to a tab that is hidden for this user (per-user
 * nav config) or admin-only and the user is not an admin, redirect to the dashboard. Also redirects
 * relocated routes into Settings. This is the UX layer; the security layer is `require_role` on the
 * backend (which 403s regardless of the UI).
 */
export function NavGuard({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const { prefs, loaded } = usePreferences();
  const pathname = usePathname();
  const router = useRouter();

  const target = useMemo(() => {
    if (!loaded || !user) return null;
    if (RELOCATED[pathname]) return RELOCATED[pathname];
    const item = NAV_ITEMS.find((i) => pathname === i.href || pathname.startsWith(i.href + "/"));
    if (!item) return null;
    if (item.adminOnly && user.role !== "admin") return "/";
    if (prefs.nav_config?.[item.href]?.visible === false) return "/";
    return null;
  }, [pathname, prefs, loaded, user]);

  useEffect(() => {
    if (target) router.replace(target);
  }, [target, router]);

  if (target) return null;
  return <>{children}</>;
}
