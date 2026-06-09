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
  UserRound,
  Palette,
  Users,
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

/** Avenue MDP navigation. All pages are bound to the FastAPI backend. */
export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Dashboard", desc: "Platform overview", icon: LayoutDashboard },
  { href: "/object-manager", label: "Data Models", desc: "Type A / Type B", icon: Boxes },
  { href: "/incremental", label: "DB Browser", desc: "Schemas & tables", icon: Table2 },
  { href: "/jde", label: "Demo Data", desc: "JDE staging", icon: Database },
  { href: "/apis", label: "API Keys", desc: "External access keys", icon: Plug },
  { href: "/transactions", label: "Transactions", desc: "Ingest / outbound log", icon: Repeat },
  { href: "/connections", label: "Connections", desc: "External systems", icon: Cable },
  { href: "/migration-jobs", label: "Migration Jobs", desc: "ora2pg tracking", icon: ArrowRightLeft },
  { href: "/jde-demo", label: "JDE Demo Flow", desc: "Guided UAT", icon: Workflow },
  { href: "/users", label: "Users", desc: "Accounts & roles", icon: Users, adminOnly: true },
  { href: "/settings", label: "Settings", desc: "Tabs, roles & theme", icon: Settings, adminOnly: true },
  { href: "/profile", label: "Profile", desc: "Sign-in & identity", icon: UserRound },
];

export const NAV_SECONDARY: NavItem[] = [
  { href: "/design-system", label: "Design System", desc: "UI source of truth", icon: Palette },
];
