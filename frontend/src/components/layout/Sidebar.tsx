"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LogIn, LogOut } from "lucide-react";
import { NAV_ITEMS, NAV_SECONDARY, type NavItem } from "@/lib/nav";
import { useAuth } from "@/components/auth/AuthProvider";
import { cn } from "@/lib/utils";

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={cn(
        "group flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
        active
          ? "bg-brand text-white"
          : "text-neutral-700 hover:bg-neutral-100",
      )}
    >
      <Icon
        size={18}
        className={cn(active ? "text-white" : "text-neutral-400 group-hover:text-neutral-600")}
      />
      <span className="flex-1 truncate font-medium">{item.label}</span>
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(href + "/");
  // Hide admin-only items from non-admins (Users Management). Route also guards.
  const items = NAV_ITEMS.filter((i) => !i.adminOnly || user?.role === "admin");

  return (
    <aside className="flex h-screen w-64 flex-col border-r border-neutral-200 bg-white">
      <div className="flex flex-col items-center border-b border-neutral-100 px-5 py-5">
        <div className="w-fit text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/avenue-logo-full.svg"
            alt="Avenue MDP"
            className="mx-auto mb-2 block h-auto w-4/5 object-contain"
          />
        </div>
      </div>

      {/* Primary nav */}
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
        {items.map((item) => (
          <NavLink key={item.href} item={item} active={isActive(item.href)} />
        ))}

        <div className="my-3 border-t border-neutral-100" />
        {NAV_SECONDARY.map((item) => (
          <NavLink key={item.href} item={item} active={isActive(item.href)} />
        ))}
      </nav>

      {/* Footer — signed-in user + log out */}
      <div className="border-t border-neutral-100 p-3">
        {user ? (
          <div className="flex items-center gap-2">
            <Link
              href="/profile"
              className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 hover:bg-neutral-100"
            >
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-bold text-white">
                {user.username.slice(0, 1).toUpperCase()}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-neutral-800">{user.username}</span>
                <span className="block truncate text-xs text-neutral-400">{user.role}</span>
              </span>
            </Link>
            <button
              onClick={async () => {
                await logout();
                router.replace("/login");
              }}
              title="Log out"
              className="rounded-md p-2 text-neutral-400 hover:bg-neutral-100 hover:text-danger"
            >
              <LogOut size={18} />
            </button>
          </div>
        ) : (
          <Link
            href="/login"
            className="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-neutral-600 hover:bg-neutral-100"
          >
            <LogIn size={18} className="text-neutral-400" />
            Sign in
          </Link>
        )}
      </div>
    </aside>
  );
}
