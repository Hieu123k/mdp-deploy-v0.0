"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  getMyPreferences,
  updateMyPreferences,
  type NavConfig,
  type Preferences,
} from "@/lib/api";
import { useAuth } from "@/components/auth/AuthProvider";

type PrefState = {
  prefs: Preferences;
  loaded: boolean;
  theme: string;
  setTheme: (t: string) => void;
  refresh: () => Promise<void>;
};

const DEFAULT: Preferences = { theme: "light", nav_config: {} };
const THEME_KEY = "mdp_theme";

const Ctx = createContext<PrefState>({
  prefs: DEFAULT,
  loaded: false,
  theme: "light",
  setTheme: () => {},
  refresh: async () => {},
});

function applyTheme(theme: string) {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const [prefs, setPrefs] = useState<Preferences>(DEFAULT);
  const [loaded, setLoaded] = useState(false);
  const lastUser = useRef<string | null>(null);

  // Instant apply from localStorage (no flash) before the server prefs arrive.
  useEffect(() => {
    try {
      const cached = window.localStorage.getItem(THEME_KEY);
      if (cached) {
        setPrefs((p) => ({ ...p, theme: cached }));
        applyTheme(cached);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const p = await getMyPreferences();
      setPrefs(p);
      applyTheme(p.theme);
      try {
        window.localStorage.setItem(THEME_KEY, p.theme);
      } catch {
        /* ignore */
      }
    } catch {
      /* keep cached/default on failure */
    } finally {
      setLoaded(true);
    }
  }, []);

  // Sync from the server once per signed-in user.
  useEffect(() => {
    if (user && lastUser.current !== user.id) {
      lastUser.current = user.id;
      void refresh();
    }
    if (!user) {
      lastUser.current = null;
      setLoaded(false);
    }
  }, [user, refresh]);

  const setTheme = useCallback((t: string) => {
    setPrefs((p) => ({ ...p, theme: t }));
    applyTheme(t);
    try {
      window.localStorage.setItem(THEME_KEY, t);
    } catch {
      /* ignore */
    }
    // Persist server-side (cross-device); fire-and-forget.
    void updateMyPreferences({ theme: t }).catch(() => {});
  }, []);

  return (
    <Ctx.Provider value={{ prefs, loaded, theme: prefs.theme, setTheme, refresh }}>
      {children}
    </Ctx.Provider>
  );
}

export const usePreferences = () => useContext(Ctx);

/** Apply a per-user nav override map onto a base nav list: hide, rename and reorder. */
export function applyNavConfig<T extends { href: string; label: string }>(
  items: T[],
  navConfig: NavConfig | undefined,
): T[] {
  if (!navConfig) return items;
  return items
    .filter((it) => navConfig[it.href]?.visible !== false)
    .map((it) => {
      const o = navConfig[it.href];
      return o?.label ? { ...it, label: o.label } : it;
    })
    .sort((a, b) => {
      const oa = navConfig[a.href]?.order;
      const ob = navConfig[b.href]?.order;
      if (oa == null && ob == null) return 0;
      if (oa == null) return 1;
      if (ob == null) return -1;
      return oa - ob;
    });
}
