import { cn } from "@/lib/utils";
import type { SelectHTMLAttributes, ReactNode } from "react";
import { RequiredMark } from "@/components/ui/RequiredMark";

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: ReactNode;
  /** Show a red "*" after the label (prompt 47). Visual only - does NOT set native `required`. */
  requiredMark?: boolean;
}

export function Select({ label, requiredMark, className, children, id, ...props }: SelectProps) {
  return (
    <label className="block">
      {label && (
        <span className="mb-1.5 block text-sm font-medium text-neutral-700">
          {label}
          {requiredMark && <RequiredMark />}
        </span>
      )}
      <select
        id={id}
        className={cn(
          "h-10 w-full rounded-md border border-neutral-300 bg-white px-3 text-sm text-neutral-900",
          "focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30",
          "disabled:cursor-not-allowed disabled:bg-neutral-50",
          className,
        )}
        {...props}
      >
        {children}
      </select>
    </label>
  );
}
