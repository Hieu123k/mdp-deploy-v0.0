"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "./AuthProvider";

/** Wrap routes that require sign-in. Unauthenticated users are redirected to /login. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading)
    return (
      <div className="flex h-screen items-center justify-center text-sm text-neutral-500">
        Checking session…
      </div>
    );
  if (!user) return null;
  return <>{children}</>;
}
