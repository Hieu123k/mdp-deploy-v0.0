import type { ReactNode } from "react";

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-neutral-900">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-1 text-sm text-neutral-500">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}

/** Placeholder block for stub pages (no business logic yet). */
export function StubNotice({ children }: { children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-neutral-300 bg-white/60 p-8 text-center">
      <p className="text-sm text-neutral-500">
        {children ?? "This page will be built in a later prompt."}
      </p>
    </div>
  );
}
