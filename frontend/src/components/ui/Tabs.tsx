"use client";

import { cn } from "@/lib/utils";

export type TabDef = { key: string; label: string };

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: TabDef[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="inline-flex flex-wrap gap-1 rounded-lg border border-neutral-200 bg-white p-1">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={cn(
            "rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
            active === t.key
              ? "bg-brand text-white"
              : "text-neutral-600 hover:bg-neutral-100",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
