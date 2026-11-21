// A terminal's right-click menu (TERMINALS terminals and bottom-panel panes alike), as Orca, VS Code and iTerm2 offer
// one: Copy, Paste, Select all, Find, Clear, Reset, Split right, Split down, each with its key. A terminal asks for it
// (menu-event.ts); this is mounted once and loads the terminal code it acts with only when an item is picked.
// Paste goes through the page's paste guard (the multi-line confirm); Reset puts the terminal's own state back (modes,
// colours, the screen) and sends nothing to the program; Split starts a new Shell as ⌘D does.
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import "./term-menu.css";
import { t, type Key } from "../../i18n";
import { isMac } from "../../app/shortcuts";
import { useStore } from "../../state/store";
import { getSplit, groupOf } from "../splitState";
import { getTermPanel } from "../../terminal/state";
import { MAX_PANES, panesOf } from "../../terminal/layout";
import { TERM_MENU_EVENT, type TermMenuRequest } from "./menu-event";

type ItemKey = "copy" | "paste" | "selectAll" | "find" | "clear" | "reset" | "splitRight" | "splitDown";

/** The key shown beside an item on this platform ("" for none). */
function termMenuShortcut(k: ItemKey, onMac: boolean): string {
  const keys: Record<ItemKey, [string, string]> = {
    copy: ["⌘C", "Ctrl+Shift+C"],
    paste: ["⌘V", "Ctrl+Shift+V"],
    selectAll: ["⌘A", ""],
    find: ["⌘F", "Ctrl+Shift+F"],
    clear: ["⌘K", ""],
    reset: ["", ""],
    splitRight: ["⌘D", "Ctrl+Shift+D"],
    splitDown: ["⌘⇧D", "Alt+Shift+D"],
  };
  return keys[k][onMac ? 0 : 1];
}

/** Where the split items act: a TERMINALS session's terminal, a bottom-panel pane, or neither (no split items). */
function splitTarget(host: Element): { session: string } | { pane: number } | null {
  const session = host.closest('[data-testid="terminal"][data-session]')?.getAttribute("data-session");
  if (session) return { session };
  const raw = host.closest('[data-testid="termpanel-terminal"][data-pane]')?.getAttribute("data-pane");
  const pane = raw ? Number(raw) : NaN;
  return Number.isInteger(pane) ? { pane } : null;
}

/** The split the pane is in already holds four panes: Split right / down would do nothing. */
function splitFull(to: { session: string } | { pane: number }): boolean {
  if ("session" in to) {
    const g = groupOf(getSplit().groups, to.session);
    return !!g && panesOf(g.layout).length >= MAX_PANES;
  }
  const tab = getTermPanel().tabs.find((x) => x.panes.some((p) => p.id === to.pane));
  return !!tab && tab.panes.length >= MAX_PANES;
}

/** Clear or Reset changed the screen without the program printing: the kept history follows (history.ts). */
async function changed(term: TermMenuRequest["term"]): Promise<void> {
  const { historyChanged } = await import("./history");
  historyChanged(term);
}

async function split(host: Element, dir: "right" | "down"): Promise<void> {
  const to = splitTarget(host);
  if (!to) return;
  if ("session" in to) {
    const { onSplitKey } = await import("../SplitView");
    onSplitKey(to.session, { kind: "split", dir });
  } else {
    const { focusPane, splitPane } = await import("../../terminal/state");
    focusPane(to.pane, true);
    splitPane(dir);
  }
}

export function TermMenu() {
  const [req, setReq] = useState<TermMenuRequest | null>(null);
  // another view or session came to the front (a shortcut pressed while the menu had the keyboard): the menu goes,
  // so it never acts on a terminal the person no longer sees
  const ui = useStore().ui;
  const where = `${ui.view}:${ui.session ?? ""}`;
  useEffect(() => setReq(null), [where]);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const on = (e: Event) => setReq((e as CustomEvent<TermMenuRequest>).detail);
    document.addEventListener(TERM_MENU_EVENT, on);
    return () => document.removeEventListener(TERM_MENU_EVENT, on);
  }, []);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!req || !el) return;
    setPos({ x: Math.max(6, Math.min(req.x, innerWidth - el.offsetWidth - 6)), y: Math.max(6, Math.min(req.y, innerHeight - el.offsetHeight - 6)) });
    el.querySelector<HTMLElement>("button:not(:disabled)")?.focus({ preventScroll: true });
  }, [req]);
  useEffect(() => {
    if (!req) return;
    const outside = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setReq(null);
    };
    const away = () => setReq(null);
    // the keyboard left the menu (Tab out, a focus moved by a shortcut)
    const left = (e: FocusEvent) => {
      if (!ref.current?.contains(e.relatedTarget as Node | null)) setReq(null);
    };
    const el = ref.current;
    el?.addEventListener("focusout", left);
    document.addEventListener("pointerdown", outside, true);
    addEventListener("resize", away);
    addEventListener("blur", away);
    return () => {
      el?.removeEventListener("focusout", left);
      document.removeEventListener("pointerdown", outside, true);
      removeEventListener("resize", away);
      removeEventListener("blur", away);
    };
  }, [req]);
  if (!req) return null;

  const { term, host } = req;
  const close = (refocus = true) => {
    setReq(null);
    if (refocus) term.focus();
  };
  const mac = isMac();
  const to = splitTarget(host);
  const full = !!to && splitFull(to);
  const items: { key: ItemKey; label: Key; run: () => void; disabled?: boolean; gap?: boolean }[] = [
    {
      key: "copy",
      label: "tmenu.copy",
      disabled: !term.hasSelection(),
      run: () => void navigator.clipboard?.writeText(term.getSelection()).catch(() => undefined),
    },
    {
      key: "paste",
      label: "tmenu.paste",
      run: () =>
        void Promise.all([navigator.clipboard?.readText(), import("./paste-guard")])
          .then(([text, m]) => {
            if (text) m.guardedPaste(term, text);
          })
          .catch(() => undefined),
    },
    { key: "selectAll", label: "tmenu.selectAll", run: () => term.selectAll() },
    { key: "find", label: "tmenu.find", run: () => req.find(), gap: true },
    {
      key: "clear",
      label: "tmenu.clear",
      run: () => {
        term.clear();
        void changed(term);
      },
      gap: true,
    },
    {
      key: "reset",
      label: "tmenu.reset",
      run: () => {
        term.reset();
        void changed(term);
      },
    },
    ...(to
      ? [
          { key: "splitRight" as const, label: "tmenu.splitRight" as Key, run: () => void split(host, "right"), disabled: full, gap: true },
          { key: "splitDown" as const, label: "tmenu.splitDown" as Key, run: () => void split(host, "down"), disabled: full },
        ]
      : []),
  ];
  const keys = (e: KeyboardEvent<HTMLDivElement>) => {
    const list = [...(ref.current?.querySelectorAll<HTMLElement>("button:not(:disabled)") ?? [])];
    const i = list.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape" || e.key === "Tab") {
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      const to = e.key === "Home" ? 0 : e.key === "End" ? list.length - 1 : (i + (e.key === "ArrowDown" ? 1 : list.length - 1)) % list.length;
      list[to]?.focus();
    }
  };
  return (
    <div
      ref={ref}
      className="row-menu term-menu"
      role="menu"
      aria-label={t("tmenu.label")}
      data-testid="term-menu"
      style={{ left: pos.x, top: pos.y }}
      onKeyDown={keys}
      onContextMenu={(e) => e.preventDefault()}
    >
      {items.map((it) => (
        <button
          key={it.key}
          type="button"
          role="menuitem"
          className={`row-mi term-mi${it.gap ? " term-mi-gap" : ""}`}
          data-testid={`term-menu-${it.key}`}
          disabled={it.disabled}
          onClick={() => {
            // find and split hand the keyboard on themselves
            close(it.key !== "find" && it.key !== "splitRight" && it.key !== "splitDown");
            it.run();
          }}
        >
          <span className="term-mi-l">{t(it.label)}</span>
          {termMenuShortcut(it.key, mac) && <kbd className="term-mi-k">{termMenuShortcut(it.key, mac)}</kbd>}
        </button>
      ))}
    </div>
  );
}
