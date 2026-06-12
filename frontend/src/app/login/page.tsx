"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { useAuth } from "@/components/auth/AuthProvider";
import { ApiError, authLogin } from "@/lib/api";

export default function LoginPage() {
  const { user, loading, refresh } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Already signed in: leave /login
  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) {
      setErr("Enter your username and password.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await authLogin(username.trim(), password); // POST /auth/login stores the JWT
      await refresh(); // GET /auth/me with the new Bearer token
      router.replace("/");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="login-bg flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-lg bg-white p-8 shadow-xl">
        <div className="mb-6 flex flex-col items-center">
          <div className="w-fit text-center">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/avenue-logo-full.svg"
              alt="Avenue MDP"
              className="mx-auto mb-3 block h-auto w-4/5 object-contain"
            />
          </div>
          <p className="mt-1 text-sm text-neutral-400">Sign in to continue</p>
        </div>

        <form className="space-y-4" onSubmit={onSubmit}>
          {err && <p className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
          <Input
            label="Username"
            requiredMark
            name="username"
            placeholder="admin"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <Input
            label="Password"
            requiredMark
            name="password"
            type="password"
            placeholder="Password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Signing in..." : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}
