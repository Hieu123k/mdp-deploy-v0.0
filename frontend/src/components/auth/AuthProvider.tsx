"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { authLogout, authMe, getToken, type AuthUser } from "@/lib/api";

type AuthState = {
  user: AuthUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};

const Ctx = createContext<AuthState>({
  user: null,
  loading: true,
  refresh: async () => {},
  logout: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    // No token means the user is not authenticated; skip the network call.
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await authMe()); // GET /auth/me with Bearer; 401 means invalid or expired token.
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    authLogout(); // Drop the JWT. MDP is stateless, so no server call is needed.
    setUser(null);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <Ctx.Provider value={{ user, loading, refresh, logout }}>{children}</Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
