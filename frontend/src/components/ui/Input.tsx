import { cn } from "@/lib/utils";
import type { InputHTMLAttributes, ReactNode } from "react";
import { RequiredMark } from "@/components/ui/RequiredMark";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode;
  hint?: ReactNode;
  /** Show a red "*" after the label (prompt 47). Visual only - does NOT set native `required`. */
  requiredMark?: boolean;
}

/** Standard Input — placeholder DIMMED (neutral-400) per MoM #4 (see globals.css). */
export function Input({ label, hint, requiredMark, className, id, ...props }: InputProps) {
  return (
    <label className="block">
      {label && (
        <span className="mb-1.5 block text-sm font-medium text-neutral-700">
          {label}
          {requiredMark && <RequiredMark />}
        </span>
      )}
      <input
        id={id}
        className={cn(
          "h-10 w-full rounded-md border border-neutral-300 bg-white px-3 text-sm",
          "text-neutral-900 placeholder:text-neutral-400",
          "focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30",
          "disabled:cursor-not-allowed disabled:bg-neutral-50",
          className,
        )}
        {...props}
      />
      {hint && <span className="mt-1 block text-xs text-neutral-500">{hint}</span>}
    </label>
  );
}
