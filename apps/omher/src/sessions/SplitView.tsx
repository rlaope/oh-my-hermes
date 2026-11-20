// TERMINALS splits (Otty / Orca style): the open TERMINALS session with up to three others, right of, left of, over or
// under each other in any nesting (splitState.ts keeps the layout). ⌘D splits the focused pane right and ⌘⇧D down
// (Ctrl+Shift+D and Alt+Shift+D off macOS) at once, with a new Shell in the focused pane's folder (the one its shell
// last reported, OSC 7), as iTerm2 and Ghostty do; a full split does nothing. A TERMINALS row dragged from the sidebar
// onto the open terminal puts that session in a pane on the side it is dropped (splitDrag.ts); a pane's grip (top
// centre) drags the pane itself to another pane's side, and a click on it opens the pane's menu (zoom, even out,
// close). The pane with the keyboard is the session open in the main column; the others are dimmed (Settings ›
// Terminal › Dim unfocused panes) and the focused one shows by its cursor. Panes have no title bar (Ghostty / iTerm
// splits): a 1px divider between them, the grip, and a zoom and an x in the top right corner, which show while the
// pointer is over the pane. ⌘W closes the pane (the session stays in TERMINALS), ⌘⌥arrows move between panes, ⌘] / ⌘[
// step through them, ⌘⇧⌥arrows move the pane, ⌘⇧↩ zooms it (the zoom follows the keyboard to another pane; splitting,
// closing or moving a pane ends it, splitState.ts), ⌘⌃= evens them out (layout.ts paneKey has the keys off macOS).
// Dividers drag and a double click evens them. Each pane is its session's own terminal (sessions.ts attach), so each
// keeps its own engine; a pane whose session came back paused after a restart shows it paused. Bot chats never split:
// only TERMINALS sessions go in a split, and the keys live in TERMINALS terminals only.
import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode, type RefObject } from "react";
import { getStore } from "../state/store";
import { CloseIcon, ExpandIcon } from "../ui";
import { t } from "../i18n";
import { getSessions, useSessions } from "./sessions";
import { SHELL, termFallbackName, tildePath, type SessionRec } from "./agents";
import { pickTitle } from "./titles";
import { termActs } from "./termActivity";
import { clampRatio, isPane, MAX_PANES, paneKey, panesOf, paneRects, PANE_MIN_ROWS, PANE_MIN_W, type Layout, type PaneKey } from "../terminal/layout";
import { onTermSettings, readTermSettings } from "./term/settings";
import { isMac } from "../app/shortcuts";
import { composing } from "../lib/ime";
import { markPaneClosed } from "../app/menuClose";
import { pressToSplit } from "./splitDrag";
import { equalizeIn, getSplit, groupOf, groupSessions, leaveIn, paneKeyIn, paneOf, ratioIn, sessionOf, setSplit, splitIn, splitPaneOf, useSplit, zoomIn, type SplitDirName } from "./splitState";

export { getSplit, resetSplit, useSplit } from "./splitState";

const textareaOf = (id: string) => document.querySelector<HTMLElement>(`[data-testid="terminal"][data-session="${id}"] .xterm-helper-textarea`);

/** Give the keyboard to session `id`'s pane: its session opens (header, row, Plans follow) and its terminal is focused. */
export function focusSplitPane(id: string): void {
  if (getStore().getState().ui.session !== id) getStore().actions.openSession(id);
  requestAnimationFrame(() => textareaOf(id)?.focus({ preventScroll: true }));
}

/** Put `add` in a new pane on the `dir` side of `at`'s (moving it there when it is in that split already); it takes
 *  the keyboard. */
export function splitWith(at: string, add: string, dir: SplitDirName = "right"): void {
  if (at === add) return;
  const before = getSplit().groups;
  const groups = splitIn(before, at, dir, add);
  if (groups === before) return;
  setSplit({ groups });
  if (groupOf(groups, add) && groupOf(groups, at)) focusSplitPane(add);
}

/** A new Shell in a new pane of `at`'s split, in `at`'s folder (the one its shell last reported, else where it started),
 *  running the same shell as `at` when that is a Shell row (else the default shell). */
export function splitNewShell(at: string, dir: SplitDirName): void {
  const rec = getSessions().getState().list.find((r) => r.id === at);
  if (!rec) return;
  const id = getSessions().startTerminal(SHELL, termActs.get(at).cwd ?? rec.cwd, rec.agent === SHELL ? rec.shell : undefined);
  if (id) splitWith(at, id, dir);
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
    const g = groupOf(getSplit().groups, id);
    if (!g || panesOf(g.layout).length < MAX_PANES) splitNewShell(id, k.dir);
    return true;
  }
  const before = getSplit().groups;
  const r = paneKeyIn(before, id, k);
  if (!r.took) return false;
  if (r.groups !== before) setSplit({ groups: r.groups });
  if (r.focus) focusSplitPane(r.focus);
  return true;
}

/** Close TERMINALS session `id` the way a terminal app closes a tab (⌘W or the menu's Close Window on a terminal that
 *  is not split): as its row's x does, a running one only when the close can be undone (the toast brings it back),
 *  an ended one at once. False when it was left alone (the undo window is Off and its program runs). */
export function closeLone(id: string): boolean {
  const ss = getSessions();
  const r = ss.getState().list.find((x) => x.id === id);
  if (!r) return false;
  const running = r.status === "running" || r.status === "starting";
  if (running && !ss.closeUndoable(id)) return false;
  ss.close(id);
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
      // a terminal on its own: Ctrl+Shift+W closes its session off macOS (on macOS ⌘W reaches the menu's Close
      // Window, which does the same: app/menuClose.ts)
      if (k.kind === "close" && !inSplit) {
        if (!isMac() && closeLone(id)) {
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

/** The least height a pane keeps under a divider: four rows of the terminal's font and its padding. */
const paneMinH = () => {
  const s = readTermSettings();
  return Math.ceil(s.fontSize * s.lineHeight) * PANE_MIN_ROWS + 12;
};

/** A pane's own buttons, floating in its top right corner over the terminal (no title bar): zoom and close. They show
 *  while the pointer is over the pane or the keyboard is on them (sessions.css); the pane's name is their tooltip
 *  and the sidebar row's split mark. */
function PaneTools({ rec, focused, onClose }: { rec: SessionRec; focused: boolean; onClose: () => void }) {
  const ss = useSessions();
  const name = pickTitle(rec, termFallbackName(rec, ss.agents)).title;
  const zoom = () => {
    setSplit({ groups: zoomIn(getSplit().groups, rec.id) });
    focusSplitPane(rec.id);
  };
  return (
    <div className="ss-split-tools" data-testid="split-tools" data-session={rec.id} data-focused={focused ? "true" : "false"} title={`${name} · ${tildePath(rec.cwd, ss.home)}`}>
      <button type="button" className="ss-split-x" aria-label={t("key.zoomPane")} title={t("key.zoomPane")} onClick={zoom} data-testid="split-zoom">
        <ExpandIcon size={11} />
      </button>
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

/** The shortcut of a pane menu item, named for this platform (layout.ts paneKey). */
const paneShortcut = (k: "zoom" | "equalize" | "close"): string => {
  const mac = isMac();
  if (k === "zoom") return mac ? "⌘⇧↩" : "Ctrl+Shift+Enter";
  if (k === "equalize") return mac ? "⌘⌃=" : "Ctrl+Alt+=";
  return mac ? "⌘W" : "Ctrl+Shift+W";
};

/** A pane's menu, opened by a click on its grip: zoom, even out, close, each with its key. */
function PaneMenu({ rec, name, at, onClose }: { rec: SessionRec; name: string; at: { x: number; y: number }; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState(at);
  useLayoutEffect(() => {
    const w = ref.current?.offsetWidth ?? 0;
    setPos({ x: Math.max(6, Math.min(at.x - w / 2, innerWidth - w - 6)), y: at.y });
  }, [at]);
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("button")?.focus({ preventScroll: true });
    // a press on its own grip is the grip's (a click there closes the menu)
    const outside = (e: globalThis.PointerEvent) => {
      if (!ref.current?.contains(e.target as Node) && !(e.target as Element).closest?.(`[data-testid="split-grip"][data-session="${rec.id}"]`)) onClose();
    };
    document.addEventListener("pointerdown", outside, true);
    return () => document.removeEventListener("pointerdown", outside, true);
  }, [onClose, rec.id]);
  const act = (fn: () => void) => () => {
    onClose();
    fn();
  };
  const items: { key: "zoom" | "equalize" | "close"; label: string; run: () => void }[] = [
    {
      key: "zoom",
      label: t("key.zoomPane"),
      run: () => {
        setSplit({ groups: zoomIn(getSplit().groups, rec.id) });
        focusSplitPane(rec.id);
      },
    },
    {
      key: "equalize",
      label: t("key.equalizePanes"),
      run: () => {
        setSplit({ groups: equalizeIn(getSplit().groups, rec.id) });
        focusSplitPane(rec.id);
      },
    },
    { key: "close", label: t("key.closePane"), run: () => leaveSplit(rec.id) },
  ];
  const keys = (e: KeyboardEvent<HTMLDivElement>) => {
    const list = [...(ref.current?.querySelectorAll<HTMLElement>("button") ?? [])];
    const i = list.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape" || e.key === "Tab") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
      focusSplitPane(rec.id);
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      list[(i + (e.key === "ArrowDown" ? 1 : list.length - 1)) % list.length]?.focus();
    }
  };
  return (
    <div ref={ref} className="row-menu ss-pane-menu" role="menu" aria-label={name} data-testid="split-pane-menu" data-session={rec.id} style={{ left: pos.x, top: pos.y }} onKeyDown={keys}>
      {items.map((it) => (
        <button key={it.key} type="button" role="menuitem" className="row-mi ss-pane-mi" data-testid={`split-menu-${it.key}`} onClick={act(it.run)}>
          <span className="ss-pane-mi-l">{it.label}</span>
          <kbd className="ss-pane-mi-k">{paneShortcut(it.key)}</kbd>
        </button>
      ))}
    </div>
  );
}

/** A pane's grip, at its top centre over the terminal: drag it to another pane's side to move the pane there
 *  (splitDrag.ts), click it for the pane's menu. */
function PaneGrip({ rec }: { rec: SessionRec }) {
  const ss = useSessions();
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const close = useCallback(() => setMenu(null), []);
  const name = pickTitle(rec, termFallbackName(rec, ss.agents)).title;
  return (
    <>
      <button
        type="button"
        className={`ss-split-grip${menu ? " on" : ""}`}
        aria-label={t("split.grip", { name })}
        title={t("split.grip", { name })}
        aria-haspopup="menu"
        aria-expanded={!!menu}
        data-testid="split-grip"
        data-session={rec.id}
        onPointerDown={(e) => pressToSplit(e, rec.id, (d) => splitWith(d.at, rec.id, d.side))}
        onClick={(e) => {
          if (menu) return setMenu(null);
          const r = e.currentTarget.getBoundingClientRect();
          setMenu({ x: r.left + r.width / 2, y: r.bottom + 4 });
        }}
      >
        <span aria-hidden="true" />
      </button>
      {menu && <PaneMenu rec={rec} name={name} at={menu} onClose={close} />}
    </>
  );
}

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
      <PaneGrip rec={rec} />
      <PaneTools rec={rec} focused={focused} onClose={() => leaveSplit(rec.id)} />
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
