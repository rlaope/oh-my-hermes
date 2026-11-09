import { useEffect } from "react";
import type { Look, Theme } from "../state/store";

const query = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null);

export function resolveTheme(theme: Theme): "dark" | "light" {
  if (theme !== "system") return theme;
  return query()?.matches ? "light" : "dark";
}

/** Writes the look (colour set, bubble style, text size) to <html data-palette|data-bubbles|data-text>. */
export function useLookAttributes(look: Look) {
  useEffect(() => {
    const d = document.documentElement.dataset;
    d.palette = look.palette;
    d.bubbles = look.bubbles;
    d.text = look.text;
  }, [look.palette, look.bubbles, look.text]);
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
