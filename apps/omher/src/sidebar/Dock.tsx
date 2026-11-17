// The dock at the bottom of the sidebar (Arc favourites), BOTS ONLY: while BOTS is scrolled, one rounded tile per bot
// whose row went out of view at the top (dockState.useBotsAbove), in list order, at most six, 3 per row (1 row on a
// short window). At the top of BOTS there is no dock and no space kept for it. It fades and slides in and out
// (150ms; reduced motion: at once). A tile shows the bot's state as Arc and Gmail do: needs you = a small orange dot,
// failed = a small red dot, running = a thin ring (static with reduced motion); done and idle show nothing. Click =
// the bot click: its chat opens and its row slides to the top of BOTS (revealBotTop), and the tiles follow. Tiles
// are one roving-tabindex group (arrow keys move, Enter opens).
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { selectAsks, selectSidebarBots, useStore } from "../state/store";
import { Avatar } from "../ui";
import { t } from "../i18n";
import { DOCK_MAX } from "./dockState";
import { revealBotTop } from "./revealBot";

/** Tiles per row for `n` tiles: rows filled edge to edge, never one tile alone under a full row (4 = 2x2). */
export function dockCols(n: number): number {
  return n <= 3 ? Math.max(1, n) : n === 4 ? 2 : 3;
}

/** How many of the dock's 6 grid columns tile `i` of `n` spans: a full row's tiles share the width evenly, and a
 *  short last row stretches to fill it too (5 tiles = 3 over 2). */
export function dockSpan(i: number, n: number): number {
  const per = dockCols(n);
  const last = n % per;
  return last && i >= n - last ? 6 / last : 6 / per;
}

export const DOCK_FADE_MS = 150;

const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Under 700px of window height the dock keeps one row. */
function useShortWindow(): boolean {
  const q = typeof matchMedia === "function" ? matchMedia("(max-height: 699px)") : null;
  const [short, setShort] = useState(!!q?.matches);
  useEffect(() => {
    if (!q) return;
    const on = () => setShort(q.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, [q]);
  return short;
}

/** `above`: the bots scrolled out of view at the top of BOTS, in list order. */
export function Dock({ above }: { above: string[] }) {
  const s = useStore();
  const [focus, setFocus] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const short = useShortWindow();
  // leaving: the last tiles stay for the fade-out, then the dock is gone from the page
  const [kept, setKept] = useState<string[]>(above);
  const [leaving, setLeaving] = useState(false);
  useEffect(() => {
    if (above.length) {
      setKept(above);
      setLeaving(false);
      return;
    }
    if (reduced()) {
      setKept([]);
      return;
    }
    setLeaving(true);
    const h = setTimeout(() => {
      setKept([]);
      setLeaving(false);
    }, DOCK_FADE_MS);
    return () => clearTimeout(h);
  }, [above]);
  const bots = selectSidebarBots(s);
  const asks = selectAsks(s);
  const names = (above.length ? above : kept).filter((n) => bots.some((b) => b.name === n)).slice(0, short ? 3 : DOCK_MAX);
  const n = names.length;
  useEffect(() => {
    if (focus >= n) setFocus(Math.max(0, n - 1));
  }, [focus, n]);
  if (!n) return null;
  const cols = dockCols(n);
  const tiles = names.map((name) => {
    const b = bots.find((x) => x.name === name)!;
    const mine = (k: string) => k === name || k.startsWith(`fold:${name}:`);
    const needs = asks.some((a) => mine(a.bot));
    const chats = Object.entries(s.chats).filter(([k]) => mine(k));
    const running = b.running || chats.some(([, c]) => !!c.turn);
    // red = failed only: the newest ended turn among the bot's main chat and threads failed, and nothing runs now
    // (an old failed thread under a bot that answered since leaves no dot)
    const ended = chats.map(([, c]) => c.lastTurn).filter((x): x is NonNullable<typeof x> => !!x);
    const newest = ended.sort((a, b) => (b.endedAt ?? 0) - (a.endedAt ?? 0))[0];
    const failed = !chats.some(([, c]) => !!c.turn) && newest?.outcome === "error";
    const state = needs ? "needs" : failed ? "failed" : running ? "running" : null;
    return { name, label: b.display_name, state, active: s.ui.view === "chat" && s.selectedBot === name && !s.ui.thread };
  });
  const go = (name: string) => {
    revealBotTop(name);
    void s.selectBot(name);
  };
  const onKey = (e: KeyboardEvent, i: number) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : e.key === "ArrowDown" ? cols : e.key === "ArrowUp" ? -cols : 0;
    const to = e.key === "Home" ? 0 : e.key === "End" ? n - 1 : step ? Math.max(0, Math.min(n - 1, i + step)) : -1;
    if (to < 0) return;
    e.preventDefault();
    setFocus(to);
    box.current?.querySelectorAll<HTMLButtonElement>(".dk-t")[to]?.focus();
  };
  return (
    <div className={`dock${leaving && !above.length ? " out" : ""}`} ref={box} role="toolbar" aria-label={t("dock.label")} data-testid="dock" data-cols={cols}>
      {tiles.map((tile, i) => {
        const label = tile.state === "needs" ? t("dock.needs", { name: tile.label }) : tile.state === "failed" ? t("dock.failed", { name: tile.label }) : tile.state === "running" ? t("dock.running", { name: tile.label }) : tile.label;
        return (
          <button
            key={tile.name}
            type="button"
            className={`dk-t${tile.state === "running" ? " ring" : ""}${tile.active ? " on" : ""}`}
            tabIndex={i === focus ? 0 : -1}
            aria-label={label}
            aria-current={tile.active ? "true" : undefined}
            title={tile.label}
            data-testid={`dock-tile-bot:${tile.name}`}
            data-state={tile.state ?? "idle"}
            style={{ gridColumn: `span ${dockSpan(i, n)}` } as CSSProperties}
            onClick={() => go(tile.name)}
            onFocus={() => setFocus(i)}
            onKeyDown={(e) => onKey(e, i)}
          >
            <span className="dk-f">
              <Avatar bot={tile.name} size={24} />
            </span>
            {(tile.state === "needs" || tile.state === "failed") && <span className={`dk-dot ${tile.state}`} data-testid="dock-dot" data-dot={tile.state} aria-hidden="true" />}
          </button>
        );
      })}
    </div>
  );
}
