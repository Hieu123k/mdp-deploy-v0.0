import { cn } from "@/lib/utils";
import type { SelectHTMLAttributes, ReactNode } from "react";

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: ReactNode;
}

export function Select({ label, className, children, id, ...props }: SelectProps) {
  return (
    <label className="block">
      {label && (
        <span className="mb-1.5 block text-sm font-medium text-neutral-700">
          {label}
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
