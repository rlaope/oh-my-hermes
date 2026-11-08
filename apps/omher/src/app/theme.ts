import { useEffect } from "react";
import type { Theme } from "../state/store";

const query = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null);

export function resolveTheme(theme: Theme): "dark" | "light" {
  if (theme !== "system") return theme;
  return query()?.matches ? "light" : "dark";
}

/** Writes the resolved theme to <html data-theme>; "system" follows the OS live. */
export function useThemeAttribute(theme: Theme) {
  useEffect(() => {
    const apply = () => {
      document.documentElement.dataset.theme = resolveTheme(theme);
    };
    apply();
    if (theme !== "system") return;
    const mq = query();
    mq?.addEventListener("change", apply);
    return () => mq?.removeEventListener("change", apply);
  }, [theme]);
}
