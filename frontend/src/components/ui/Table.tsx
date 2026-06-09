import { cn } from "@/lib/utils";
import type { ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";

export function Table({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-200">
      <table className={cn("w-full border-collapse text-sm", className)}>
        {children}
      </table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  // header bg-neutral-50 (context/04)
  return <thead className="bg-neutral-50">{children}</thead>;
}

export function TBody({ children }: { children: ReactNode }) {
  return (
    <tbody className="divide-y divide-neutral-100">{children}</tbody>
  );
}

export function TR({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  // row hover:bg-neutral-50 (context/04)
  return (
    <tr className={cn("transition-colors hover:bg-neutral-50", className)}>
      {children}
    </tr>
  );
}

export function TH({
  children,
  className,
  ...props
}: ThHTMLAttributes<HTMLTableCellElement> & { children?: ReactNode }) {
  return (
    <th
      className={cn(
        "px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-neutral-500",
        className,
      )}
      {...props}
    >
      {children}
    </th>
  );
}

export function TD({
  children,
  className,
  ...props
}: TdHTMLAttributes<HTMLTableCellElement> & { children?: ReactNode }) {
  return (
    <td className={cn("px-4 py-2.5 text-neutral-700", className)} {...props}>
      {children}
    </td>
  );
}
