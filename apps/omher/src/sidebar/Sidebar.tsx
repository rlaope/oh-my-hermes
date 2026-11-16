import { useCallback, useEffect, useRef, useState } from "react";
import { getRestarts } from "./restart";
import "./sidebar.css";
import logo from "../assets/omher-mark.png";
import { selectAsks, selectSidebarBots, useStore } from "../state/store";
import { slots } from "../features";
import { CalendarIcon, GearIcon, GridIcon, IconButton, PlusIcon, SearchIcon } from "../ui";
import { BotRow, threadsLatest } from "./BotRow";
import { threadKey } from "../threads/types";
import { useRowDrag } from "./useRowDrag";
import { AttachCard } from "../peers/AttachCard";
import { Usage } from "./Usage";
import { AccountsWatcher } from "../settings/accounts/useAccounts";
import "../sessions/sessions.css";
import { SessionList, SessionsHeader } from "../sessions/SessionsSection";
import { SessionBackgroundMenu } from "../sessions/SessionBackgroundMenu";
import { SESSIONS_ENTRY } from "../sessions/entry";
import { NeedsStrip } from "./Needs";
import { UpdateButton } from "./UpdateButton";
import { FirstRunHint } from "../onboarding/FirstRun";
import { OmhNotice } from "./OmhNotice";
import { t } from "../i18n";
import { ThreadTree } from "../threads/ThreadTree";
import { Dock } from "./Dock";
import { useBotsAbove } from "./dockState";
import { revealBotTop, revealPending } from "./revealBot";
import { useEdgeFade } from "./edgeFade";
import { SplitDivider, useSideSplit } from "./SideSplit";
import { useAutoSplit } from "./autoSplit";

const sessionBackground = (target: EventTarget) => target instanceof Element && !target.closest(".ss-row, button, input, textarea, select, a, [contenteditable], [role=menu], [role=menuitem]");

/** The open bot or thread row scrolls into view inside BOTS (never moving TERMINALS). */
function useRevealBot(bot: string | null, thread: string | null, inChat: boolean) {
  useEffect(() => {
    if (!inChat || !bot) return;
    // a bot clicked in the sidebar or the dock rises to the top on its own (revealBot): no nearest-scroll under it
    if (!thread && revealPending(bot)) return;
    const sel = thread ? `[data-testid="thread-row-${CSS.escape(thread)}"]` : `[data-testid="bot-${CSS.escape(bot)}"]`;
    document.querySelector(sel)?.scrollIntoView({ block: "nearest" });
  }, [bot, thread, inChat]);
}

export function Sidebar() {
  const s = useStore();
  const [q, setQ] = useState("");
  const [sessionMenu, setSessionMenu] = useState<{ x: number; y: number; focus: HTMLElement } | null>(null);
  const closeSessionMenu = useCallback(() => setSessionMenu(null), []);
  const [adding, setAdding] = useState(false);
  const [ssh, setSsh] = useState(false);
  const AddBot = slots.addBot;
  const needle = q.trim().toLowerCase();
  const listed = selectSidebarBots(s);
  const bots = needle
    ? listed.filter((b) => b.display_name.toLowerCase().includes(needle) || b.name.toLowerCase().includes(needle))
    : listed;
  const asks = selectAsks(s);
  // hold a row to drag it; off while searching, where a row's place in the filtered list is not its sidebar place
  const drag = useRowDrag(
    listed.map((b) => b.name),
    s.ui.pinned,
    !needle,
    (bot, to) => s.moveBot(bot, to),
  );
  const inSettings = s.ui.view === "settings";
  const automations = s.automations?.length ?? 0;
  const inChat = s.ui.view === "chat";
  useRevealBot(s.selectedBot, s.ui.thread, inChat);
  const botList = useRef<HTMLElement>(null);
  const botNav = useEdgeFade<HTMLElement>(botList);
  // the dock: the bots scrolled out of view at the top of BOTS (none at the top: no dock)
  const above = useBotsAbove(botList);
  // BOTS | TERMINALS: auto (each takes what its rows need and they share the rest) or the share the person dragged
  const botSec = useRef<HTMLElement>(null);
  const termSec = useRef<HTMLElement>(null);
  const split = useSideSplit(botSec, termSec);
  // auto (nothing dragged, no search): each region as tall as its rows, or cut on a whole row (autoSplit.ts)
  useAutoSplit(botSec, termSec, SESSIONS_ENTRY && !needle && split.share === null);

  return (
    <aside className="side" data-testid="sidebar">
      <div className="side-top">
        <div className="brand">
          <img src={logo} alt="" />
          <b>omher</b>
        </div>
        <div className="side-add">
          <OmhNotice />
          <IconButton label={t("nav.addBot")} onClick={() => AddBot && setAdding((v) => !v)} aria-expanded={adding} disabled={!AddBot}>
            <PlusIcon />
          </IconButton>
          {AddBot && adding && <AddBot onClose={() => setAdding(false)} onSsh={() => setSsh(true)} />}
          {ssh && <AttachCard seed={{}} onClose={() => setSsh(false)} />}
        </div>
      </div>
      <label className="search">
        <SearchIcon />
        <input
          type="search"
          placeholder={t("nav.search")}
          aria-label={t("nav.searchBots")}
          data-testid="bot-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && setQ("")}
        />
      </label>
      <NeedsStrip asks={asks} />
      <section ref={botSec} className={`side-sec${needle && bots.length === 0 ? " side-sec-fit" : ""}`} data-testid="side-bots" style={needle ? undefined : split.bots}>
        <div className="side-sh">{t("nav.bots")}</div>
        <nav ref={botNav} className="bot-list" aria-label={t("nav.bots")} role="tree">
          {bots.map((b) => {
            const pinned = s.ui.pinned.includes(b.name);
            const hasThreads = (s.threads[b.name]?.length ?? 0) > 0;
            const groupId = `threads-of-${b.name.replace(/[^A-Za-z0-9_-]/g, "_")}`;
            return (
            <BotRow
              key={b.name}
              bot={b}
              chat={s.chats[b.name]}
              unread={s.unread[b.name] ?? 0}
              active={inChat && s.selectedBot === b.name && !s.ui.thread}
              asks={asks.filter((a) => a.bot === b.name)}
              pinned={pinned}
              onSelect={() => {
                revealBotTop(b.name);
                void s.selectBot(b.name);
              }}
              drag={drag.row(b.name)}
              groupId={hasThreads ? groupId : undefined}
              latest={hasThreads ? threadsLatest(s.threads[b.name]!, (th) => s.chats[threadKey(b.name, th)]) : null}
              menu={{
                onNewThread: b.host || b.status === "offline" ? undefined : () => void s.newThread(b.name),
                pinned,
                onPin: () => s.pinBot(b.name, !pinned),
                onEdit: () => s.openSettings(`bot:${b.name}`),
                onRestart: () => void getRestarts().press(b.name),
                offline: b.status === "offline",
                onRemove: listed.length > 1 ? () => s.listBot(b.name, false) : undefined,
              }}
            >
              {hasThreads && <ThreadTree bot={b.name} id={groupId} />}
            </BotRow>
            );
          })}
          {needle && bots.length === 0 && <div className="bot-empty">{t("side.noBot", { q: q.trim() })}</div>}
          {!needle && listed.length === 0 && <FirstRunHint text={t("onb.botsHint")} testId="onb-hint-bots" />}
        </nav>
      </section>
      {SESSIONS_ENTRY && <SplitDivider share={split.share} onDrag={split.onDrag} onReset={split.reset} onKey={split.onKey} />}
      {SESSIONS_ENTRY && (
      <section
        ref={termSec}
        className="side-sec"
        data-testid="side-sessions"
        style={needle ? undefined : split.terms}
        tabIndex={-1}
        onPointerDown={(e) => {
          // Keep the previous focus available for Escape, before the right press can blur it.
          if (e.button === 2 && sessionBackground(e.target)) e.preventDefault();
        }}
        onContextMenu={(e) => {
          // Rows own their menu; controls and text fields keep their native context menu.
          if (!sessionBackground(e.target)) return;
          e.preventDefault();
          const focus = document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : e.currentTarget;
          const box = e.currentTarget.getBoundingClientRect();
          setSessionMenu({ x: e.clientX || box.left + 8, y: e.clientY || box.top + 8, focus });
        }}
      >
        <SessionsHeader />
        <SessionList needle={needle} query={q.trim()} />
        {sessionMenu && <SessionBackgroundMenu at={sessionMenu} onClose={closeSessionMenu} />}
      </section>
      )}
      <Dock above={needle ? [] : above} />
      <div className="side-foot">
        {/* one compact row: Automations, Plugins and Settings as icon buttons (their names in the tooltip and to a
            screen reader), the usage marks after them */}
        <div className="foot-row" data-testid="foot-row">
          <button
            type="button"
            className={`nav nav-i${s.ui.view === "automations" ? " on" : ""}`}
            aria-current={s.ui.view === "automations" ? "page" : undefined}
            title={automations > 0 ? `${t("nav.automations")} · ${automations}` : t("nav.automations")}
            onClick={() => s.openAutomations()}
            data-testid="nav-automations"
          >
            <CalendarIcon />
            <span className="vh">{t("nav.automations")}</span>
            {automations > 0 && <span className="nav-count">{automations}</span>}
          </button>
          <button
            type="button"
            className={`nav nav-i${s.ui.view === "plugins" ? " on" : ""}`}
            aria-current={s.ui.view === "plugins" ? "page" : undefined}
            title={t("nav.plugins")}
            onClick={() => s.openPlugins()}
            data-testid="nav-plugins"
          >
            <GridIcon />
            <span className="vh">{t("nav.plugins")}</span>
          </button>
          <button
            type="button"
            className={`nav nav-i${inSettings && s.ui.settingsPage !== "accounts" ? " on" : ""}`}
            title={t("nav.settings")}
            onClick={() => (inSettings ? s.closeSettings() : s.openSettings())}
            data-testid="nav-settings"
          >
            <GearIcon />
            <span className="vh">{t("nav.settings")}</span>
          </button>
          <Usage />
        </div>
        <AccountsWatcher />
        <div className={`me${inSettings && s.ui.settingsPage === "accounts" ? " on" : ""}`} data-testid="me">
          <button type="button" className="me-btn" onClick={() => s.openSettings("accounts")} title={t("nav.accounts")}>
            <span className="me-i" aria-hidden="true">
              Y
            </span>
            <span>{t("nav.you")}</span>
          </button>
          <UpdateButton />
        </div>
      </div>
    </aside>
  );
}
