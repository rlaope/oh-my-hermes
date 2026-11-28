// Settings > Terminal > Customize colours: each colour of the theme picked for one app theme (screen, the sixteen ANSI
// colours, the pane border) as a swatch with a colour picker and a hex field. A change is saved at once as that app
// theme's edited set (settings `edits`), so the preview and every open terminal take it; Reset goes back to the theme
// the edits started from. Editing under the light app theme edits the light set, never the dark one.
import { useEffect, useState } from "react";
import { t, type Key } from "../../i18n";
import { cleanHex, writeTermSettings, type TermEditKey, type TermSettings } from "../../sessions/term/settings";
import { ANSI_BRIGHT, ANSI_NORMAL, EDITED_THEME_ID, themeBorder, type TermTheme } from "../../sessions/term/themes";

type Mode = "dark" | "light";

const SCREEN: { key: TermEditKey; label: Key }[] = [
  { key: "background", label: "term.cBackground" },
  { key: "foreground", label: "term.cForeground" },
  { key: "cursor", label: "term.cCursor" },
  { key: "selectionBackground", label: "term.cSelection" },
  { key: "border", label: "term.cBorder" },
];
const NAMES: Key[] = ["term.cBlack", "term.cRed", "term.cGreen", "term.cYellow", "term.cBlue", "term.cMagenta", "term.cCyan", "term.cWhite"];

/** The page's own line colour, as the border shows when no edit sets it (a colour picker takes `#rrggbb` only). */
function pageLine(): string {
  if (typeof document === "undefined") return "#808080";
  const v = getComputedStyle(document.documentElement).getPropertyValue("--line-soft").trim();
  return cleanHex(v.slice(0, 7)) ?? "#808080";
}

/** A theme colour as `#rrggbb` for the swatch: an `#rrggbbaa` loses its alpha; anything else is grey. */
const asHex = (c: string | undefined) => (c && cleanHex(c.slice(0, 7))) || "#808080";

/** What the slot `mode` would get with `key` set to `hex`: the edited set (started from the theme in force) with it. */
export function editPatch(mode: Mode, picked: TermTheme, s: TermSettings, key: TermEditKey, hex: string): Partial<TermSettings> {
  const editing = picked.id === EDITED_THEME_ID && s.edits[mode];
  const base = editing ? s.edits[mode]!.base : picked.id;
  const colors = editing ? { ...s.edits[mode]!.colors, [key]: hex } : { [key]: hex };
  return {
    edits: { ...s.edits, [mode]: { base, colors } },
    ...(mode === "light" ? { themeLight: EDITED_THEME_ID } : { themeDark: EDITED_THEME_ID }),
  };
}

/** Reset: the slot `mode` goes back to the theme its edits started from, and the edits are gone. */
export function resetPatch(mode: Mode, s: TermSettings): Partial<TermSettings> {
  const base = s.edits[mode]?.base ?? (mode === "light" ? "omher-light" : "omher-dark");
  return { edits: { ...s.edits, [mode]: null }, ...(mode === "light" ? { themeLight: base } : { themeDark: base }) };
}

function Swatch({ id, label, value, onPick }: { id: string; label: string; value: string; onPick: (hex: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const ok = cleanHex(text) !== null;
  return (
    <label className="tc-sw" data-testid={`term-color-${id}`}>
      <input type="color" className="tc-pick" aria-label={label} value={value} onChange={(e) => onPick(e.target.value.toLowerCase())} data-testid={`term-color-${id}-pick`} />
      <span className="tc-name">{label}</span>
      <input
        type="text"
        className="tc-hex"
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        maxLength={7}
        aria-label={t("term.cHex", { what: label })}
        aria-invalid={!ok}
        title={ok ? undefined : t("term.cHexBad")}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          const hex = cleanHex(e.target.value);
          if (hex && hex !== value) onPick(hex);
        }}
        onBlur={() => setText(value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
        data-testid={`term-color-${id}-hex`}
      />
    </label>
  );
}

export function TermColors({ mode, picked, settings }: { mode: Mode; picked: TermTheme; settings: TermSettings }) {
  const th = picked.theme;
  const edited = picked.id === EDITED_THEME_ID;
  const baseName = picked.base?.name ?? picked.name;
  const value = (k: TermEditKey) => (k === "border" ? themeBorder(th) ?? pageLine() : asHex(th[k]));
  const set = (k: TermEditKey, hex: string) => void writeTermSettings(editPatch(mode, picked, settings, k, hex));
  const row = (keys: readonly TermEditKey[], labels: (i: number) => string) =>
    keys.map((k, i) => <Swatch key={k} id={k} label={labels(i)} value={value(k)} onPick={(hex) => set(k, hex)} />);

  return (
    <div className="tc" data-testid="term-colors" data-mode={mode}>
      <div className="tc-head">
        <span className="tc-for">{t(mode === "light" ? "term.cForLight" : "term.cForDark", { name: baseName })}</span>
        <button type="button" className="st-btn tc-reset" disabled={!edited} onClick={() => writeTermSettings(resetPatch(mode, settings))} data-testid="term-colors-reset">
          {t("term.cReset", { name: baseName })}
        </button>
      </div>
      <div className="tc-gh">{t("term.cScreen")}</div>
      <div className="tc-grid">{row(SCREEN.map((x) => x.key), (i) => t(SCREEN[i].label))}</div>
      <div className="tc-gh">{t("term.cNormal")}</div>
      <div className="tc-grid">{row(ANSI_NORMAL, (i) => t(NAMES[i]))}</div>
      <div className="tc-gh">{t("term.cBright")}</div>
      <div className="tc-grid">{row(ANSI_BRIGHT, (i) => t("term.cBrightOf", { c: t(NAMES[i]) }))}</div>
    </div>
  );
}
