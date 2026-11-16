// The pinned dock at the bottom of the sidebar (Arc favourites): rounded tiles, 3 per row, at most 2 rows (1 on a
// short window), bots (their face) and terminals (TermRowMark). It never scrolls; BOTS and TERMINALS end above it.
// A tile shows its state as Arc and Gmail do: needs you = a small orange dot, failed = a small red dot, running = a
// thin ring (static with reduced motion); done and idle show nothing. Click opens the bot's main chat or the
// terminal and scrolls its row into view; right-click offers Open and Unpin; drag a tile to reorder. Tiles are one
// roving-tabindex group (arrow keys move, Enter opens).
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { selectAsks, selectSidebarBots, useStore } from "../state/store";
import { useSessions } from "../sessions/sessions";
import { isShell, isTerminalRec, termMarkAgent, termStatus, agentLabel, type SessionRec } from "../sessions/agents";
import { pickTitle } from "../sessions/titles";
import { TermRowMark } from "../sessions/TermRowMark";
import { Avatar } from "../ui";
import { t } from "../i18n";
import { dockTiles, moveInDock, pinToDock, useDock } from "./dockState";

type TileState = "needs" | "failed" | "running" | null;

interface Tile {
  key: string;
  name: string;
  state: TileState;
  active: boolean;
  open: () => void;
  face: ReactNode;
}

/** Scroll the sidebar row of tile `key` into view inside its own region. */
function reveal(key: string) {
  requestAnimationFrame(() => {
    const sel = key.startsWith("bot:") ? `[data-testid="bot-row-${CSS.escape(key.slice(4))}"]` : `[data-testid="session-${CSS.escape(key.slice(5))}"]`;
    document.querySelector(sel)?.scrollIntoView({ block: "nearest" });
  });
}

export function Dock() {
  const s = useStore();
  const ss = useSessions();
  const dock = useDock();
  const [menu, setMenu] = useState<{ key: string; x: number; y: number } | null>(null);
  const [focus, setFocus] = useState(0);
  const [drag, setDrag] = useState<{ key: string; to: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const bots = selectSidebarBots(s);
  const asks = selectAsks(s);
  const terms = ss.list.filter((r) => isTerminalRec(ss.agents, r));
  const termOf = (id: string) => terms.find((r) => r.id === id);
  // the bots with the most recent activity: their main chat's or a thread's newest message
  const lastOf = (bot: string) => {
    let ts = 0;
    for (const [k, c] of Object.entries(s.chats)) if (k === bot || k.startsWith(`fold:${bot}:`)) ts = Math.max(ts, c.messages[c.messages.length - 1]?.ts ?? 0);
    return ts;
  };
  const recent = [...bots].sort((a, b) => lastOf(b.name) - lastOf(a.name)).map((b) => b.name);
  const exists = (k: string) => (k.startsWith("bot:") ? bots.some((b) => b.name === k.slice(4)) : !!termOf(k.slice(5)));
  const { keys } = dockTiles(dock.pins, exists, recent);
  const now = Date.now();
  const tiles: Tile[] = keys.map((key) => {
    if (key.startsWith("bot:")) {
      const name = key.slice(4);
      const b = bots.find((x) => x.name === name)!;
      const mine = (k: string) => k === name || k.startsWith(`fold:${name}:`);
      const needs = asks.some((a) => mine(a.bot));
      const chats = Object.entries(s.chats).filter(([k]) => mine(k));
      const running = b.running || chats.some(([, c]) => !!c.turn);
      const failed = chats.some(([, c]) => !c.turn && c.lastTurn?.outcome === "error");
      return {
        key,
        name: b.display_name,
        state: needs ? "needs" : failed ? "failed" : running ? "running" : null,
        active: s.ui.view === "chat" && s.selectedBot === name && !s.ui.thread,
        open: () => void s.selectBot(name),
        face: <Avatar bot={name} size={24} />,
      };
    }
    const r = termOf(key.slice(5)) as SessionRec;
    const st = termStatus(r, ss.unseen[r.id], now);
    const name = pickTitle(r, isShell(r.agent) ? t("term.shell") : agentLabel(r.agent, ss.agents)).title;
    return {
      key,
      name,
      state: st === "bell" ? "needs" : st === "err" ? "failed" : r.status === "running" || r.status === "starting" ? "running" : null,
      active: s.ui.view === "session" && s.ui.session === r.id,
      open: () => s.openSession(r.id),
      face: <TermRowMark agent={termMarkAgent(r)} size={20} />,
    };
  });
  useEffect(() => {
    if (focus >= tiles.length) setFocus(Math.max(0, tiles.length - 1));
  }, [focus, tiles.length]);
  useEffect(() => {
    if (!menu) return;
    const off = (e: globalThis.PointerEvent) => {
      if (!(e.target as Element | null)?.closest?.("[data-testid=dock-menu]")) setMenu(null);
    };
    document.addEventListener("pointerdown", off, true);
    return () => document.removeEventListener("pointerdown", off, true);
  }, [menu]);
  if (!tiles.length) return null;
  const go = (tile: Tile) => {
    tile.open();
    reveal(tile.key);
  };
  const onKey = (e: KeyboardEvent, i: number) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : e.key === "ArrowDown" ? 3 : e.key === "ArrowUp" ? -3 : 0;
    const to = e.key === "Home" ? 0 : e.key === "End" ? tiles.length - 1 : step ? Math.max(0, Math.min(tiles.length - 1, i + step)) : -1;
    if (to < 0) return;
    e.preventDefault();
    setFocus(to);
    box.current?.querySelectorAll<HTMLButtonElement>(".dk-t")[to]?.focus();
  };
  // drag to reorder: the tile under the pointer is where it goes
  const slotAt = (x: number, y: number) => {
    const els = [...(box.current?.querySelectorAll<HTMLElement>(".dk-t") ?? [])];
    const i = els.findIndex((el) => {
      const r = el.getBoundingClientRect();
      return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
    });
    return i;
  };
  const onDown = (e: PointerEvent, key: string) => {
    if (e.button !== 0) return;
    const sx = e.clientX;
    const sy = e.clientY;
    let moving = false;
    const move = (ev: globalThis.PointerEvent) => {
      if (!moving && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 5) return;
      moving = true;
      const to = slotAt(ev.clientX, ev.clientY);
      setDrag({ key, to: to < 0 ? keys.indexOf(key) : to });
    };
    const up = (ev: globalThis.PointerEvent) => {
      removeEventListener("pointermove", move);
      removeEventListener("pointerup", up);
      setDrag(null);
      if (!moving) return;
      const to = slotAt(ev.clientX, ev.clientY);
      if (to >= 0 && to !== keys.indexOf(key)) moveInDock(keys, key, to);
      // the click that follows a drag opens nothing
      const stop = (c: MouseEvent) => {
        c.stopPropagation();
        c.preventDefault();
      };
      addEventListener("click", stop, { capture: true, once: true });
      setTimeout(() => removeEventListener("click", stop, { capture: true }), 0);
    };
    addEventListener("pointermove", move);
    addEventListener("pointerup", up);
  };
  return (
    <div className="dock" ref={box} role="toolbar" aria-label={t("dock.label")} data-testid="dock">
      {tiles.map((tile, i) => {
        const label = tile.state === "needs" ? t("dock.needs", { name: tile.name }) : tile.state === "failed" ? t("dock.failed", { name: tile.name }) : tile.state === "running" ? t("dock.running", { name: tile.name }) : tile.name;
        return (
          <button
            key={tile.key}
            type="button"
            className={`dk-t${tile.active ? " on" : ""}${drag?.key === tile.key ? " lifted" : ""}${drag && drag.key !== tile.key && drag.to === i ? " drop" : ""}`}
            tabIndex={i === focus ? 0 : -1}
            aria-label={label}
            aria-current={tile.active ? "true" : undefined}
            title={tile.name}
            data-testid={`dock-tile-${tile.key}`}
            data-state={tile.state ?? "idle"}
            onClick={() => go(tile)}
            onFocus={() => setFocus(i)}
            onKeyDown={(e) => onKey(e, i)}
            onPointerDown={(e) => onDown(e, tile.key)}
            onContextMenu={(e) => {
              e.preventDefault();
              setMenu({ key: tile.key, x: e.clientX, y: e.clientY });
            }}
          >
            <span className={`dk-f${tile.state === "running" ? " ring" : ""}`}>{tile.face}</span>
            {(tile.state === "needs" || tile.state === "failed") && <span className={`dk-dot ${tile.state}`} data-testid="dock-dot" data-dot={tile.state} aria-hidden="true" />}
          </button>
        );
      })}
      {menu && (
        <div className="row-menu" role="menu" data-testid="dock-menu" style={{ left: Math.min(menu.x, innerWidth - 170), top: Math.min(menu.y, innerHeight - 80) }}>
          <button
            type="button"
            role="menuitem"
            className="row-mi"
            data-testid="dock-open"
            onClick={() => {
              const tile = tiles.find((x) => x.key === menu.key);
              setMenu(null);
              if (tile) go(tile);
            }}
          >
            {t("dock.open")}
          </button>
          <button
            type="button"
            role="menuitem"
            className="row-mi"
            data-testid="dock-unpin"
            onClick={() => {
              const k = menu.key;
              setMenu(null);
              // an automatic tile (nothing pinned yet) is taken out by pinning the others in their order
              if (!dock.pins.includes(k)) for (const other of keys) if (other !== k) pinToDock(other, true);
              pinToDock(k, false);
            }}
          >
            {t("dock.unpin")}
          </button>
        </div>
      )}
    </div>
  );
}
