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
import { Fragment, memo, useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import { getStore, useStore } from "../state/store";
import { CloseIcon, LiveRing, PlusIcon, Popover, TypingDots } from "../ui";
import { busyFor, shortTime } from "../app/time";
import { t } from "../i18n";
import { composing } from "../lib/ime";
import { AgentMark } from "./AgentMark";
import { agentDef, agentLabel, draftFolder, folderChoices, folderName, hermesOnly, installLine, isTerminalRec, menuFocus, menuOrder, missingNote, parentPath, SHELL, termActivity, termFallbackName, termGroups, terminalAgents, termMarkAgent, termStatus, tildePath, type AgentId, type AgentInfo, type RowMark, type SessionRec, type TermStatus, type Unseen } from "./agents";
import { TermRowMark } from "./TermRowMark";
import { SplitGlyph, useSplit, useSplitPrune } from "./SplitView";
import { groupOf, groupSessions, paneOf } from "./splitState";
import type { Layout } from "../terminal/layout";
import { countRender, useAnyFlowing, useTermFace } from "./termActivity";
import { allCollapsed, collapseOthers, folderSummary, getFolderPrefs, moveFolder, orderFolders, revealFolder as openFolder, setAllFolders, setFolderPrefs, toggleFolder, useFolderPrefs } from "./folders";
import { ChevronDown, ChevronRight } from "../ui/icons";
import { CUE_PX, useEdgeFade } from "../sidebar/edgeFade";
import { getHost, type PastChat } from "./host";
import { getSessions, useSessions } from "./sessions";
import { pickTitle } from "./titles";
import { onOpenNewSessionMenu } from "./newMenu";
import { TermLinkGone } from "./termLinkOpen";
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
      <span>{t("nav.terminals")}</span>
      <span className="ss-add">
        <CollapseAllButton />
        <button
          ref={plus}
          type="button"
          className="ss-plus"
          aria-label={t("term.new")}
          title={t("term.new")}
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          data-testid="session-new"
        >
          <PlusIcon size={14} />
        </button>
        {open && <NewSessionMenu onClose={() => setOpen(false)} trigger={plus} />}
      </span>
      <TermLinkGone />
    </div>
  );
}

/** The menu spans the section, 8px inside both sidebar edges. */
const MENU_W = "min(240px, calc(var(--side-w) - 16px))";

/** Space kept between the menu and what it must not cover. */
const MENU_GAP = 6;
/** Space kept between the menu's edge and a sidebar row it stops at. */
const ROW_CLEAR = 2;
/** Opened above its row, the menu keeps at least this much air under the row above it: a band of the sidebar's own
 *  colour (`.ss-pop.ui-pop-top::before`, the same height) covers what lies there. Sidebar rows stand 2px apart, so the
 *  air reaches into the next row's empty top padding, which the band hides; no row shows half. */
export const MENU_AIR = 6;

/** Where the + menu goes, how tall it may be in all (`max`) and, opened above its row, how tall the band of air over
 *  it is (`air`). It opens under its row when the whole list fits above the sidebar's bottom rows (Automations,
 *  Plugins, Settings, You), else on the side with more room. A list that fits whole above its row is never cut: the
 *  sidebar row its top edge would cross is hidden whole by the band instead. A list that does not fit scrolls
 *  inside, and its edge stops on a row boundary. Either way no row shows half. */
export function fitMenu(
  anchor: { top: number; bottom: number },
  natural: number,
  gap: number,
  limits: { top: number; bottom: number },
  rows: { top: number; bottom: number }[],
): { side: "top" | "bottom"; max: number; air: number } {
  const below = limits.bottom - (anchor.bottom + gap);
  const above = anchor.top - gap - limits.top;
  if (natural <= below || below >= above) {
    let end = Math.min(anchor.bottom + gap + natural, limits.bottom);
    // pull the edge back past every row it would cross (moving it can reach the row before)
    for (let cut; (cut = rows.find((r) => r.top < end + ROW_CLEAR && r.bottom > end && r.top >= anchor.bottom)); ) end = cut.top - ROW_CLEAR;
    return { side: "bottom", max: Math.max(0, end - anchor.bottom - gap), air: 0 };
  }
  const whole = anchor.top - gap - natural;
  if (whole >= limits.top) {
    // the band grows up to the top of each row it would cross (rows stand 2px apart: it ends 1px under the row
    // before); never over the sidebar's own top rows, where the list is cut as below
    let air = MENU_AIR;
    for (let cut; (cut = rows.find((r) => r.top < whole - air + 1 && r.bottom > whole - air - 1 && r.bottom <= anchor.top)); ) air = whole - cut.top + 1;
    if (whole - air >= limits.top - MENU_GAP) return { side: "top", max: natural, air };
  }
  let start = Math.max(whole, limits.top);
  // a row that begins above the band must end above it; one that begins in the band is hidden by it and the menu. The
  // edge lands within a px of `start` (offsets round), so a row within 1px of the band counts as in it, and the menu
  // then stops 1px further down; with rows 2px apart that never reaches the next row's top.
  for (let cut; (cut = rows.find((r) => r.top < start - MENU_AIR + 1 && r.bottom > start - MENU_AIR - 1 && r.bottom <= anchor.top)); ) start = cut.bottom + MENU_AIR + 1;
  return { side: "top", max: Math.max(0, anchor.top - gap - start), air: MENU_AIR };
}

/** Measure the open menu `box` (its list scrolls in `.ss-scroll`) against the sidebar, and again on resize and
 *  whenever `shape` changes (the folded agents opened or closed). */
function useMenuFit(box: RefObject<HTMLDivElement | null>, ready: boolean, shape = "") {
  const [fit, setFit] = useState<{ side: "top" | "bottom"; max: number } | null>(null);
  useLayoutEffect(() => {
    if (!ready) return;
    const pop = box.current?.closest<HTMLElement>(".ss-pop");
    const measure = () => {
      const menu = box.current;
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
      // rows as drawn: a group's rows, not the group (TERMINALS lists folder groups), and only what its list shows
      const rows = [...(side?.querySelectorAll(".bot-list:not(.ss-list) > *, .ss-list .tg > *, .side-sec > .side-sh, .side > :not(.side-sec)") ?? [])]
        .map((r) => {
          const b = r.getBoundingClientRect();
          const box = r.closest(".bot-list")?.getBoundingClientRect();
          return box && (b.bottom <= box.top || b.top >= box.bottom) ? null : b;
        })
        .filter((b): b is DOMRect => !!b);
      const f = fitMenu(a, natural, gap, { top: Math.max(top, 0) + MENU_GAP, bottom: Math.min(foot, innerHeight) - MENU_GAP }, rows);
      // the band above an upward menu (`.ss-pop.ui-pop-top::before`) is as tall as the air it keeps
      pop.style.setProperty("--ss-air", `${f.air}px`);
      // whole px down: a fraction up would set the menu's edge into the row it stops at
      setFit({ side: f.side, max: Math.max(0, Math.floor(f.max - chrome)) });
    };
    measure();
    addEventListener("resize", measure);
    return () => {
      removeEventListener("resize", measure);
      // the next thing shown in this box (an agent's past conversations) keeps the plain band
      pop?.style.removeProperty("--ss-air");
    };
    // measured again once placed on its side: the gap to the row differs above and below
  }, [box, ready, fit?.side, shape]);
  return fit;
}

/** Whether the list `el` has more below what it shows: its bottom edge then fades, saying it scrolls. */
function useMoreBelow(el: RefObject<HTMLDivElement | null>, on: boolean, shape: boolean) {
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
  }, [el, on, shape]);
  return more;
}

/** The SESSIONS + menu: the installed agents with their mark and name (by tier; the last one used has the focus), then one "More
 *  agents" row that opens the agents that are not installed, dimmed, each with its install line as text (picking one
 *  copies that line; omher installs nothing), then "Continue a conversation", there as the menu first opens. Picking
 *  an installed agent opens its New session chat at once (the folder is the chip under that chat's composer). Arrow
 *  keys move, Enter picks, Esc closes. */
function NewSessionMenu({ onClose, trigger }: { onClose: () => void; trigger: RefObject<HTMLButtonElement | null> }) {
  const ss = useSessions();
  const accounts = useAccounts();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ss.agents === null) void getSessions().loadAgents();
  }, [ss.agents]);
  const parts = ss.agents ? terminalAgents(ss.agents, ss.recent) : null;
  const agents = parts ? [...parts.shown, ...parts.more] : null;
  // the agents that are not installed stay folded until the person opens them
  const [unfold, setUnfold] = useState(false);
  const [copied, setCopied] = useState<AgentId | null>(null);
  // the first row takes the focus once the list is there (installed first, so it is the one Enter should pick)
  const ready = agents !== null;
  // the second step: one agent's past conversations (its own list: this menu is not measured while it shows)
  const [past, setPast] = useState<PastAgent | null>(null);
  // the folder it starts in: the chip at the top (the last folder used, else home)
  const [folder, setFolder] = useState<string | null>(null);
  const [folders, setFolders] = useState(false);
  // measured again whenever its rows change (the folded agents, the folder list)
  const fit = useMenuFit(box, ready && !past, `${unfold ? "open" : "folded"}:${folders ? "folders" : ""}`);
  // once placed (a hidden menu cannot take focus)
  const placed = fit !== null;
  const list = useRef<HTMLDivElement>(null);
  const more = useMoreBelow(list, placed, unfold);
  const first = parts ? menuFocus(parts.shown, ss.recent) : null;
  useEffect(() => {
    if (!placed) return;
    const row = first ? box.current?.querySelector<HTMLButtonElement>(`[data-testid="session-agent-${first}"]`) : null;
    (row ?? box.current?.querySelector<HTMLButtonElement>("[role=menuitem]"))?.focus({ preventScroll: true });
    // focus once, when the menu is placed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placed]);
  const close = (why: "escape" | "outside" | "pick") => {
    onClose();
    if (why === "escape") trigger.current?.focus();
  };
  const at = folder ?? draftFolder(ss.recent, ss.home);
  const pick = (id: AgentId) => {
    close("pick");
    getSessions().startTerminal(id, at || undefined);
  };
  const choose = async () => {
    const got = await getSessions().pickFolder(at || ss.home || "");
    if (got) setFolder(got);
    setFolders(false);
  };
  const { recent: recentFolders, home } = folderChoices(ss.recent, ss.home);
  // an agent that is not installed: its install line goes to the clipboard, as text (omher runs nothing)
  const copyInstall = (id: AgentId) => {
    void navigator.clipboard?.writeText(installLine(id)).then(
      () => setCopied(id),
      () => undefined,
    );
  };
  const row = (a: NonNullable<typeof agents>[number]) => {
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
        onClick={() => (missing ? copyInstall(a.id) : pick(a.id))}
        data-testid={`session-agent-${a.id}`}
      >
        <span className="ss-ic">
          <AgentMark agent={a.id} />
        </span>
        <span className="ss-n ss-n-as" title={account ? `${label} ${account}` : label}>
          {missing ? (
            // the state word shares the name's line, so the install line under them has the whole width
            <span className="ss-head">
              <span className="ss-l">{label}</span>
              <span className="ss-missing">{copied === a.id ? t("ss.copiedInstall") : t("sessions.notInstalled")}</span>
            </span>
          ) : (
            <span className="ss-l">{label}</span>
          )}
          {account && !missing && (
            <span className="ss-as" data-testid={`session-account-${a.id}`}>
              {account}
            </span>
          )}
          {missing && (
            // whole, on as many lines as it needs; it breaks between its words before it breaks inside one
            <span className="ss-as ss-install" data-testid={`session-install-${a.id}`}>
              {installLine(a.id).split(" ").map((word, i) => (
                <Fragment key={i}>
                  {i > 0 && " "}
                  <span className="ss-tok">{word}</span>
                </Fragment>
              ))}
            </span>
          )}
        </span>
      </button>
    );
  };
  if (past)
    return (
      <Popover open onClose={close} align="left" side={fit?.side ?? "bottom"} width={MENU_W} label={t("ss.past.title", { agent: agentLabel(past, ss.agents) })} className="ss-pop">
        <PastList agent={past} onBack={() => setPast(null)} onPick={() => close("pick")} />
      </Popover>
    );
  return (
    <Popover open onClose={close} align="left" side={fit?.side ?? "bottom"} width={MENU_W} label={t("term.new")} className={`ss-pop${ready && !fit ? " ss-pop-measuring" : ""}`}>
      <div
        ref={box}
        role="menu"
        aria-label={t("term.new")}
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
        <div className="ss-h">{t("term.new")}</div>
        {agents === null && <div className="ss-empty">{t("ss.lookingAgents")}</div>}
        <button
          type="button"
          role="menuitem"
          className="ss-item ss-at"
          aria-expanded={folders}
          title={at}
          onClick={() => setFolders((v) => !v)}
          data-testid="session-folder"
        >
          <span className="ss-ic" aria-hidden="true">
            <FolderGlyph />
          </span>
          <span className="ss-n">{at ? folderName(at) : t("sessions.findingHome")}</span>
          <span className="ss-path">{at ? parentPath(tildePath(at, ss.home)) : ""}</span>
        </button>
        {folders && (
          <div className="ss-folders" data-testid="session-folders">
            {[...recentFolders, ...(home ? [home] : [])].map((cwd) => (
              <button
                key={cwd}
                type="button"
                role="menuitem"
                className={`ss-item${cwd === at ? " on" : ""}`}
                title={cwd}
                onClick={() => {
                  setFolder(cwd);
                  setFolders(false);
                }}
                data-testid="session-folder-pick"
              >
                <span className="ss-ic" />
                <span className="ss-n">{folderName(cwd)}</span>
                <span className="ss-path">{parentPath(tildePath(cwd, ss.home))}</span>
              </button>
            ))}
            <button type="button" role="menuitem" className="ss-item" onClick={() => void choose()} data-testid="session-choose">
              <span className="ss-ic" />
              <span className="ss-n">{t("sessions.choose")}</span>
            </button>
          </div>
        )}
        <div className="ss-sep" />
        <div ref={list} className={`ss-scroll${more ? " more" : ""}`} style={fit ? { maxHeight: fit.max } : undefined} data-testid="session-menu-list">
        {ready && (
          <button key="shell" type="button" role="menuitem" className="ss-item" title={t("term.shellTip")} onClick={() => pick(SHELL)} data-testid="session-agent-shell">
            <span className="ss-ic">
              <TermRowMark agent={null} size={16} />
            </span>
            <span className="ss-n ss-n-as">
              <span className="ss-l">{t("term.shell")}</span>
            </span>
          </button>
        )}
        {(parts?.shown ?? []).map(row)}
        {parts && parts.more.length > 0 && (
          <button
            type="button"
            role="menuitem"
            className="ss-item ss-more"
            aria-expanded={unfold}
            onClick={() => setUnfold((v) => !v)}
            data-testid="session-more"
          >
            <span className="ss-ic ss-more-ic" aria-hidden="true">
              {unfold ? "⌄" : "›"}
            </span>
            <span className="ss-n">{t("ss.moreAgents")}</span>
            <span className="ss-missing">{parts.more.length}</span>
          </button>
        )}
        {unfold && parts?.more.map(row)}
        </div>
        {more && (
          <button
            type="button"
            className="ss-more-cue"
            tabIndex={-1}
            aria-hidden="true"
            onClick={() => list.current?.scrollBy({ top: list.current.clientHeight - 32, behavior: "smooth" })}
            data-testid="session-menu-more-below"
          >
            <ChevronDown size={10} />
            {t("term.moreBelow")}
          </button>
        )}
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
      <button type="button" role="menuitem" className="ss-item ss-past-back" onClick={onBack} data-testid="session-past-back" aria-label={t("ss.past.back")}>
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

/** The coding agents the New session tooltip names: every agent the shell offers (in menu order) but oh-my-hermes,
 *  which stays in the + menu. */
const coding = (a: AgentInfo) => a.id !== "omh";

/** The empty section: one "New session" row built like the sidebar's nav rows, opening the same + menu under it.
 *  What it does and the installed coding agents sit in its tooltip; nothing else shows, nothing is centred or boxed. */
function SessionStart() {
  const ss = useSessions();
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (ss.agents === null) void getSessions().loadAgents();
  }, [ss.agents]);
  const names = menuOrder(ss.agents ?? [], [])
    .filter((a) => a.path && coding(a))
    .map((a) => agentDef(a.id).label)
    .join(", ");
  const tip = names ? `${t("term.empty")} ${names}` : t("term.empty");
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
          {t("term.new")}
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
  const sp = useSplit();
  useSplitPrune();
  const [confirm, setConfirm] = useState<string | null>(null);
  const [refocus, setRefocus] = useState<string | null>(null);
  const current = s.ui.view === "session" ? s.ui.session : null;
  // the split the open session is in: its rows carry the split's shape
  const openSplit = current ? groupOf(sp.groups, current) : null;
  useEffect(() => {
    if (!refocus) return;
    // the row itself (its × shows only on hover, so it cannot hold focus)
    document.querySelector<HTMLElement>(`[data-testid="session-${refocus}"] .ss-open`)?.focus();
    setRefocus(null);
  }, [refocus]);
  const folders = useFolderPrefs();
  const currentCwd = current ? ss.list.find((r) => r.id === current)?.cwd : undefined;
  // the open terminal's folder opens (reveal) and its row scrolls into view inside TERMINALS (never moving BOTS)
  useEffect(() => {
    if (currentCwd !== undefined) openFolder(currentCwd);
  }, [current, currentCwd]);
  // ...and stays in view when the region changes size (the dock gains a row, the window shrinks) or rows land above
  // it (a newer folder lists first): only then, never against the person's own scrolling
  const nav = useRef<HTMLElement>(null);
  const navRef = useEdgeFade(nav);
  const rowsKey = ss.list.map((r) => r.id).join(",");
  useEffect(() => {
    if (!current) return;
    const rowOf = () => nav.current?.querySelector<HTMLElement>(`[data-testid="session-${CSS.escape(current)}"]`) ?? null;
    // the band above the region's end is kept for the "more below" chevron (a row reaching into it is hidden)
    const inView = () => {
      const list = nav.current;
      const row = rowOf();
      if (!list || !row) return false;
      const l = list.getBoundingClientRect();
      const r = row.getBoundingClientRect();
      return r.top >= l.top && r.bottom <= l.bottom - CUE_PX;
    };
    // held in view until the person scrolls TERMINALS themselves (wheel, touch, keys, the scrollbar): scrolling BOTS
    // brings the dock in and shrinks this region, which must not undo their own scroll. A scroll the browser makes
    // (the region shrank) does not let go of the row.
    let held = true;
    const keep = () => {
      const row = rowOf();
      if (!held || !row || inView()) return;
      row.scrollIntoView({ block: "nearest" });
    };
    const own = () => {
      held = false;
    };
    const id = requestAnimationFrame(keep);
    const el = nav.current;
    const input = ["wheel", "touchmove", "keydown", "pointerdown"] as const;
    for (const k of input) el?.addEventListener(k, own, { passive: true });
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(keep) : null;
    if (el) ro?.observe(el);
    return () => {
      cancelAnimationFrame(id);
      for (const k of input) el?.removeEventListener(k, own);
      ro?.disconnect();
    };
  }, [current, folders.collapsed, rowsKey]);
  const cancel = (id: string) => {
    setConfirm(null);
    setRefocus(id);
  };
  // one function for every row (a memoised row keeps its props)
  const ask = useCallback((rec: SessionRec) => {
    if (rec.status === "running" || rec.status === "starting") setConfirm(rec.id);
    else getSessions().close(rec.id);
  }, []);
  countRender("SessionList");
  const terms = ss.list.filter((r) => isTerminalRec(ss.agents, r));
  // each row's spinner and age, and a collapsed folder's spinner, follow the terminal's output on their own
  // (termActivity.ts): output never re-renders this list
  // the ages tick while any terminal runs (as one list-wide clock did before)
  const ticking = terms.some((r) => r.status === "running" || r.status === "starting");
  if (terms.length === 0) return <SessionStart />;
  const shown = terms.filter((r) => sessionMatches(r, needle));
  return (
    <nav ref={navRef} className="bot-list ss-list" aria-label={t("nav.terminals")} data-testid="session-list">
      {needle && shown.length === 0 && (
        <div className="bot-empty" data-testid="session-none-match">
          {t("side.noSession", { q: query })}
        </div>
      )}
      {orderFolders(termGroups(shown), folders.order).map((g, gi, all) => {
        // a search shows every match, collapsed or not
        const shut = !needle && folders.collapsed.includes(g.cwd);
        return (
        <div key={g.cwd} className={`tg${shut ? " shut" : ""}`} role="group" aria-label={folderName(g.cwd)} data-testid="term-group" data-cwd={g.cwd} data-collapsed={shut ? "true" : undefined}>
          <FolderHead
            cwd={g.cwd}
            home={ss.home}
            shut={shut}
            index={gi}
            all={all.map((x) => x.cwd)}
            summary={{ ...folderSummary(g.rows.map((r) => termStatus(r, ss.unseen[r.id], 0))), running: g.rows.filter((r) => (r.status === "running" || r.status === "starting") && termMarkAgent(r) !== null).length }}
            flowIds={shut ? g.rows.filter((r) => (r.status === "running" || r.status === "starting") && ss.unseen[r.id] !== "bell").map((r) => r.id) : NO_IDS}
          />
          {!shut && g.rows.map((rec) =>
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
              <TermRow key={rec.id} rec={rec} agents={ss.agents} unseen={ss.unseen[rec.id]} active={current === rec.id} ticking={ticking} lang={s.ui.lang} onClose={ask} split={openSplit && paneOf(rec.id) !== null && groupSessions(openSplit).includes(rec.id) ? openSplit.layout : null} />
            ),
          )}
        </div>
        );
      })}
    </nav>
  );
}

/** A small folder outline, the TERMINALS group header's icon. */
function FolderGlyph() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round" aria-hidden="true">
      <path d="M3.5 7.5A2 2 0 0 1 5.5 5.5h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z" />
    </svg>
  );
}

/** "Collapse all" / "Expand all" for the TERMINALS folders, in the section header next to its +. */
function CollapseAllButton() {
  const ss = useSessions();
  const prefs = useFolderPrefs();
  const all = [...new Set(ss.list.filter((r) => isTerminalRec(ss.agents, r)).map((r) => r.cwd))];
  if (all.length < 2) return null;
  const shut = allCollapsed(prefs, all);
  const label = shut ? t("term.expandAll") : t("term.collapseAll");
  return (
    <button type="button" className="ss-plus ss-fold-all" aria-label={label} title={label} onClick={() => setFolderPrefs(setAllFolders(getFolderPrefs(), all, !shut))} data-testid="term-collapse-all" data-all={shut ? "collapsed" : "expanded"}>
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {shut ? <path d="m7 9 5-5 5 5M7 15l5 5 5-5" /> : <path d="m7 4 5 5 5-5M7 20l5-5 5 5" />}
      </svg>
    </button>
  );
}

/** Drag folder headers to reorder them: the header under the pointer is where it goes (saved on this computer). */
function useFolderDrag(cwd: string, all: readonly string[]) {
  return (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || (e.target as Element).closest("button:not(.tg-open)")) return;
    const sx = e.clientX;
    const sy = e.clientY;
    const head = e.currentTarget;
    let moving = false;
    const heads = () => [...(head.closest(".ss-list")?.querySelectorAll<HTMLElement>(".tg-h") ?? [])];
    const slot = (y: number) => {
      const hs = heads();
      const i = hs.findIndex((h) => {
        const g = h.closest(".tg")!.getBoundingClientRect();
        return y >= g.top && y <= g.bottom;
      });
      return i;
    };
    const move = (ev: PointerEvent) => {
      if (!moving && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 5) return;
      moving = true;
      head.classList.add("lifted");
      const to = slot(ev.clientY);
      for (const [i, h] of heads().entries()) h.classList.toggle("drop", i === to && h !== head);
    };
    const up = (ev: PointerEvent) => {
      removeEventListener("pointermove", move);
      removeEventListener("pointerup", up);
      head.classList.remove("lifted");
      for (const h of heads()) h.classList.remove("drop");
      if (!moving) return;
      const to = slot(ev.clientY);
      if (to >= 0 && all[to] !== cwd) setFolderPrefs({ ...getFolderPrefs(), order: moveFolder(all, cwd, to) });
      // the click that follows a drag toggles nothing
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
}

const NO_IDS: readonly string[] = [];

/** A TERMINALS group's header, Orca-style: a chevron that collapses its sessions (kept on this computer), the
 *  folder's name (semibold) and its git branch in small grey; collapsed, it shows how many sessions it holds and
 *  their live summary (the spinner while one prints, the amber dot while one waits for you, a red dot when one
 *  failed). Right-click: New terminal here, Collapse others, Show in Finder. Drag to reorder. */
function FolderHead({ cwd, home, shut, index, all, summary: base, flowIds }: { cwd: string; home: string | null; shut: boolean; index: number; all: string[]; summary: ReturnType<typeof folderSummary> & { running: number }; flowIds: readonly string[] }) {
  // the spinner: output flows in one of its running sessions that is not waiting for the person (termStatus's
  // "busy"), followed here and not through the list
  const busy = useAnyFlowing(flowIds);
  const summary = { ...base, busy };
  const [branch, setBranch] = useState("");
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const drag = useFolderDrag(cwd, all);
  useEffect(() => {
    let live = true;
    if (cwd)
      void getHost()
        .branch(cwd)
        .then((b) => live && setBranch(b))
        .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [cwd]);
  const name = folderName(cwd);
  const toggle = () => setFolderPrefs(toggleFolder(getFolderPrefs(), cwd));
  return (
    <div
      className={`tg-h${index === 0 ? " first" : ""}`}
      title={tildePath(cwd, home)}
      data-testid="term-group-head"
      onPointerDown={drag}
      onContextMenu={(e) => {
        e.preventDefault();
        const side = e.currentTarget.closest(".side")?.getBoundingClientRect();
        const right = (side?.right ?? innerWidth) - 6;
        setMenu({ x: Math.max(6, Math.min(e.clientX, right - MENU_W_PX)), y: Math.max(6, Math.min(e.clientY, innerHeight - menuHeight(3) - 6)) });
      }}
    >
      <button type="button" className="tg-open" aria-expanded={!shut} aria-label={t(shut ? "term.folderOpen" : "term.folderClose", { name })} onClick={toggle} data-testid="term-group-toggle">
        <span className="tg-chev" aria-hidden="true">{shut ? <ChevronRight size={9} /> : <ChevronDown size={9} />}</span>
        <span className="tg-ic">
          <FolderGlyph />
        </span>
        <span className="tg-n">{name}</span>
        {shut && (
          <span className="tg-sum" data-testid="term-group-summary" data-busy={summary.busy ? "true" : undefined} data-needs={summary.needs ? "true" : undefined} data-failed={summary.failed ? "true" : undefined}>
            {summary.busy && <TermStatusGlyph status="busy" />}
            {summary.running > 0 && (
              <>
                <span className="tg-run" data-testid="term-group-running">
                  {t("term.folderRunning", { n: summary.running })}
                </span>
                <span aria-hidden="true">·</span>
              </>
            )}
            {/* the count says what it counts: "2 sessions", never a bare number */}
            <span className="tg-count" data-testid="term-group-count" data-n={summary.count}>
              {summary.count === 1 ? t("term.folderCount1") : t("term.folderCountN", { n: summary.count })}
            </span>
            {summary.needs && <span className="tg-dot needs" title={t("ss.mark.bell")} />}
            {summary.failed && <span className="tg-dot err" title={t("ss.mark.error")} />}
          </span>
        )}
        {branch && (
          <span className="tg-b" data-testid="term-group-branch">
            {branch}
          </span>
        )}
      </button>
      {menu && <FolderMenu at={menu} cwd={cwd} all={all} onDismiss={() => setMenu(null)} />}
    </div>
  );
}

/** A folder header's right-click menu: New terminal here (the + menu's Shell in that folder), Collapse others,
 *  Show in Finder. */
function FolderMenu({ at, cwd, all, onDismiss }: { at: { x: number; y: number }; cwd: string; all: string[]; onDismiss: () => void }) {
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
    ["term-folder-new", t("term.here"), () => void getSessions().startTerminal(SHELL, cwd)],
    ["term-folder-others", t("term.collapseOthers"), () => setFolderPrefs(collapseOthers(getFolderPrefs(), all, cwd))],
    ["term-folder-reveal", revealWord(), () => void getHost().reveal(cwd).catch(() => undefined)],
  ];
  return (
    <div
      ref={ref}
      className="row-menu"
      style={{ left: at.x, top: at.y }}
      role="menu"
      aria-label={folderName(cwd)}
      data-testid="term-folder-menu"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          onDismiss();
          return;
        }
        const btns = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
        const i = btns.indexOf(document.activeElement as HTMLButtonElement);
        const to = e.key === "ArrowDown" ? i + 1 : e.key === "ArrowUp" ? i - 1 + btns.length : null;
        if (to === null) return;
        e.preventDefault();
        btns[to % btns.length]?.focus();
      }}
    >
      {items.map(([id, label, run]) => (
        <button
          key={id}
          type="button"
          role="menuitem"
          className="row-mi"
          data-testid={id}
          onClick={() => {
            onDismiss();
            run();
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** The row's status glyph, 12px: an amber arc spinning while output flows (static under reduced motion), the bell's
 *  warning triangle, a green outlined check on exit 0, a red x on a non-zero exit; nothing when idle. */
export function TermStatusGlyph({ status }: { status: TermStatus }) {
  const label = status === "busy" ? t("term.st.busy") : status === "bell" ? t("ss.mark.bell") : status === "ok" ? t("ss.at.done") : status === "err" ? t("ss.mark.error") : "";
  return (
    <span className={`tst${status ? ` ${status}` : ""}`} data-testid="term-status" data-status={status ?? "idle"} role={status ? "img" : undefined} aria-label={label || undefined} title={label || undefined}>
      {status === "busy" && (
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M6 1.6A4.4 4.4 0 1 1 1.6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      )}
      {status === "ok" && (
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <path d="M3.7 6.2 5.3 7.8 8.4 4.4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {status === "err" && (
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M3.4 3.4 8.6 8.6M8.6 3.4 3.4 8.6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      )}
      {status === "bell" && <StateSign mark="needs" />}
    </span>
  );
}

/** `now`, `12m`, `3h`, `2d` since `ms`. */
const ageMs = (ms: number, now: number) => ageOf(ms / 1000, now);

/** What a session row's menu offers, in order: Rename, Reveal the folder, Open the folder in the system terminal,
 *  Copy the conversation id (only when the agent reported one), New session here, Close session. */
export function rowMenuItems(rec: Pick<SessionRec, "cwd" | "agentSession">): RowAction[] {
  return ["rename", ...(rec.cwd ? (["reveal", "terminal"] as const) : []), ...(rec.agentSession ? (["copy"] as const) : []), "here", "close"];
}
/** A TERMINALS row's menu: Rename, Reveal, Open in the system terminal, Copy link (its `omher://terminal/…`),
 *  New terminal here, Close. */
export function termMenuItems(rec: Pick<SessionRec, "cwd" | "linkId">): RowAction[] {
  return ["rename", ...(rec.cwd ? (["reveal", "terminal"] as const) : []), ...(rec.linkId ? (["link"] as const) : []), "here", "close"];
}
export type RowAction = "rename" | "reveal" | "terminal" | "copy" | "link" | "here" | "close";

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
  link: () => t("tlink.copy"),
  here: () => t("term.here"),
  close: () => t("ss.close"),
};
const ROW_ACTION_ID: Record<RowAction, string> = {
  rename: "session-rename",
  reveal: "session-reveal",
  terminal: "session-system-terminal",
  copy: "session-copy-id",
  link: "session-copy-link",
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

/** The row's compact view mark. The terminal is a solid window with the prompt cut out of it, the chat an outlined
 *  bubble; the original 16 by 13 geometry scales together inside a 12 by 10 box. */
function ViewMark({ view }: { view: "chat" | "terminal" }) {
  return view === "terminal" ? (
    <svg width="12" height="10" viewBox="0 0 16 13" aria-hidden="true">
      <rect width="16" height="13" rx="3" fill="currentColor" />
      <path d="M4 4 6.5 6.5 4 9M8.3 9.2h3.9" fill="none" stroke="var(--ss-cut)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ) : (
    <svg width="12" height="10" viewBox="0 0 16 13" aria-hidden="true">
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

/** A TERMINALS row. Memoised: it re-renders when its own record, unseen mark, selection or the language change, or
 *  when its terminal's output changes what it shows (useTermFace), never for another session's output. `lang` is
 *  only a key: the strings read the current language at render. */
const TermRow = memo(function TermRow({ rec, agents, unseen, active, ticking, onClose, split }: { rec: SessionRec; agents: AgentInfo[] | null; unseen?: Unseen; active: boolean; ticking: boolean; lang: string; onClose: (rec: SessionRec) => void; split?: Layout | null }) {
  countRender(`row:${rec.id}`);
  const [editing, setEditing] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const live = rec.status === "running" || rec.status === "starting";
  const { act, now } = useTermFace(rec.id, rec.startedAt, ticking);
  const title = pickTitle(rec, termFallbackName(rec, agents));
  // a program reporting progress (OSC 9;4) is working for as long as it says so, printing or not
  const status = termStatus({ status: rec.status, exitCode: rec.exitCode, lastOut: act.progress ? now : act.lastOut }, unseen, now);
  // the folder its shell reports now (OSC 7), when that is not the folder it started in (its group's header)
  const movedTo = act.cwd && act.cwd !== rec.cwd ? act.cwd : null;
  const markAgent = termMarkAgent(rec);
  const age = ageMs(act.lastOut ?? rec.startedAt, now);
  const activity = termActivity({ agent: rec.agent, fgAgent: rec.fgAgent, lastLine: act.lastLine, oscTitle: act.oscTitle });
  // a CLI runs in it: the card's thin amber lane on its left edge (the folder summary's "running" counts the same)
  const running = live && markAgent !== null;
  const actions = termMenuItems(rec);
  const pick = (a: RowAction) => {
    const sx = getSessions();
    if (a === "rename") setEditing(true);
    else if (a === "reveal") void sx.revealFolder(rec.id);
    else if (a === "terminal") void sx.openTerminal(rec.id);
    else if (a === "link") void sx.copyLink(rec.id);
    else if (a === "here") sx.startTerminal(rec.agent, rec.cwd);
    else if (a === "close") onClose(rec);
  };
  const endEdit = (name: string | null | undefined) => {
    setEditing(false);
    if (name !== undefined) getSessions().rename(rec.id, name);
    requestAnimationFrame(() => wrap.current?.querySelector<HTMLElement>(".ss-open")?.focus());
  };
  const body = (
    <>
      <TermStatusGlyph status={status} />
      {/* live: a CLI runs in it (its own, or one the shell reports in front): the amber frame; a bare shell prompt and
          an ended session keep the plain frame */}
      <TermRowMark agent={markAgent} live={live && markAgent !== null} size={16} />
      {editing ? (
        <NameInput initial={title.title} auto={title.source !== "person"} onDone={endEdit} />
      ) : (
        <span
          className={`tr-n${split ? " has-split" : ""}`}
          data-testid="session-name"
          data-source={title.source}
          title={title.title}
          onDoubleClick={(e) => {
            e.preventDefault();
            setEditing(true);
          }}
        >
          {split ? <span className="tr-nt">{title.title}</span> : title.title}
          {split && (
            <span className="tr-split" data-testid="term-split-glyph" role="img" aria-label={t(active ? "split.focusedPane" : "split.inSplit")} title={t(active ? "split.focusedPane" : "split.inSplit")}>
              <SplitGlyph layout={split} mine={paneOf(rec.id) ?? -1} size={11} />
            </span>
          )}
        </span>
      )}
      <span className="tr-age" data-testid="term-age">
        {age}
      </span>
      {/* line 2, muted: the CLI, then what it last printed (else the title it set) */}
      <span className="tr-sub" data-testid="term-meta" title={activity.line || undefined}>
        <span className="tr-cli">{activity.cli}</span>
        {movedTo && (
          <>
            <span className="tr-dot" aria-hidden="true">
              ·
            </span>
            <span className="tr-cwd" data-testid="term-cwd" title={movedTo}>
              {folderName(movedTo)}
            </span>
          </>
        )}
        {activity.line && (
          <>
            <span className="tr-dot" aria-hidden="true">
              ·
            </span>
            <span className="tr-line" data-testid="term-line">
              {activity.line}
            </span>
          </>
        )}
      </span>
    </>
  );
  return (
    <div
      ref={wrap}
      className={`ss-row tr${active ? " active" : ""}${running ? " run" : ""}${menu ? " menu-open" : ""}${split ? (active ? " split-focus" : " split") : ""}`}
      data-split={split ? (active ? "focused" : "in") : undefined}
      data-testid={`session-${rec.id}`}
      data-status={rec.status}
      data-term-status={status ?? "idle"}
      data-fg={rec.fgAgent ?? undefined}
      onContextMenu={(e) => {
        if (editing) return;
        e.preventDefault();
        const side = wrap.current?.closest(".side")?.getBoundingClientRect();
        const right = (side?.right ?? window.innerWidth) - 6;
        const h = menuHeight(actions.length);
        setMenu({ x: Math.max(6, Math.min(e.clientX, right - MENU_W_PX)), y: Math.max(6, Math.min(e.clientY, window.innerHeight - h - 6)) });
      }}
    >
      {editing ? (
        <div className="ss-open ss-editing" title={rec.cwd}>
          {body}
        </div>
      ) : (
        <button type="button" className="ss-open" onClick={() => getStore().actions.openSession(rec.id)} aria-current={active ? "true" : undefined} title={`${title.title}\n${act.cwd ?? rec.cwd}`}>
          {body}
        </button>
      )}
      {!editing && (
        <button type="button" className="ss-x" aria-label={t("ss.close")} title={t("ss.close")} onClick={() => onClose(rec)} data-testid="session-close">
          <CloseIcon />
        </button>
      )}
      {menu && <SessionMenu at={menu} name={title.title} actions={actions} onPick={pick} onDismiss={() => setMenu(null)} />}
    </div>
  );
});
