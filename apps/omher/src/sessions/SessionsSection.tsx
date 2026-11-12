// SESSIONS in the sidebar: the `+` menu of agents (picking one opens its New session chat at once; the folder is
// picked in that chat, see DraftPane in SessionView), and one row per session started in this run of the app. A draft row reads "New
// session" over its folder until its first message. A chat row shows the bot row's live states: the
// answer ring around the agent mark and the turn's elapsed time while a turn runs, and the amber dot with
// "waiting" while one of its approvals or questions is open (the same asks the Needs-you strip lists). A
// terminal row keeps a live dot while its program runs: a terminal has no turn to ring for.
// Line 1 is the session's name (the person's, the agent's own title, a summary of the first message, else the
// folder) and line 2 the folder and the agent. Double-click the name, or right-click › Rename, to name it.
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { selectAsks, useStore, type AppState } from "../state/store";
import { CloseIcon, LiveRing, PlusIcon, Popover, Spinner, TypingDots } from "../ui";
import { busyFor, shortTime } from "../app/time";
import { useNow } from "../elsewhere/useNow";
import { t } from "../i18n";
import { composing } from "../lib/ime";
import { AgentMark } from "./AgentMark";
import { agentDef, agentLabel, folderName, hermesOnly, menuOrder, missingNote, rowModel, type AgentId, type ChatLive, type RowContext, type SessionRec } from "./agents";
import { getSessions, useSessions } from "./sessions";
import { getAddOmh, useAddOmh } from "./addOmh";
import { InstallLog } from "../app/BridgeGate";
import type { Account, AccountCli, AccountGroup } from "../lib/protocol";
import { useAccounts } from "../settings/accounts/useAccounts";
import { accountForNewSessions } from "../settings/accounts/rules";

/** The Accounts CLI a new session of `agent` signs in as (mirrors `session_cli` in src-tauri/src/accounts.rs). */
const SESSION_CLI: Partial<Record<AgentId, AccountCli>> = { claude: "claude", codex: "codex", grok: "grok" };

/** `work@example.com` -> `work@…`. */
const maskEmail = (email: string) => (email.includes("@") ? `${email.slice(0, email.indexOf("@"))}@…` : email);

/** The quiet "as …" next to an agent in the menu: the account Settings › Accounts picked for new sessions, by
 *  its name, else its masked email. Nothing for "This computer" or an agent without accounts. */
export function sessionAccountSuffix(groups: AccountGroup[] | null, agent: AgentId): string {
  const cli = SESSION_CLI[agent];
  const a: Account | null = cli ? accountForNewSessions(groups, cli) : null;
  if (!a || a.id === "default") return "";
  const name = a.label || maskEmail(a.email) || a.id;
  return `as ${name}`;
}

const openers = new Set<() => void>();
/** Open the SESSIONS + menu from elsewhere (the first-run card's "New session"). */
export function openNewSessionMenu(): void {
  for (const f of [...openers]) f();
}

export function SessionsHeader() {
  const [open, setOpen] = useState(false);
  const plus = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const f = () => setOpen(true);
    openers.add(f);
    return () => {
      openers.delete(f);
    };
  }, []);
  return (
    <div className="side-sh side-sh-row">
      <span>{t("nav.sessions")}</span>
      <span className="ss-add">
        <button
          ref={plus}
          type="button"
          className="ss-plus"
          aria-label={t("sessions.new")}
          title={t("sessions.new")}
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          data-testid="session-new"
        >
          <PlusIcon size={14} />
        </button>
        {open && <NewSessionMenu onClose={() => setOpen(false)} trigger={plus} />}
      </span>
    </div>
  );
}

/** The menu spans the section, 8px inside both sidebar edges. */
const MENU_W = "min(240px, calc(var(--side-w) - 16px))";

/** Space kept between the menu and what it must not cover. */
const MENU_GAP = 6;
/** Space kept between the menu's edge and a sidebar row it stops at. */
const ROW_CLEAR = 2;
/** Opened above its row, the menu keeps this much air under the row above it: a band of the sidebar's own colour
 *  (`.ss-pop.ui-pop-top::before`, the same height) covers what lies there. Sidebar rows stand 2px apart, so the air
 *  reaches into the next row's empty top padding, which the band hides; no row shows half. */
export const MENU_AIR = 6;

/** Where the + menu goes and how tall it may be in all (`max`). It opens under its row when the whole list fits above the sidebar's
 *  bottom rows (Automations, Plugins, Settings, You), else on the side with more room, scrolling inside. The edge
 *  that lies over the sidebar stops on a row boundary, so no row shows half under it. */
export function fitMenu(
  anchor: { top: number; bottom: number },
  natural: number,
  gap: number,
  limits: { top: number; bottom: number },
  rows: { top: number; bottom: number }[],
): { side: "top" | "bottom"; max: number } {
  const below = limits.bottom - (anchor.bottom + gap);
  const above = anchor.top - gap - limits.top;
  if (natural <= below || below >= above) {
    let end = Math.min(anchor.bottom + gap + natural, limits.bottom);
    // pull the edge back past every row it would cross (moving it can reach the row before)
    for (let cut; (cut = rows.find((r) => r.top < end + ROW_CLEAR && r.bottom > end && r.top >= anchor.bottom)); ) end = cut.top - ROW_CLEAR;
    return { side: "bottom", max: Math.max(0, end - anchor.bottom - gap) };
  }
  let start = Math.max(anchor.top - gap - natural, limits.top);
  // a row that begins above the band must end above it; one that begins in the band is hidden by it and the menu. The
  // edge lands within a px of `start` (offsets round), so a row within 1px of the band counts as in it, and the menu
  // then stops 1px further down; with rows 2px apart that never reaches the next row's top.
  for (let cut; (cut = rows.find((r) => r.top < start - MENU_AIR + 1 && r.bottom > start - MENU_AIR - 1 && r.bottom <= anchor.top)); ) start = cut.bottom + MENU_AIR + 1;
  return { side: "top", max: Math.max(0, anchor.top - gap - start) };
}

/** Measure the open menu `box` (its list scrolls in `.ss-scroll`) against the sidebar, and again on resize. */
function useMenuFit(box: RefObject<HTMLDivElement | null>, ready: boolean) {
  const [fit, setFit] = useState<{ side: "top" | "bottom"; max: number } | null>(null);
  useLayoutEffect(() => {
    if (!ready) return;
    const measure = () => {
      const menu = box.current;
      const pop = menu?.closest<HTMLElement>(".ss-pop");
      const list = menu?.querySelector<HTMLElement>(".ss-scroll");
      // the row the menu is placed against (its positioned container)
      const anchor = pop?.offsetParent;
      if (!menu || !pop || !list || !(anchor instanceof HTMLElement)) return;
      const side = anchor.closest(".side");
      const a = anchor.getBoundingClientRect();
      const top = side?.querySelector(".side-top")?.getBoundingClientRect().bottom ?? 0;
      const foot = side?.querySelector(".side-foot")?.getBoundingClientRect().top ?? innerHeight;
      // the menu's own header, padding and border around the list, and the list's full height
      const chrome = pop.offsetHeight - list.clientHeight;
      const natural = chrome + list.scrollHeight;
      // the gap between the row and the menu, the same on both sides (offsets ignore the pop-in transform)
      const gap = Math.max(0, pop.classList.contains("ui-pop-bottom") ? pop.offsetTop - anchor.offsetHeight : -pop.offsetTop - pop.offsetHeight);
      const rows = [...(side?.querySelectorAll(".bot-list > *, .ss-list > *, .side-sec > .side-sh, .side > :not(.side-sec)") ?? [])].map((r) => r.getBoundingClientRect());
      const f = fitMenu(a, natural, gap, { top: Math.max(top, 0) + MENU_GAP, bottom: Math.min(foot, innerHeight) - MENU_GAP }, rows);
      // whole px down: a fraction up would set the menu's edge into the row it stops at
      setFit({ side: f.side, max: Math.max(0, Math.floor(f.max - chrome)) });
    };
    measure();
    addEventListener("resize", measure);
    return () => removeEventListener("resize", measure);
    // measured again once placed on its side: the gap to the row differs above and below
  }, [box, ready, fit?.side]);
  return fit;
}

/** Whether the list `el` has more below what it shows: its bottom edge then fades, saying it scrolls. */
function useMoreBelow(el: RefObject<HTMLDivElement | null>, on: boolean) {
  const [more, setMore] = useState(false);
  useLayoutEffect(() => {
    const list = el.current;
    if (!on || !list) return;
    const read = () => setMore(list.scrollTop + list.clientHeight < list.scrollHeight - 1);
    read();
    list.addEventListener("scroll", read, { passive: true });
    const ro = new ResizeObserver(read);
    ro.observe(list);
    return () => {
      list.removeEventListener("scroll", read);
      ro.disconnect();
    };
  }, [el, on]);
  return more;
}

/** The SESSIONS + menu: every agent with its mark and name, the installed ones first (the last one used on top),
 *  the missing ones dimmed with their install line in the tooltip. Picking one opens its New session chat at once
 *  (the folder is the chip under that chat's composer). Arrow keys move, Enter picks, Esc closes. */
function NewSessionMenu({ onClose, trigger }: { onClose: () => void; trigger: RefObject<HTMLButtonElement | null> }) {
  const ss = useSessions();
  const accounts = useAccounts();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ss.agents === null) void getSessions().loadAgents();
  }, [ss.agents]);
  const agents = ss.agents ? menuOrder(ss.agents, ss.recent) : null;
  // the first row takes the focus once the list is there (installed first, so it is the one Enter should pick)
  const ready = agents !== null;
  const fit = useMenuFit(box, ready);
  // once placed (a hidden menu cannot take focus)
  const placed = fit !== null;
  const list = useRef<HTMLDivElement>(null);
  const more = useMoreBelow(list, placed);
  useEffect(() => {
    if (placed) box.current?.querySelector<HTMLButtonElement>("[role=menuitem]")?.focus({ preventScroll: true });
  }, [placed]);
  const close = (why: "escape" | "outside" | "pick") => {
    onClose();
    if (why === "escape") trigger.current?.focus();
  };
  const pick = (id: AgentId) => {
    close("pick");
    getSessions().draft(id);
  };
  return (
    <Popover open onClose={close} align="left" side={fit?.side ?? "bottom"} width={MENU_W} label={t("sessions.new")} className={`ss-pop${ready && !fit ? " ss-pop-measuring" : ""}`}>
      <div
        ref={box}
        role="menu"
        aria-label={t("sessions.new")}
        data-testid="session-menu"
        onKeyDown={(e) => {
          const items = [...(box.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]") ?? [])];
          const i = items.indexOf(document.activeElement as HTMLButtonElement);
          const to = e.key === "ArrowDown" ? i + 1 : e.key === "ArrowUp" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : null;
          if (to === null || !items.length) return;
          e.preventDefault();
          const next = items[(to + items.length) % items.length];
          next?.focus({ preventScroll: true });
          next?.scrollIntoView({ block: "nearest" });
        }}
      >
        <div className="ss-h">{t("sessions.new")}</div>
        {agents === null && <div className="ss-empty">{t("ss.lookingAgents")}</div>}
        <div ref={list} className={`ss-scroll${more ? " more" : ""}`} style={fit ? { maxHeight: fit.max } : undefined} data-testid="session-menu-list">
        {(agents ?? []).map((a) => {
          const label = agentLabel(a.id, ss.agents);
          const account = sessionAccountSuffix(accounts.groups, a.id);
          const missing = !a.path;
          return (
            <button
              key={a.id}
              type="button"
              role="menuitem"
              className={`ss-item${missing ? " off" : ""}`}
              aria-disabled={missing || undefined}
              title={a.path ?? missingNote(a.id)}
              onClick={() => {
                if (!missing) pick(a.id);
              }}
              data-testid={`session-agent-${a.id}`}
            >
              <span className="ss-ic">
                <AgentMark agent={a.id} />
              </span>
              <span className="ss-n ss-n-as" title={account ? `${label} ${account}` : label}>
                <span className="ss-l">{label}</span>
                {account && (
                  <span className="ss-as" data-testid={`session-account-${a.id}`}>
                    {account}
                  </span>
                )}
              </span>
              {missing && <span className="ss-missing">{t("sessions.notInstalled")}</span>}
            </button>
          );
        })}
        </div>
        {hermesOnly(ss.agents) && <AddOmhLine />}
      </div>
    </Popover>
  );
}

/** The + menu's one quiet line for a person who has Hermes but not oh-my-hermes: "Add oh-my-hermes", which runs the
 *  first-run screen's fixed installer and shows its output the same way, under the line. Gone once `omh` is found. */
function AddOmhLine() {
  const add = useAddOmh();
  const running = add.phase === "running";
  return (
    <div className="ss-add-omh" data-testid="session-add-omh-wrap">
      <button
        type="button"
        role="menuitem"
        className="ss-item ss-add-omh-b"
        title={t("omh.add.tip")}
        aria-busy={running || undefined}
        onClick={() => {
          if (!running) void getAddOmh().run();
        }}
        data-testid="session-add-omh"
      >
        <span className="ss-ic">
          {running ? <Spinner size={12} label={t("gate.installing")} /> : <PlusIcon size={12} />}
        </span>
        <span className="ss-n">{running ? t("omh.add.running") : add.phase === "failed" ? t("gate.again") : t("omh.add.line")}</span>
      </button>
      {add.phase === "failed" && add.error && (
        <div className="ss-add-omh-err" role="status" title={add.error} data-testid="session-add-omh-error">
          {add.error}
        </div>
      )}
      {running && <InstallLog lines={add.lines} compact testId="session-add-omh-log" />}
    </div>
  );
}

/** The coding agents the New session tooltip names: the CLIs a person launches to code with (omh stays in the + menu). */
const CODING: AgentId[] = ["claude", "codex", "omo", "dsh", "pi", "omp", "grok", "opencode"];

/** The empty section: one "New session" row built like the sidebar's nav rows, opening the same + menu under it.
 *  What it does and the installed coding agents sit in its tooltip; nothing else shows, nothing is centred or boxed. */
function SessionStart() {
  const ss = useSessions();
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (ss.agents === null) void getSessions().loadAgents();
  }, [ss.agents]);
  const names = (ss.agents ?? [])
    .filter((a) => a.path && CODING.includes(a.id))
    .map((a) => agentDef(a.id).label)
    .join(", ");
  const tip = names ? `${t("onb.sessionsHint")} ${names}` : t("onb.sessionsHint");
  return (
    <div className="ss-none" data-testid="session-none">
      <div className="ss-start-w">
        <button
          ref={btn}
          type="button"
          className="ss-start"
          title={tip}
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          data-testid="session-start"
        >
          <PlusIcon size={16} />
          {t("sessions.new")}
        </button>
        {open && <NewSessionMenu onClose={() => setOpen(false)} trigger={btn} />}
      </div>
    </div>
  );
}

export function SessionList() {
  const s = useStore();
  const ss = useSessions();
  const [confirm, setConfirm] = useState<string | null>(null);
  const [refocus, setRefocus] = useState<string | null>(null);
  const current = s.ui.view === "session" ? s.ui.session : null;
  useEffect(() => {
    if (!refocus) return;
    // the row itself (its × shows only on hover, so it cannot hold focus)
    document.querySelector<HTMLElement>(`[data-testid="session-${refocus}"] .ss-open`)?.focus();
    setRefocus(null);
  }, [refocus]);
  const cancel = (id: string) => {
    setConfirm(null);
    setRefocus(id);
  };
  const ask = (rec: SessionRec) => {
    if (rec.status === "running" || rec.status === "starting") setConfirm(rec.id);
    else getSessions().close(rec.id);
  };
  if (ss.list.length === 0) return <SessionStart />;
  // a draft's folder is not settled yet: it never makes another row show its parent
  const ctx: RowContext = { cwds: ss.list.filter((r) => r.status !== "draft").map((r) => r.cwd), home: ss.home, agents: ss.agents };
  return (
    <nav className="bot-list ss-list" aria-label={t("nav.sessions")} data-testid="session-list">
      {ss.list.map((rec) =>
        confirm === rec.id ? (
          <div
            key={rec.id}
            className="ss-row ss-confirm"
            role="group"
            aria-label={t("ss.stopIn", { agent: agentDef(rec.agent).label, folder: folderName(rec.cwd) })}
            data-testid={`session-confirm-${rec.id}`}
            onKeyDown={(e) => {
              if (e.key !== "Escape") return;
              e.preventDefault();
              e.stopPropagation();
              cancel(rec.id);
            }}
          >
            <span className="ss-q" title={rec.cwd}>
              {t("ss.stopQ", { agent: agentDef(rec.agent).label })}
            </span>
            <button type="button" className="ss-btn" onClick={() => cancel(rec.id)} autoFocus>
              {t("ss.cancel")}
            </button>
            <button
              type="button"
              className="ss-btn"
              onClick={() => {
                setConfirm(null);
                getSessions().close(rec.id);
              }}
              data-testid="session-stop"
            >
              {t("ss.stop")}
            </button>
          </div>
        ) : (
          <Row key={rec.id} rec={rec} ctx={ctx} active={current === rec.id} onClose={() => ask(rec)} />
        ),
      )}
    </nav>
  );
}

/** The row's view of a session's chat: a turn running, and an ask of it open (the Needs-you model). */
function chatLive(s: AppState, key: string | null): ChatLive | undefined {
  const c = key ? s.chats[key] : undefined;
  if (!c) return undefined;
  return { turn: !!c.turn, needsYou: selectAsks(s).some((a) => a.bot === key) };
}

/** Right-click menu of a session row: Rename, Close session. Placed at the pointer, inside the window. */
function SessionMenu({ at, name, onRename, onClose, onDismiss }: { at: { x: number; y: number }; name: string; onRename: () => void; onClose: () => void; onDismiss: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const onDown = (e: globalThis.MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onDismiss();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onDismiss]);
  const items: [string, string, () => void][] = [
    [t("ss.rename"), "session-rename", onRename],
    [t("ss.close"), "session-menu-close", onClose],
  ];
  return (
    <div
      ref={ref}
      className="row-menu"
      style={{ left: at.x, top: at.y }}
      role="menu"
      aria-label={t("ss.actions", { name })}
      data-testid="session-row-menu"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          onDismiss();
          return;
        }
        if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
        e.preventDefault();
        const btns = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
        const i = btns.indexOf(document.activeElement as HTMLButtonElement);
        btns[(i + (e.key === "ArrowDown" ? 1 : btns.length - 1)) % btns.length]?.focus();
      }}
    >
      {items.map(([label, id, fn]) => (
        <button
          key={id}
          type="button"
          role="menuitem"
          className="row-mi"
          data-testid={id}
          onClick={() => {
            onDismiss();
            fn();
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

const MENU_SIZE = { w: 168, h: 70 };

/** The name field of a row being renamed: Enter or leaving it saves, Esc cancels, an empty name goes back to the
 *  automatic one. */
function NameInput({ initial, auto, onDone }: { initial: string; auto: boolean; onDone: (title: string | null | undefined) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);
  const finish = (save: boolean) => {
    if (done.current) return;
    done.current = true;
    const v = (ref.current?.value ?? "").replace(/\s+/g, " ").trim();
    // undefined = leave it as it was; "" = back to the automatic name
    onDone(!save ? undefined : !v ? "" : auto && v === initial ? undefined : v);
  };
  return (
    <input
      ref={ref}
      className="ss-name-in"
      defaultValue={initial}
      maxLength={80}
      aria-label={t("ss.name")}
      placeholder={t("ss.autoName")}
      spellCheck={false}
      data-testid="session-rename-input"
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter" && !composing(e)) {
          e.preventDefault();
          finish(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          finish(false);
        }
      }}
      onBlur={() => finish(true)}
    />
  );
}

function Row({ rec, ctx, active, onClose }: { rec: SessionRec; ctx: RowContext; active: boolean; onClose: () => void }) {
  const s = useStore();
  const key = getSessions().chatKey(rec.id);
  const chat = rec.view === "chat" ? chatLive(s, key) : undefined;
  const m = rowModel(rec, chat, ctx);
  const [editing, setEditing] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  // a chat answers in turns (ring); a terminal just runs (dot)
  const ring = rec.view === "chat" && m.live && !m.needsYou;
  const dot = rec.view !== "chat" && m.live;
  const busySince = ring && key ? (s.chats[key]?.turn?.startedAt ?? null) : null;
  const now = useNow(busySince !== null, 1_000);
  const endEdit = (title: string | null | undefined) => {
    setEditing(false);
    if (title !== undefined) getSessions().rename(rec.id, title);
    requestAnimationFrame(() => wrap.current?.querySelector<HTMLElement>(".ss-open")?.focus());
  };
  const body = (
    <>
      <LiveRing on={ring} size={34} gap={3.5} label={t("ss.answering")} seed={rec.id}>
        <span className="ss-av">
          <AgentMark agent={rec.agent} size={18} />
          {dot && <span className="live-dot" data-testid="live-dot" aria-label={t("ss.liveDot")} />}
        </span>
      </LiveRing>
      <span className="bot-m">
        <span className="bot-r1">
          {editing ? (
            <NameInput initial={m.title} auto={m.titleSource !== "person"} onDone={endEdit} />
          ) : (
            <span
              className="bot-n"
              data-testid="session-name"
              data-source={m.titleSource}
              title={m.titleSource === "folder" ? undefined : m.title}
              onDoubleClick={(e) => {
                e.preventDefault();
                if (rec.status !== "draft") setEditing(true);
              }}
            >
              {m.title}
              {m.where && (
                <span className="ss-where" data-testid="session-where">
                  {" · "}
                  {m.where}
                </span>
              )}
            </span>
          )}
          {m.needsYou ? (
            <span className="bot-t wait" data-testid="bot-time">
              {t("ss.waiting")}
            </span>
          ) : busySince !== null ? (
            <span className="bot-t busy" data-testid="bot-time">
              {busyFor(now - busySince)}
            </span>
          ) : rec.status === "draft" ? null : (
            <span className="bot-t" data-testid="bot-time">
              {shortTime(m.ts)}
            </span>
          )}
        </span>
        <span className="bot-r2">
          <span className={`bot-p${ring ? " live" : ""}`} data-testid="session-sub">
            {m.sub}
          </span>
          {ring && <TypingDots size={3} testId="bot-typing" />}
          {m.needsYou && (
            // the bot row's plain amber dot: no number (the strip carries the count)
            <span className="needs-dot" data-testid="needs" role="status" aria-label={t("ss.needsAnswer")} title={t("ss.needsAnswer")} />
          )}
        </span>
      </span>
    </>
  );
  return (
    <div
      ref={wrap}
      className={`ss-row bot${active ? " active" : ""}${m.needsYou ? " needs" : ""}${menu ? " menu-open" : ""}`}
      data-testid={`session-${rec.id}`}
      data-status={rec.status}
      data-needs-you={m.needsYou ? "true" : undefined}
      onContextMenu={(e) => {
        e.preventDefault();
        if (editing) return;
        // a draft has nothing to rename yet: right-click closes it, as before
        if (rec.status === "draft") return onClose();
        const side = wrap.current?.closest(".side")?.getBoundingClientRect();
        const right = (side?.right ?? window.innerWidth) - 6;
        setMenu({ x: Math.max(6, Math.min(e.clientX, right - MENU_SIZE.w)), y: Math.min(e.clientY, window.innerHeight - MENU_SIZE.h - 6) });
      }}
    >
      {editing ? (
        // no button around a text field: the same row, not clickable while the name is edited
        <div className="ss-open ss-editing" title={rec.cwd}>
          {body}
        </div>
      ) : (
        <button
          type="button"
          className="ss-open"
          onClick={() => s.openSession(rec.id)}
          aria-current={active ? "true" : undefined}
          title={rec.cwd}
        >
          {body}
        </button>
      )}
      {!editing && (
        <button type="button" className="ss-x" aria-label={t("ss.close")} title={t("ss.close")} onClick={onClose} data-testid="session-close">
          <CloseIcon />
        </button>
      )}
      {menu && <SessionMenu at={menu} name={m.title} onRename={() => setEditing(true)} onClose={onClose} onDismiss={() => setMenu(null)} />}
    </div>
  );
}
