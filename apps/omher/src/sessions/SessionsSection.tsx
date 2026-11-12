// SESSIONS in the sidebar: the `+` menu of agents (picking one opens its New session chat at once; the folder is
// picked in that chat, see DraftPane in SessionView), and one row per session started in this run of the app. A draft row reads "New
// session" over its folder until its first message. A chat row shows the bot row's live states: the
// answer ring around the agent mark and the turn's elapsed time while a turn runs, and the amber dot with
// "waiting" while one of its approvals or questions is open (the same asks the Needs-you strip lists). A
// terminal row keeps a live dot while its program runs: a terminal has no turn to ring for.
// Every row ends line 2 with a small mark for the view it opens to: an outlined speech bubble for omher's chat, a
// solid little prompt window for the agent's terminal (a draft shows the way picked for it). A session's state takes
// the time's place on line 1 as a sign and a word: a yellow warning triangle and "waiting" while it waits for the
// person (an open ask, or its terminal rang), a red exclamation mark and "error" when it stopped on an error, a green
// check and "done" when it finished something the person has not opened yet. No dots: the row already has the live
// dot. A session that no longer runs steps back.
// Line 1 is the session's name (the person's, the agent's own title, a summary of the first message, else the
// folder) and line 2 the folder and the agent. Double-click the name, or right-click › Rename, to name it.
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { selectAsks, useStore, type AppState } from "../state/store";
import { CloseIcon, LiveRing, PlusIcon, Popover, TypingDots } from "../ui";
import { busyFor, shortTime } from "../app/time";
import { useNow } from "../elsewhere/useNow";
import { t } from "../i18n";
import { composing } from "../lib/ime";
import { AgentMark } from "./AgentMark";
import { agentDef, agentLabel, draftOpen, folderChoices, folderName, hermesOnly, menuOrder, missingNote, rowModel, tildePath, type AgentId, type ChatLive, type RowContext, type RowMark, type SessionRec, type Unseen } from "./agents";
import { getHost, type PastChat } from "./host";
import { getSessions, useSessions } from "./sessions";
import { pickTitle } from "./titles";
import { onOpenNewSessionMenu } from "./newMenu";
import { getAddOmh } from "./addOmh";
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

export { openNewSessionMenu } from "./newMenu";

export function SessionsHeader() {
  const [open, setOpen] = useState(false);
  const plus = useRef<HTMLButtonElement>(null);
  useEffect(() => onOpenNewSessionMenu(() => setOpen(true)), []);
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
  // the second step: one agent's past conversations
  const [past, setPast] = useState<PastAgent | null>(null);
  const keeps = (agents ?? []).filter((a) => a.path && PAST_AGENTS.includes(a.id as PastAgent)).map((a) => a.id as PastAgent);
  if (past)
    return (
      <Popover open onClose={close} align="left" side={fit?.side ?? "bottom"} width={MENU_W} label={t("ss.past.title", { agent: agentLabel(past, ss.agents) })} className="ss-pop">
        <PastList agent={past} onBack={() => setPast(null)} onPick={() => close("pick")} />
      </Popover>
    );
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
        {keeps.length > 0 && (
          <>
            <div className="ss-sep" />
            <div className="ss-h">{t("ss.past.head")}</div>
            {keeps.map((id) => (
              <button key={id} type="button" role="menuitem" className="ss-item" onClick={() => setPast(id)} data-testid={`session-past-${id}`}>
                <span className="ss-ic">
                  <AgentMark agent={id} />
                </span>
                <span className="ss-n">{agentLabel(id, ss.agents)}</span>
                <span className="ss-chev" aria-hidden="true">
                  ›
                </span>
              </button>
            ))}
          </>
        )}
        </div>
        {hermesOnly(ss.agents) && <AddOmhLine onPick={() => close("pick")} />}
      </div>
    </Popover>
  );
}

/** The agents whose conversations can be continued here: they keep them in files omher can read. */
const PAST_AGENTS = ["claude", "codex"] as const;
type PastAgent = (typeof PAST_AGENTS)[number];

/** How long ago `at` (seconds since the epoch) was: \"now\", \"5m\", \"3h\", \"2d\". */
export function ageOf(at: number, nowMs = Date.now()): string {
  const s = Math.max(0, Math.floor(nowMs / 1000 - at));
  if (s < 60) return t("time.nowShort");
  if (s < 3600) return t("unit.m", { n: Math.floor(s / 60) });
  if (s < 86_400) return t("unit.h", { n: Math.floor(s / 3600) });
  return t("unit.d", { n: Math.floor(s / 86_400) });
}

/** The + menu's second step: `agent`'s recent conversations for the folders the menu offers (the recent ones and
 *  home), newest first. Each row is its title or first words over its folder and age; picking one continues it as
 *  a session. ← (or Esc on the first row's left) goes back to the agents. */
function PastList({ agent, onBack, onPick }: { agent: PastAgent; onBack: () => void; onPick: () => void }) {
  const ss = useSessions();
  const box = useRef<HTMLDivElement>(null);
  const [rows, setRows] = useState<PastChat[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { recent, home } = folderChoices(ss.recent, ss.home);
  const cwds = [...recent, ...(home ? [home] : [])];
  const key = cwds.join("\n");
  useEffect(() => {
    let live = true;
    getHost()
      .pastChats(agent, cwds)
      .then((r) => live && setRows(r))
      .catch((e: unknown) => live && (setRows([]), setError(e instanceof Error ? e.message : String(e))));
    return () => {
      live = false;
    };
    // the folders, not the array's identity
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent, key]);
  useEffect(() => {
    box.current?.querySelector<HTMLButtonElement>(rows?.length ? ".ss-past [role=menuitem]" : "[role=menuitem]")?.focus({ preventScroll: true });
  }, [rows]);
  const label = agentLabel(agent, ss.agents);
  return (
    <div
      ref={box}
      role="menu"
      aria-label={t("ss.past.title", { agent: label })}
      data-testid="session-past-menu"
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") {
          e.preventDefault();
          onBack();
          return;
        }
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
      <button type="button" role="menuitem" className="ss-item ss-back" onClick={onBack} data-testid="session-past-back" aria-label={t("ss.past.back")}>
        <span className="ss-ic" aria-hidden="true">
          ‹
        </span>
        <span className="ss-ic">
          <AgentMark agent={agent} />
        </span>
        <span className="ss-n">{label}</span>
      </button>
      <div className="ss-h">{t("ss.past.head")}</div>
      {rows === null && <div className="ss-empty">{t("ss.past.looking")}</div>}
      {rows !== null && rows.length === 0 && (
        <div className="ss-empty" data-testid="session-past-none" title={error ?? undefined}>
          {t("ss.past.none", { agent: label })}
        </div>
      )}
      {rows !== null && rows.length > 0 && (
        <div className="ss-scroll ss-past" data-testid="session-past-list">
          {rows.map((c) => (
            <button
              key={c.id}
              type="button"
              role="menuitem"
              className="ss-item ss-past-row"
              title={`${c.title}\n${c.cwd}`}
              onClick={() => {
                onPick();
                void getSessions().continuePast(c);
              }}
              data-testid={`session-past-row-${c.id}`}
            >
              <span className="ss-n ss-n-as">
                <span className="ss-l">{c.title}</span>
                <span className="ss-as">
                  {tildePath(c.cwd, ss.home)} · {ageOf(c.at)}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** The + menu's one quiet line for a person who has Hermes but not oh-my-hermes: "Add oh-my-hermes" closes the menu
 *  and opens the sidebar's "!" popover (shown again if it was hidden), the one place its installer runs. */
function AddOmhLine({ onPick }: { onPick: () => void }) {
  return (
    <div className="ss-add-omh" data-testid="session-add-omh-wrap">
      <button
        type="button"
        role="menuitem"
        className="ss-item ss-add-omh-b"
        title={t("omh.add.tip")}
        onClick={() => {
          onPick();
          getAddOmh().offer();
        }}
        data-testid="session-add-omh"
      >
        <span className="ss-ic">
          <PlusIcon size={12} />
        </span>
        <span className="ss-n">{t("omh.add.line")}</span>
      </button>
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

/** Whether session `rec` matches the sidebar search `needle` (lower case): by its name, as its row shows it, or its
 *  folder. */
export function sessionMatches(rec: SessionRec, needle: string): boolean {
  if (!needle) return true;
  const name = rec.status === "draft" ? t("ss.newTitle") : pickTitle(rec, folderName(rec.cwd)).title;
  return [name, rec.cwd].some((v) => v.toLowerCase().includes(needle));
}

export function SessionList({ needle = "", query = "" }: { needle?: string; query?: string }) {
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
  const shown = ss.list.filter((r) => sessionMatches(r, needle));
  // a draft's folder is not settled yet: it never makes another row show its parent
  const ctx: RowContext = { cwds: ss.list.filter((r) => r.status !== "draft").map((r) => r.cwd), home: ss.home, agents: ss.agents };
  return (
    <nav className="bot-list ss-list" aria-label={t("nav.sessions")} data-testid="session-list">
      {needle && shown.length === 0 && (
        <div className="bot-empty" data-testid="session-none-match">
          {t("side.noSession", { q: query })}
        </div>
      )}
      {shown.map((rec) =>
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
          <Row
            key={rec.id}
            rec={rec}
            ctx={ctx}
            // a draft has no view yet: its mark is the way picked for it
            view={rec.status === "draft" ? draftOpen(rec.agent, ss.agents, ss.opens) : rec.view}
            unseen={ss.unseen[rec.id]}
            active={current === rec.id}
            onClose={() => ask(rec)}
          />
        ),
      )}
    </nav>
  );
}

/** The row's view of a session's chat: a turn running, and an ask of it open (the Needs-you model). */
function chatLive(s: AppState, key: string | null): ChatLive | undefined {
  const c = key ? s.chats[key] : undefined;
  if (!c) return undefined;
  return { turn: !!c.turn, needsYou: selectAsks(s).some((a) => a.bot === key), failed: !c.turn && c.lastTurn?.outcome === "error" };
}

/** What a session row's menu offers, in order: Rename, Reveal the folder, Open the folder in the system terminal,
 *  Copy the conversation id (only when the agent reported one), New session here, Close session. */
export function rowMenuItems(rec: Pick<SessionRec, "cwd" | "agentSession">): RowAction[] {
  return ["rename", ...(rec.cwd ? (["reveal", "terminal"] as const) : []), ...(rec.agentSession ? (["copy"] as const) : []), "here", "close"];
}
export type RowAction = "rename" | "reveal" | "terminal" | "copy" | "here" | "close";

/** \"Show in Finder\" on macOS, \"Show in Explorer\" on Windows, \"Show in file manager\" elsewhere. */
const revealWord = () => {
  const ua = typeof navigator === "undefined" ? "" : navigator.userAgent;
  return t(/Windows/i.test(ua) ? "md.explorer" : /Mac/i.test(ua) ? "md.finder" : "ss.menu.files");
};

const ROW_ACTION_LABEL: Record<RowAction, () => string> = {
  rename: () => t("ss.rename"),
  reveal: revealWord,
  terminal: () => t("ss.menu.terminal"),
  copy: () => t("ss.menu.copyId"),
  here: () => t("ss.menu.here"),
  close: () => t("ss.close"),
};
const ROW_ACTION_ID: Record<RowAction, string> = {
  rename: "session-rename",
  reveal: "session-reveal",
  terminal: "session-system-terminal",
  copy: "session-copy-id",
  here: "session-new-here",
  close: "session-menu-close",
};

/** Right-click menu of a session row (rowMenuItems). Placed at the pointer, inside the window. Arrow keys move,
 *  Home / End jump, Enter picks, Esc closes. */
function SessionMenu({ at, name, actions, onPick, onDismiss }: { at: { x: number; y: number }; name: string; actions: RowAction[]; onPick: (a: RowAction) => void; onDismiss: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const onDown = (e: globalThis.MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onDismiss();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onDismiss]);
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
        const btns = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
        const i = btns.indexOf(document.activeElement as HTMLButtonElement);
        const to = e.key === "ArrowDown" ? i + 1 : e.key === "ArrowUp" ? i - 1 + btns.length : e.key === "Home" ? 0 : e.key === "End" ? btns.length - 1 : null;
        if (to === null) return;
        e.preventDefault();
        btns[to % btns.length]?.focus();
      }}
    >
      {actions.map((a) => (
        <button
          key={a}
          type="button"
          role="menuitem"
          className={`row-mi${a === "close" ? " sep" : ""}`}
          data-testid={ROW_ACTION_ID[a]}
          onClick={() => {
            onDismiss();
            onPick(a);
          }}
        >
          {ROW_ACTION_LABEL[a]()}
        </button>
      ))}
    </div>
  );
}

/** The row menu's size, to keep it inside the window: 168 wide, 26 per row plus its padding and separator. */
const MENU_W_PX = 168;
const menuHeight = (rows: number) => rows * 26 + 14;

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

/** The sign before a row's state word: a warning triangle (it waits for you), an exclamation mark (it stopped on an
 *  error), a check (it finished). Three shapes, so the state reads without its colour. */
function StateSign({ mark }: { mark: RowMark }) {
  if (mark === "needs")
    return (
      <svg width="13" height="12" viewBox="0 0 13 12" aria-hidden="true">
        <path d="M6.5 1.3 11.9 10.7H1.1Z" fill="currentColor" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M6.5 4.5v2.8" fill="none" stroke="var(--needs-ink, #1b1204)" strokeWidth="1.4" strokeLinecap="round" />
        <circle cx="6.5" cy="9.2" r="0.8" fill="var(--needs-ink, #1b1204)" />
      </svg>
    );
  if (mark === "error")
    return (
      <svg width="5" height="12" viewBox="0 0 5 12" aria-hidden="true">
        <path d="M2.5 1.5v5.6" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" />
        <circle cx="2.5" cy="10.3" r="1.25" fill="currentColor" />
      </svg>
    );
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2 6.4 4.8 9.2 10 3.2" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** The row's view mark. The two must differ at a glance at 16 by 13: the terminal is a solid window with the prompt
 *  cut out of it, the chat an outlined bubble. The header's line icons at this size both read as "a small box". */
function ViewMark({ view }: { view: "chat" | "terminal" }) {
  return view === "terminal" ? (
    <svg width="16" height="13" viewBox="0 0 16 13" aria-hidden="true">
      <rect width="16" height="13" rx="3" fill="currentColor" />
      <path d="M4 4 6.5 6.5 4 9M8.3 9.2h3.9" fill="none" stroke="var(--ss-cut)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ) : (
    <svg width="16" height="13" viewBox="0 0 16 13" aria-hidden="true">
      <path
        d="M3 .8h10a2.2 2.2 0 0 1 2.2 2.2v4.2A2.2 2.2 0 0 1 13 9.4H7.6l-3.1 2.8V9.4H3A2.2 2.2 0 0 1 .8 7.2V3A2.2 2.2 0 0 1 3 .8Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Row({ rec, ctx, view, unseen, active, onClose }: { rec: SessionRec; ctx: RowContext; view: "chat" | "terminal"; unseen?: Unseen; active: boolean; onClose: () => void }) {
  const s = useStore();
  const key = getSessions().chatKey(rec.id);
  const chat = rec.view === "chat" ? chatLive(s, key) : undefined;
  const m = rowModel(rec, chat, ctx, unseen);
  // what the state's sign says, for a pointer and a screen reader (an error says its own text when it has one)
  const markSays = m.mark === "needs" ? t("ss.mark.bell") : m.mark === "error" ? rec.error || t("ss.mark.error") : t("ss.mark.done");
  const [editing, setEditing] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  // a chat answers in turns (ring); a terminal just runs (dot)
  const ring = rec.view === "chat" && m.live && !m.needsYou;
  const dot = rec.view !== "chat" && m.live;
  const busySince = ring && key ? (s.chats[key]?.turn?.startedAt ?? null) : null;
  const now = useNow(busySince !== null, 1_000);
  const pick = (a: RowAction) => {
    const ss = getSessions();
    if (a === "rename") setEditing(true);
    else if (a === "reveal") void ss.revealFolder(rec.id);
    else if (a === "terminal") void ss.openTerminal(rec.id);
    else if (a === "copy" && rec.agentSession) void navigator.clipboard?.writeText(rec.agentSession).catch(() => undefined);
    else if (a === "here") ss.draftHere(rec.id);
    else if (a === "close") onClose();
  };
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
          {m.mark ? (
            <span className={`bot-t ${m.mark === "needs" ? "wait" : m.mark === "error" ? "err" : "ok"}`} data-testid="bot-time">
              <span
                className={`ss-sign ${m.mark}`}
                data-testid={m.needsYou ? "needs" : "session-mark"}
                data-mark={m.mark}
                role="img"
                aria-label={m.needsYou ? t("ss.needsAnswer") : markSays}
                title={m.needsYou ? t("ss.needsAnswer") : markSays}
              >
                <StateSign mark={m.mark} />
              </span>
              {t(m.mark === "needs" ? "ss.waiting" : m.mark === "error" ? "ss.at.error" : "ss.at.done")}
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
          <span
            className="ss-view"
            role="img"
            data-testid="session-view"
            data-view={view}
            aria-label={t(view === "terminal" ? "ss.open.terminal" : "ss.open.chat")}
            title={t(view === "terminal" ? "ss.open.terminal" : "ss.open.chat")}
          >
            <ViewMark view={view} />
          </span>
        </span>
      </span>
    </>
  );
  return (
    <div
      ref={wrap}
      className={`ss-row bot${active ? " active" : ""}${m.needsYou ? " needs" : ""}${m.over ? " over" : ""}${menu ? " menu-open" : ""}`}
      data-testid={`session-${rec.id}`}
      data-status={rec.status}
      data-needs-you={m.needsYou ? "true" : undefined}
      data-mark={m.needsYou ? "needs" : (m.mark ?? undefined)}
      onContextMenu={(e) => {
        e.preventDefault();
        if (editing) return;
        // a draft has nothing to rename yet: right-click closes it, as before
        if (rec.status === "draft") return onClose();
        const side = wrap.current?.closest(".side")?.getBoundingClientRect();
        const right = (side?.right ?? window.innerWidth) - 6;
        const h = menuHeight(rowMenuItems(rec).length);
        setMenu({ x: Math.max(6, Math.min(e.clientX, right - MENU_W_PX)), y: Math.max(6, Math.min(e.clientY, window.innerHeight - h - 6)) });
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
      {menu && <SessionMenu at={menu} name={m.title} actions={rowMenuItems(rec)} onPick={pick} onDismiss={() => setMenu(null)} />}
    </div>
  );
}
