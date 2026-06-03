import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

// Map status values to colors.
// Map status values to colors.
// Map status values to colors.
export type BadgeTone =
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "neutral";

const TONES: Record<BadgeTone, string> = {
  success: "bg-success/10 text-success ring-success/20",
  warning: "bg-warning/10 text-warning ring-warning/20",
  danger: "bg-danger/10 text-danger ring-danger/20",
  info: "bg-info/10 text-info ring-info/20",
  neutral: "bg-neutral-100 text-neutral-600 ring-neutral-200",
};

export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
