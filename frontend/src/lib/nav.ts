import {
  LayoutDashboard,
  Boxes,
  Table2,
  Database,
  Plug,
  Repeat,
  Cable,
  ArrowRightLeft,
  Workflow,
  Radio,
  Settings,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  desc: string;
  icon: LucideIcon;
  adminOnly?: boolean;
};

/** Avenue MDP navigation. All pages are bound to the FastAPI backend.
 * IA (report 30): Streaming is its own tab; Users / Profile / Design System live INSIDE Settings
 * (as sub-tabs), so they are no longer top-level nav items. */
export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Dashboard", desc: "Platform overview", icon: LayoutDashboard },
  { href: "/object-manager", label: "Data Models", desc: "Type A / Type B", icon: Boxes },
  { href: "/incremental", label: "DB Browser", desc: "Schemas & tables", icon: Table2 },
  { href: "/jde", label: "Demo Data", desc: "JDE staging", icon: Database },
  { href: "/apis", label: "API Keys", desc: "External access keys", icon: Plug },
  { href: "/transactions", label: "Transactions", desc: "Ingest / outbound log", icon: Repeat },
  { href: "/connections", label: "Connections", desc: "External systems", icon: Cable },
  { href: "/migration-jobs", label: "Migration Jobs", desc: "ora2pg + PK + Verify", icon: ArrowRightLeft },
  { href: "/streaming", label: "Streaming", desc: "Watermark-incremental sync", icon: Radio },
  { href: "/jde-demo", label: "JDE Demo Flow", desc: "Guided UAT", icon: Workflow },
  // Settings now contains Users · Profile · Design System (+ per-user tabs/theme). Visible to all;
  // admin-only sub-tabs (Users, Tabs & access) are gated inside + by require_admin on the backend.
  { href: "/settings", label: "Settings", desc: "Users · Profile · Design · tabs", icon: Settings },
];

export const NAV_SECONDARY: NavItem[] = [];
