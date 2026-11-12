// The colours of a SESSIONS terminal. A catalog of named themes (xterm `ITheme`), and which one a terminal uses:
// the person's pick for the app theme in force (Settings), else omher's own.
import type { ITheme } from "@xterm/xterm";
import type { TermSettings } from "./settings";

export interface TermTheme {
  id: string;
  /** The theme's own name, shown as it is (never translated). */
  name: string;
  kind: "dark" | "light";
  theme: ITheme;
}

// Matched to omher's tokens (--bg, --body, --ink) so the terminal reads as part of the page.
const OMHER_DARK: ITheme = {
  background: "#0b090d",
  foreground: "#dcd6de",
  cursor: "#f3eff4",
  cursorAccent: "#0b090d",
  selectionBackground: "#3d364066",
  selectionInactiveBackground: "#3d364044",
  black: "#1b181e",
  red: "#f08a8a",
  green: "#7fd6a4",
  yellow: "#eaaf55",
  blue: "#8cbcff",
  magenta: "#e48fd0",
  cyan: "#7fd1d6",
  white: "#dcd6de",
  brightBlack: "#6f6872",
  brightRed: "#ffa3a3",
  brightGreen: "#9be6b9",
  brightYellow: "#f5c779",
  brightBlue: "#a9ccff",
  brightMagenta: "#f0a8de",
  brightCyan: "#9de2e6",
  brightWhite: "#f3eff4",
};
const OMHER_LIGHT: ITheme = {
  background: "#ffffff",
  foreground: "#2c2630",
  cursor: "#19151b",
  cursorAccent: "#ffffff",
  selectionBackground: "#cbc4cf88",
  selectionInactiveBackground: "#cbc4cf55",
  black: "#19151b",
  red: "#c0392b",
  green: "#1f8a52",
  yellow: "#a86a00",
  blue: "#1d5fd1",
  magenta: "#a8327a",
  cyan: "#0f7f86",
  white: "#e9e5eb",
  brightBlack: "#756d7a",
  brightRed: "#d9534f",
  brightGreen: "#28a065",
  brightYellow: "#c08000",
  brightBlue: "#3a78e0",
  brightMagenta: "#c4367f",
  brightCyan: "#1b97a0",
  brightWhite: "#ffffff",
};

/** Every theme a person can pick. omher's own two come first and are the defaults. */
export const TERM_THEMES: readonly TermTheme[] = [
  { id: "omher-dark", name: "omher Dark", kind: "dark", theme: OMHER_DARK },
  { id: "omher-light", name: "omher Light", kind: "light", theme: OMHER_LIGHT },
];

export const termThemeById = (id: string): TermTheme | undefined => TERM_THEMES.find((t) => t.id === id);

/** The theme a terminal uses under app theme `mode`: the pick for that mode, else omher's own for it. */
export function termTheme(mode: "dark" | "light", s: TermSettings): ITheme {
  const picked = termThemeById(mode === "light" ? s.themeLight : s.themeDark);
  return (picked ?? termThemeById(mode === "light" ? "omher-light" : "omher-dark")!).theme;
}
