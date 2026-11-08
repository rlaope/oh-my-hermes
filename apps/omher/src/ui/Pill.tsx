import type { ButtonHTMLAttributes, ReactNode } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode; as?: "button" | "span" };

/** Small bordered gray pill (model | reasoning, chips). Selection states stay gray. */
export function Pill({ children, className, as = "button", ...rest }: Props) {
  const cls = `ui-pill${className ? ` ${className}` : ""}`;
  if (as === "span") return <span className={cls}>{children}</span>;
  return (
    <button type="button" className={cls} {...rest}>
      {children}
    </button>
  );
}
