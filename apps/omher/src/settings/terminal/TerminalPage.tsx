// Settings > Terminal: how the SESSIONS terminals look. A theme for each app theme (dark, light) picked from the
// catalog with a live preview, then text, cursor and the rest. Every change is saved on this computer and reaches
// the open terminals at once (term/settings.ts hands it to them).
import { useEffect, useState, useSyncExternalStore } from "react";
import "./terminal.css";
import { useStore } from "../../state/store";
import { resolveTheme } from "../../app/theme";
import { Seg } from "../../chat/model/Seg";
import { CheckIcon } from "../../chat/model/CheckIcon";
import { locale, t, type Key } from "../../i18n";
import { rendererInUse } from "../../sessions/term/engine";
import {
  cleanTermFont,
  onTermSettings,
  readTermSettings,
  TERM_CONTRASTS,
  TERM_CURSORS,
  TERM_FONT_SIZE,
  TERM_GPUS,
  TERM_LINE_HEIGHT,
  TERM_PADDING,
  TERM_SCROLLBACKS,
  writeTermSettings,
  type TermContrast,
  type TermCursor,
  type TermGpu,
  type TermSettings,
} from "../../sessions/term/settings";
import { ANSI_NORMAL, TERM_THEMES, termThemePick, type TermTheme } from "../../sessions/term/themes";
import { TermPreview } from "./TermPreview";

type Mode = "dark" | "light";

const SLOT: Record<Mode, Key> = { dark: "term.forDark", light: "term.forLight" };
const KIND: Record<Mode, Key> = { dark: "look.dark", light: "look.light" };
const CURSOR: Record<TermCursor, Key> = { block: "term.block", bar: "term.bar", underline: "term.underline" };
const CONTRAST: Record<TermContrast, Key> = { auto: "term.auto", high: "term.contrastHigh", theme: "term.contrastTheme" };
const CONTRAST_HINT: Record<TermContrast, Key> = { auto: "term.contrastAutoHint", high: "term.contrastHighHint", theme: "term.contrastThemeHint" };
const GPU: Record<TermGpu, Key> = { auto: "term.auto", on: "set.on", off: "set.off" };
const IN_USE: Record<"gpu" | "standard", Key> = { gpu: "term.usingGpu", standard: "term.usingStandard" };
const ON_OFF = (): { value: string; label: string }[] => [
  { value: "on", label: t("set.on") },
  { value: "off", label: t("set.off") },
];

const isMac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
/** "tokyonight" finds "Tokyo Night": letters and digits only, lower case. */
const compact = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
const round = (n: number) => Math.round(n * 100) / 100;

export function useTermSettings(): TermSettings {
  return useSyncExternalStore(onTermSettings, readTermSettings, readTermSettings);
}

function Row({ title, hints, children, testId }: { title: string; hints?: (string | null)[]; children: React.ReactNode; testId?: string }) {
  return (
    <div className="st-row" data-testid={testId}>
      <div className="st-k">
        <b>{title}</b>
        {hints?.map((h) => h && <span key={h}>{h}</span>)}
      </div>
      <div className="st-v">{children}</div>
    </div>
  );
}

/** A number with a step either side. Typing a value in range applies it as it is typed; anything else waits and
 *  goes back to the value in force when the field is left. */
function Stepper({ value, min, max, step, label, onChange, testId }: { value: number; min: number; max: number; step: number; label: string; onChange: (n: number) => void; testId: string }) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const inRange = (raw: string) => {
    const n = Number(raw);
    return raw.trim() !== "" && Number.isFinite(n) && n >= min && n <= max ? round(n) : null;
  };
  const bump = (by: number) => onChange(Math.min(max, Math.max(min, round(value + by))));
  return (
    <div className="tm-step" role="group" aria-label={label} data-testid={testId}>
      <button type="button" aria-label={t("term.dec", { what: label })} disabled={value <= min} onClick={() => bump(-step)}>
        −
      </button>
      <input
        inputMode="decimal"
        aria-label={label}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          const n = inRange(e.target.value);
          if (n !== null && n !== value) onChange(n);
        }}
        onBlur={() => setText(String(value))}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
      />
      <button type="button" aria-label={t("term.inc", { what: label })} disabled={value >= max} onClick={() => bump(step)}>
        +
      </button>
    </div>
  );
}

function ThemeRow({ theme, on, onPick }: { theme: TermTheme; on: boolean; onPick: () => void }) {
  const c = theme.theme;
  return (
    <button type="button" role="radio" aria-checked={on} className={`tm-row${on ? " on" : ""}`} onClick={onPick} title={theme.name} data-testid={`term-theme-${theme.id}`}>
      <span className="tm-sw" aria-hidden="true" style={{ background: c.background, color: c.foreground }}>
        {ANSI_NORMAL.map((k) => (
          <i key={k} style={{ background: c[k] }} />
        ))}
      </span>
      <span className="tm-name">{theme.name}</span>
      {on && <CheckIcon />}
    </button>
  );
}

export function TerminalPage() {
  const s = useStore();
  const term = useTermSettings();
  const appMode = resolveTheme(s.ui.theme);
  // the pick being made: for the app theme in force until the person looks at the other one
  const [slot, setSlot] = useState<Mode>(appMode);
  useEffect(() => setSlot(appMode), [appMode]);
  const [q, setQ] = useState("");
  const [font, setFont] = useState(term.fontFamily);

  const picked = termThemePick(slot, term);
  const needle = compact(q);
  const shown = needle ? TERM_THEMES.filter((th) => compact(th.name).includes(needle)) : TERM_THEMES;
  // the kind that suits the app theme being picked for comes first
  const kinds: Mode[] = slot === "light" ? ["light", "dark"] : ["dark", "light"];
  const pick = (id: string) => writeTermSettings(slot === "light" ? { themeLight: id } : { themeDark: id });
  const set = (patch: Partial<TermSettings>) => void writeTermSettings(patch);
  const using = rendererInUse();
  const rows = (n: number) => n.toLocaleString(locale());

  return (
    <div className="st-page st-wide tm" data-testid="term-settings">
      <div className="st-gh st-gh0">{t("term.theme")}</div>
      <TermPreview theme={picked} settings={term} />
      <div className="tm-bar">
        <div className="tm-slot">
          <Seg
            small
            label={t("term.themeFor")}
            value={slot}
            options={(["dark", "light"] as Mode[]).map((m) => ({ value: m, label: t(SLOT[m]) }))}
            onChange={(v) => setSlot(v as Mode)}
            testId="term-slot"
          />
        </div>
        <input type="search" className="bots-q tm-q" placeholder={t("term.find")} aria-label={t("term.find")} value={q} onChange={(e) => setQ(e.target.value)} data-testid="term-search" />
      </div>
      <div className="tm-list" role="radiogroup" aria-label={t(SLOT[slot])} data-testid="term-themes">
        {kinds.map((kind) => {
          const list = shown.filter((th) => th.kind === kind);
          if (!list.length) return null;
          return (
            <div key={kind} data-testid={`term-themes-${kind}`}>
              <div className="tm-gh">{t(KIND[kind])}</div>
              <div className="tm-grid">
                {list.map((th) => (
                  <ThemeRow key={th.id} theme={th} on={th.id === picked.id} onPick={() => pick(th.id)} />
                ))}
              </div>
            </div>
          );
        })}
        {shown.length === 0 && (
          <div className="tm-none" data-testid="term-themes-none">
            {t("term.noMatch", { q: q.trim() })}
          </div>
        )}
      </div>

      <div className="st-gh">{t("term.text")}</div>
      <div className="st-grp">
        <Row title={t("term.font")} hints={[t("term.fontHint")]}>
          <input
            type="text"
            className="tm-font"
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            placeholder={t("term.fontDefault")}
            aria-label={t("term.font")}
            value={font}
            onChange={(e) => {
              const v = cleanTermFont(e.target.value);
              setFont(v);
              set({ fontFamily: v });
            }}
            data-testid="term-font"
          />
        </Row>
        <Row title={t("term.fontSize")}>
          <Stepper value={term.fontSize} min={TERM_FONT_SIZE.min} max={TERM_FONT_SIZE.max} step={0.5} label={t("term.fontSize")} onChange={(n) => set({ fontSize: n })} testId="term-font-size" />
        </Row>
        <Row title={t("term.lineHeight")}>
          <Stepper value={term.lineHeight} min={TERM_LINE_HEIGHT.min} max={TERM_LINE_HEIGHT.max} step={0.1} label={t("term.lineHeight")} onChange={(n) => set({ lineHeight: n })} testId="term-line-height" />
        </Row>
        <Row title={t("term.contrast")} hints={[t(CONTRAST_HINT[term.contrast])]} testId="term-contrast-row">
          <Seg
            small
            label={t("term.contrast")}
            value={term.contrast}
            options={TERM_CONTRASTS.map((c) => ({ value: c, label: t(CONTRAST[c]) }))}
            onChange={(v) => set({ contrast: v as TermContrast })}
            testId="term-contrast"
          />
        </Row>
        <Row title={t("term.padding")} hints={[t("term.paddingHint")]}>
          <Stepper value={term.padding} min={TERM_PADDING.min} max={TERM_PADDING.max} step={2} label={t("term.padding")} onChange={(n) => set({ padding: Math.round(n) })} testId="term-padding" />
        </Row>
      </div>

      <div className="st-gh">{t("term.cursor")}</div>
      <div className="st-grp">
        <Row title={t("term.cursorStyle")}>
          <Seg
            small
            label={t("term.cursorStyle")}
            value={term.cursorStyle}
            options={TERM_CURSORS.map((c) => ({ value: c, label: t(CURSOR[c]) }))}
            onChange={(v) => set({ cursorStyle: v as TermCursor })}
            testId="term-cursor"
          />
        </Row>
        <Row title={t("term.blink")}>
          <Seg small label={t("term.blink")} value={term.cursorBlink ? "on" : "off"} options={ON_OFF()} onChange={(v) => set({ cursorBlink: v === "on" })} testId="term-blink" />
        </Row>
      </div>

      <div className="st-gh">{t("term.more")}</div>
      <div className="st-grp">
        <Row title={t("term.scrollback")} hints={[t("term.scrollbackHint")]} testId="term-scrollback-row">
          <Seg
            small
            label={t("term.scrollback")}
            value={String(term.scrollback)}
            options={TERM_SCROLLBACKS.map((n) => ({ value: String(n), label: rows(n) }))}
            onChange={(v) => set({ scrollback: Number(v) })}
            testId="term-scrollback"
          />
        </Row>
        {isMac() && (
          <Row title={t("term.optionMeta")} hints={[t("term.optionMetaHint")]} testId="term-option-meta-row">
            <Seg small label={t("term.optionMeta")} value={term.optionIsMeta ? "on" : "off"} options={ON_OFF()} onChange={(v) => set({ optionIsMeta: v === "on" })} testId="term-option-meta" />
          </Row>
        )}
        <Row title={t("term.gpu")} hints={[t("term.gpuHint"), using ? t(IN_USE[using]) : null]} testId="term-gpu-row">
          <Seg small label={t("term.gpu")} value={term.gpu} options={TERM_GPUS.map((g) => ({ value: g, label: t(GPU[g]) }))} onChange={(v) => set({ gpu: v as TermGpu })} testId="term-gpu" />
        </Row>
      </div>

      <div className="st-gh">{t("term.clipboard")}</div>
      <div className="st-grp">
        <Row title={t("term.copyOnSelect")} hints={[t("term.copyOnSelectHint")]} testId="term-copy-select-row">
          <Seg small label={t("term.copyOnSelect")} value={term.copyOnSelect ? "on" : "off"} options={ON_OFF()} onChange={(v) => set({ copyOnSelect: v === "on" })} testId="term-copy-select" />
        </Row>
        <Row title={t("term.rightClickPaste")} hints={[t("term.rightClickPasteHint")]} testId="term-right-paste-row">
          <Seg small label={t("term.rightClickPaste")} value={term.rightClickPaste ? "on" : "off"} options={ON_OFF()} onChange={(v) => set({ rightClickPaste: v === "on" })} testId="term-right-paste" />
        </Row>
      </div>
    </div>
  );
}
