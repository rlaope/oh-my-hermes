import type { ButtonHTMLAttributes, ReactNode } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode };

/** 26px square ghost button with an accessible label. */
export function IconButton({ label, children, className, ...rest }: Props) {
  return (
    <button type="button" aria-label={label} title={label} className={`ui-ib${className ? ` ${className}` : ""}`} {...rest}>
      {children}
    </button>
  );
}
