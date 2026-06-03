"use client";

import { cn } from "@/lib/utils";
import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

// NOTE: the focus + Escape effects below depend ONLY on `open`. Depending on `onClose`
// (usually an inline arrow) made the effect re-run on every parent re-render — i.e. every
// keystroke in a form field — which called panel.focus() and stole focus from the input
// after one character. `onCloseRef` keeps Escape wired to the latest handler without
// re-subscribing.

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Focus the panel once when it opens; restore focus on close. Runs ONLY on open-change.
  useEffect(() => {
    if (!open) return;
    const prevFocus = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    return () => {
      prevFocus?.focus?.();
    };
  }, [open]);

  // Escape to close — uses the latest onClose via ref, so typing doesn't re-subscribe.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? titleId : undefined}
    >
      {/* overlay bg-black/40 (context/04) */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div
        ref={panelRef}
        tabIndex={-1}
        className={cn(
          "relative z-10 flex max-h-[92vh] w-full max-w-lg flex-col rounded-lg bg-white shadow-xl outline-none",
          className,
        )}
      >
        {title && (
          <div className="flex shrink-0 items-center justify-between border-b border-neutral-100 px-5 py-3.5">
            <h3 id={titleId} className="text-base font-semibold text-neutral-900">
              {title}
            </h3>
            <button
              onClick={onClose}
              aria-label="Close"
              className="rounded-md p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
            >
              <X size={18} />
            </button>
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex shrink-0 justify-end gap-2 border-t border-neutral-100 px-5 py-3.5">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
