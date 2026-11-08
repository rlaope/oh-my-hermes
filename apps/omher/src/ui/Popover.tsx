import { useEffect, useRef, type ReactNode } from "react";

/**
 * Anchored popover: render it inside a `position: relative` wrapper next to its trigger.
 * Closes on outside click and on Escape.
 */
export function Popover({
  open,
  onClose,
  children,
  align = "right",
  side = "bottom",
  width = 248,
  className,
  label,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  align?: "left" | "right";
  side?: "top" | "bottom";
  width?: number;
  className?: string;
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const el = ref.current;
      const anchor = el?.parentElement;
      if (el && anchor && !anchor.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={label}
      className={`ui-pop ui-pop-${side} ui-pop-${align}${className ? ` ${className}` : ""}`}
      style={{ width }}
    >
      {children}
    </div>
  );
}
