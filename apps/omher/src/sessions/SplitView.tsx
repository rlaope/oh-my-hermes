// TERMINALS splits (Otty / Orca style): the open TERMINALS session with up to three others, right of or under each
// other in any nesting (splitState.ts keeps the layout). ⌘D splits the focused pane right and ⌘⇧D down (Ctrl+Shift+D
// and Alt+Shift+D off macOS); either asks which session goes in the new pane: another running TERMINALS session, or a
// new Shell in the focused pane's folder (the one its shell last reported, OSC 7). The pane with the keyboard is the
// session open in the main column; the others are dimmed (Settings › Terminal › Dim unfocused panes) and the focused
// one carries a thin accent line. ⌘W closes the pane (the session stays in TERMINALS), ⌘⌥arrows move between panes,
// ⌘] / ⌘[ step through them, ⌘⇧⌥arrows move the pane, ⌘⇧↩ zooms it (the zoom follows the keyboard to another pane;
// splitting, closing or moving a pane ends it, splitState.ts), ⌘⌃= evens them out (layout.ts paneKey has the
// keys off macOS). Dividers drag and a double click evens them. Each pane is its session's own terminal (sessions.ts
// attach), so each keeps its own engine; a pane whose session came back paused after a restart shows it paused. Bot
// chats never split: only TERMINALS sessions are offered, and the keys live in TERMINALS terminals only.
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode, type RefObject } from "react";
import { useStore, getStore } from "../state/store";
import { CloseIcon, PlusIcon } from "../ui";
import { t } from "../i18n";
import { getSessions, useSessions } from "./sessions";
import { folderName, isTerminalRec, SHELL, termFallbackName, termMarkAgent, tildePath, type SessionRec } from "./agents";
import { pickTitle } from "./titles";
import { TermRowMark } from "./TermRowMark";
import { termActs } from "./termActivity";
import { clampRatio, isPane, MAX_PANES, paneKey, panesOf, paneRects, PANE_MIN_ROWS, PANE_MIN_W, type Layout, type PaneKey } from "../terminal/layout";
import { onTermSettings, readTermSettings } from "./term/settings";
import { isMac } from "../app/shortcuts";
import { composing } from "../lib/ime";
import { markPaneClosed } from "../app/menuClose";
import { equalizeIn, getSplit, groupOf, groupSessions, leaveIn, paneKeyIn, paneOf, ratioIn, sessionOf, setSplit, splitIn, splitPaneOf, useSplit, type SplitDirName, type SplitGroup } from "./splitState";

export { getSplit, resetSplit, useSplit } from "./splitState";

/** The TERMINALS sessions that can go in a new pane of `at`'s split: listed, running, not paused, not in it already. */
export function splitChoices(list: SessionRec[], agents: Parameters<typeof isTerminalRec>[0], at: string, groups: SplitGroup[] = getSplit().groups): SessionRec[] {
  const g = groupOf(groups, at);
  const inIt = new Set(g ? groupSessions(g) : [at]);
  return list.filter((r) => !inIt.has(r.id) && paneOf(r.id) !== null && isTerminalRec(agents, r) && !r.paused && (r.status === "running" || r.status === "starting"));
}

/** Open the picker for the TERMINALS session open now (no-op elsewhere, and when its split is full). */
export function openSplitPicker(at?: string, dir: SplitDirName = "right"): void {
  const ui = getStore().getState().ui;
  const id = at ?? (ui.view === "session" ? ui.session : null);
  if (!id) return;
  const g = groupOf(getSplit().groups, id);
  if (g && panesOf(g.layout).length >= MAX_PANES) return;
  setSplit({ picking: { at: id, dir } });
}
export const closeSplitPicker = (): void => setSplit({ picking: null });

const textareaOf = (id: string) => document.querySelector<HTMLElement>(`[data-testid="terminal"][data-session="${id}"] .xterm-helper-textarea`);

/** Give the keyboard to session `id`'s pane: its session opens (header, row, Plans follow) and its terminal is focused. */
export function focusSplitPane(id: string): void {
  if (getStore().getState().ui.session !== id) getStore().actions.openSession(id);
  requestAnimationFrame(() => textareaOf(id)?.focus({ preventScroll: true }));
}

/** Put `add` in a new pane of `at`'s split, right of it or under it; the new pane takes the keyboard. */
export function splitWith(at: string, add: string, dir: SplitDirName = "right"): void {
  if (at === add) return;
  const before = getSplit().groups;
  const groups = splitIn(before, at, dir, add);
  setSplit({ groups, picking: null });
  if (groupOf(groups, add) && groupOf(groups, at)) focusSplitPane(add);
}

/** A new Shell in a new pane of `at`'s split, in `at`'s folder (the one its shell last reported, else where it started),
 *  running the same shell as `at` when that is a Shell row (else the default shell). */
export function splitNewShell(at: string, dir: SplitDirName): void {
  const rec = getSessions().getState().list.find((r) => r.id === at);
  if (!rec) return closeSplitPicker();
  const id = getSessions().startTerminal(SHELL, termActs.get(at).cwd ?? rec.cwd, rec.agent === SHELL ? rec.shell : undefined);
  if (id) splitWith(at, id, dir);
  else closeSplitPicker();
}

/** Take session `id`'s pane out of its split (its session keeps running in TERMINALS); the pane nearest takes the
 *  keyboard when it had it. */
export function leaveSplit(id: string): void {
  const r = leaveIn(getSplit().groups, id);
  setSplit({ groups: r.groups });
  if (getStore().getState().ui.session === id && r.heir) focusSplitPane(r.heir);
}

/** A pane key pressed in TERMINALS session `id`'s terminal. True when it was the split's (the program never sees it). */
export function onSplitKey(id: string, k: PaneKey): boolean {
  if (k.kind === "split") {
    openSplitPicker(id, k.dir);
    return true;
  }
  const before = getSplit().groups;
  const r = paneKeyIn(before, id, k);
  if (!r.took) return false;
  if (r.groups !== before) setSplit({ groups: r.groups });
  if (r.focus) focusSplitPane(r.focus);
  return true;
}

/** Pane keys in a TERMINALS terminal (taken before xterm): `wrap` is the terminal's box, `id` its session. */
export function useSplitKeys(wrap: RefObject<HTMLElement | null>, id: string, on: boolean): void {
  useEffect(() => {
    const el = wrap.current;
    if (!el || !on) return;
    const handle = (e: globalThis.KeyboardEvent) => {
      if (composing(e)) return;
      const k = paneKey(e, isMac());
      if (!k) return;
      const inSplit = !!groupOf(getSplit().groups, id);
      // a held key repeats only the moves between panes; the others happen once per press
      if (e.repeat && k.kind !== "focus" && k.kind !== "step") {
        if (inSplit || k.kind === "split") {
          e.preventDefault();
          e.stopPropagation();
        }
        return;
      }
      // the pane the key is in (splitState `splitPaneOf`, the menu's Close Window asks the same)
      if (!onSplitKey(splitPaneOf(e.target as Element | null, id) ?? id, k)) return;
      e.preventDefault();
      e.stopPropagation();
      // the menu's Close Window may hear the same ⌘W: it is not a second close
      if (k.kind === "close") markPaneClosed();
    };
    el.addEventListener("keydown", handle, true);
    return () => el.removeEventListener("keydown", handle, true);
  }, [wrap, id, on]);
}

/** How bright an unfocused pane stays (Settings › Terminal), as a style for the split. */
export function useDimStyle(): CSSProperties {
  const get = () => readTermSettings().dimUnfocused;
  const dim = useSyncExternalStore(onTermSettings, get, get);
  return { ["--pane-dim" as string]: String(dim) } as CSSProperties;
}

/** The least height a pane keeps under a divider: four rows of the terminal's font, its bar and its padding. */
const paneMinH = () => {
  const s = readTermSettings();
  return Math.ceil(s.fontSize * s.lineHeight) * PANE_MIN_ROWS + 26 + 12;
};

function SideBar({ rec, focused, onClose }: { rec: SessionRec; focused: boolean; onClose: () => void }) {
  const ss = useSessions();
  const name = pickTitle(rec, termFallbackName(rec, ss.agents)).title;
  return (
    <div className="ss-split-bar" data-testid="split-bar" data-session={rec.id} data-focused={focused ? "true" : "false"}>
      <TermRowMark agent={termMarkAgent(rec)} size={13} />
      <span className="ss-split-name" title={rec.cwd}>
        {name}
      </span>
      <span className="ss-split-path">{tildePath(rec.cwd, ss.home)}</span>
      <button type="button" className="ss-split-x" aria-label={t("split.closeSide", { name })} title={t("split.closeSide", { name })} onClick={onClose} data-testid="split-close">
        <CloseIcon />
      </button>
    </div>
  );
}

function Divider({ at, path, dir, ratio }: { at: string; path: string; dir: "row" | "col"; ratio: number }) {
  const [drag, setDrag] = useState(false);
  const min = () => (dir === "row" ? PANE_MIN_W : paneMinH());
  const size = (el: HTMLElement) => {
    const r = el.parentElement?.getBoundingClientRect();
    return r ? (dir === "row" ? r.width : r.height) : 0;
  };
  const put = (v: number) => setSplit({ groups: ratioIn(getSplit().groups, at, path, v) });
  return (
    <div
      className={`ss-split-divider ${dir}${drag ? " on" : ""}`}
      role="separator"
      aria-orientation={dir === "row" ? "vertical" : "horizontal"}
      aria-label={t("termpanel.divider")}
      aria-valuenow={Math.round(ratio * 100)}
      tabIndex={0}
      data-testid="split-divider"
      data-dir={dir}
      data-path={path}
      onPointerDown={(e: PointerEvent<HTMLDivElement>) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture?.(e.pointerId);
        setDrag(true);
      }}
      onPointerMove={(e: PointerEvent<HTMLDivElement>) => {
        if (!drag) return;
        const r = e.currentTarget.parentElement?.getBoundingClientRect();
        if (!r) return;
        const all = dir === "row" ? r.width : r.height;
        const pos = dir === "row" ? e.clientX - r.left : e.clientY - r.top;
        if (all) put(clampRatio(pos / all, all, min()));
      }}
      onPointerUp={() => setDrag(false)}
      onPointerCancel={() => setDrag(false)}
      onLostPointerCapture={() => setDrag(false)}
      onDoubleClick={() => setSplit({ groups: equalizeIn(getSplit().groups, at) })}
      onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
        const back = dir === "row" ? "ArrowLeft" : "ArrowUp";
        const fwd = dir === "row" ? "ArrowRight" : "ArrowDown";
        if (e.key !== back && e.key !== fwd) return;
        e.preventDefault();
        put(clampRatio(ratio + (e.key === fwd ? 0.05 : -0.05), size(e.currentTarget), min()));
      }}
    />
  );
}

type NodeProps = { focus: string; zoom: boolean; list: SessionRec[]; pane: (rec: SessionRec) => ReactNode };

function Pane({ rec, focus, pane }: NodeProps & { rec: SessionRec }) {
  const focused = rec.id === focus;
  const take = () => {
    if (!focused) getStore().actions.openSession(rec.id);
  };
  return (
    <div
      className={`ss-split-side${focused ? " focused" : " dim"}`}
      data-side={focused ? "main" : "beside"}
      data-session={rec.id}
      data-testid="split-pane"
      data-focused={focused ? "true" : "false"}
      // a click takes the pane; focus alone does not (a terminal that mounts focuses itself)
      onPointerDownCapture={take}
    >
      <SideBar rec={rec} focused={focused} onClose={() => leaveSplit(rec.id)} />
      {pane(rec)}
    </div>
  );
}

function LayoutNode({ l, path, ...p }: NodeProps & { l: Layout; path: string }): ReactNode {
  if (isPane(l)) {
    const rec = p.list.find((r) => r.id === sessionOf(l.pane));
    return rec ? <Pane key={rec.id} rec={rec} {...p} /> : null;
  }
  // zoomed: only the part that holds the focused pane shows, at full size
  const mine = paneOf(p.focus) ?? -1;
  if (p.zoom) {
    const inA = panesOf(l.a).includes(mine);
    return <LayoutNode l={inA ? l.a : l.b} path={`${path}${inA ? "a" : "b"}`} {...p} />;
  }
  return (
    <div className={`ss-split-node ${l.dir}`} data-dir={l.dir}>
      <div className="ss-split-part" style={{ flex: `${l.ratio} 1 0px` }}>
        <LayoutNode l={l.a} path={`${path}a`} {...p} />
      </div>
      <Divider at={p.focus} path={path} dir={l.dir} ratio={l.ratio} />
      <div className="ss-split-part" style={{ flex: `${1 - l.ratio} 1 0px` }}>
        <LayoutNode l={l.b} path={`${path}b`} {...p} />
      </div>
    </div>
  );
}

/** The terminal session `main` (the focused one) with the rest of its split, or `main` alone. `pane` draws one
 *  session's terminal (or its paused or ended state). */
export function SplitView({ main, pane }: { main: SessionRec; pane: (rec: SessionRec) => ReactNode }) {
  const sp = useSplit();
  const ss = useSessions();
  const dim = useDimStyle();
  const g = groupOf(sp.groups, main.id);
  const ids = g ? groupSessions(g) : [];
  // the other panes are on the page too: what their rows carried (they rang, they finished) is seen
  const unseen = ids.filter((id) => id !== main.id && ss.unseen[id]).join(",");
  useEffect(() => {
    if (unseen && document.hasFocus()) for (const id of unseen.split(",")) getSessions().seen(id);
  }, [unseen]);
  // the focused pane takes the keyboard when it changes (a row picked in the sidebar, a key, a click), unless the
  // keyboard is in a field, a menu or a dialog
  const inSplit = !!g;
  const zoomed = !!g?.zoom;
  useEffect(() => {
    if (!inSplit) return;
    const r = requestAnimationFrame(() => {
      const el = document.activeElement as HTMLElement | null;
      if (el?.closest(`[data-session="${main.id}"]`) || el?.closest("input, [contenteditable], [role=menu], [role=dialog]") || (el?.tagName === "TEXTAREA" && !el.classList.contains("xterm-helper-textarea"))) return;
      textareaOf(main.id)?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(r);
  }, [main.id, inSplit]);
  // a terminal that mounts focuses itself: when the zoom ends or the panes change, the panes drawn again must not keep
  // the keyboard from the focused one (typing always goes to the pane that shows as focused)
  useEffect(() => {
    if (!inSplit) return;
    const r = requestAnimationFrame(() => {
      const other = (document.activeElement as HTMLElement | null)?.closest('[data-testid="terminal"]')?.getAttribute("data-session");
      if (other && other !== main.id) textareaOf(main.id)?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(r);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoomed, ids.length]);
  if (!g) return <>{pane(main)}</>;
  return (
    <div className={`ss-split${g.zoom ? " zoomed" : ""}`} style={dim} data-testid="session-split" data-panes={ids.length} data-zoom={g.zoom ? "true" : "false"}>
      <LayoutNode l={g.layout} path="" focus={main.id} zoom={!!g.zoom} list={ss.list} pane={pane} />
      {g.zoom && (
        <div className="ss-split-zoomed" data-testid="split-zoomed">
          {t("split.zoomed", { n: ids.length })}
        </div>
      )}
    </div>
  );
}

/** Keeps every split to sessions that are still listed (a closed session's pane goes; a split left alone ends). */
export function useSplitPrune(): void {
  const ss = useSessions();
  useEffect(() => {
    // the saved list is back before the first render (main.tsx: bootResume), so an empty list is really empty
    const alive = new Set(ss.list.map((r) => r.id));
    const groups = getSplit().groups;
    let next = groups;
    for (const id of groups.flatMap(groupSessions)) if (!alive.has(id)) next = leaveIn(next, id).groups;
    if (next !== groups) setSplit({ groups: next });
  }, [ss.list]);
}

/** The picker: running TERMINALS sessions to put in the new pane, and a new Shell in this one's folder. */
export function SplitPicker({ main }: { main: SessionRec }) {
  const sp = useSplit();
  const ss = useSessions();
  const s = useStore();
  const ref = useRef<HTMLDivElement>(null);
  const pick = sp.picking;
  // the picker of the focused pane, or of any pane of its split
  const g = groupOf(sp.groups, main.id);
  const open = !!pick && (pick.at === main.id || (!!g && groupSessions(g).includes(pick.at))) && s.ui.view === "session";
  const from = pick?.at ?? main.id;
  const rows = open ? splitChoices(ss.list, ss.agents, from, sp.groups) : [];
  const fromRec = ss.list.find((r) => r.id === from) ?? main;
  // under the main column's header, at its right edge (the menu is fixed to the window); in a split, under the
  // focused pane's bar instead, so the bar's x stays in view and clickable
  const [at, setAt] = useState<{ left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const m = document.querySelector("main.main")?.getBoundingClientRect();
      const w = ref.current?.offsetWidth ?? 260;
      const bar = document.querySelector(`[data-testid="split-bar"][data-session="${from}"]`)?.getBoundingClientRect();
      if (bar) setAt({ left: Math.max(6, bar.right - w - 8), top: bar.bottom + 4 });
      else if (m) setAt({ left: Math.max(6, m.right - w - 16), top: m.top + 56 });
    };
    place();
    addEventListener("resize", place);
    return () => removeEventListener("resize", place);
  }, [open, from]);
  useEffect(() => {
    if (!open) return;
    // the first running session when there is one, else New Shell
    (ref.current?.querySelector<HTMLElement>('[data-testid="split-pick"]') ?? ref.current?.querySelector<HTMLElement>("button"))?.focus({ preventScroll: true });
    const outside = (e: globalThis.PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) closeSplitPicker();
    };
    document.addEventListener("pointerdown", outside, true);
    return () => document.removeEventListener("pointerdown", outside, true);
  }, [open]);
  if (!open || !pick) return null;
  const move = (e: KeyboardEvent<HTMLDivElement>) => {
    const items = [...(ref.current?.querySelectorAll<HTMLElement>("button") ?? [])];
    const i = items.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      closeSplitPicker();
      focusSplitPane(from);
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
    }
  };
  const where = termActs.get(from).cwd ?? fromRec.cwd;
  const label = t(pick.dir === "down" ? "split.pickDown" : "split.pick");
  return (
    <div ref={ref} className="row-menu ss-split-pick" role="menu" aria-label={label} data-testid="split-picker" data-dir={pick.dir} style={at ?? undefined} onKeyDown={move}>
      <div className="ss-split-pick-h">{label}</div>
      {rows.length === 0 && <div className="ss-split-pick-none">{t("split.none")}</div>}
      {rows.map((r) => (
        <button key={r.id} type="button" role="menuitem" className="row-mi ss-split-pick-row" data-testid="split-pick" data-session={r.id} title={r.cwd} onClick={() => splitWith(from, r.id, pick.dir)}>
          <TermRowMark agent={termMarkAgent(r)} size={13} />
          <span className="ss-split-name">{pickTitle(r, termFallbackName(r, ss.agents)).title}</span>
          <span className="ss-split-path">{folderName(r.cwd)}</span>
        </button>
      ))}
      <div className="row-sep" aria-hidden="true" />
      <button type="button" role="menuitem" className="row-mi ss-split-pick-row" data-testid="split-new-shell" title={where} onClick={() => splitNewShell(from, pick.dir)}>
        <span className="ss-split-pick-plus" aria-hidden="true">
          <PlusIcon size={12} />
        </span>
        <span className="ss-split-name">{t("split.newShell")}</span>
        <span className="ss-split-path">{folderName(where)}</span>
      </button>
    </div>
  );
}

/** A split's shape drawn small: each pane a box in the layout's proportions, `mine` filled (a TERMINALS row's glyph). */
export function SplitGlyph({ layout, mine, size = 12 }: { layout: Layout; mine: number; size?: number }) {
  const rects = paneRects(layout);
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" className="ss-split-glyph">
      {[...rects].map(([n, r]) => (
        <rect key={n} x={r.x * size + 0.75} y={r.y * size + 0.75} width={Math.max(1, r.w * size - 1.5)} height={Math.max(1, r.h * size - 1.5)} rx={1.2} fill={n === mine ? "currentColor" : "none"} stroke="currentColor" strokeWidth={1} />
      ))}
    </svg>
  );
}
