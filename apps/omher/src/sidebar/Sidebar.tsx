import { useCallback, useState } from "react";
import "./sidebar.css";
import logo from "../assets/omher-mark.png";
import { selectAsks, selectSidebarBots, useStore } from "../state/store";
import { slots } from "../features";
import { CalendarIcon, GearIcon, GridIcon, IconButton, PlusIcon, SearchIcon } from "../ui";
import { BotRow } from "./BotRow";
import { Usage } from "./Usage";
import { AccountsWatcher } from "../settings/accounts/useAccounts";
import "../sessions/sessions.css";
import { SessionList, SessionsHeader } from "../sessions/SessionsSection";
import { HiddenList, NeedsStrip } from "./Needs";
import { UpdateButton } from "./UpdateButton";
import { FirstRunHint } from "../onboarding/FirstRun";
import { t } from "../i18n";

export function Sidebar() {
  const s = useStore();
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  const closeHidden = useCallback(() => setShowHidden(false), []);
  const AddBot = slots.addBot;
  const needle = q.trim().toLowerCase();
  const listed = selectSidebarBots(s);
  const bots = needle
    ? listed.filter((b) => b.display_name.toLowerCase().includes(needle) || b.name.toLowerCase().includes(needle))
    : listed;
  const asks = selectAsks(s);
  const hiddenCount = s.ui.hidden.filter((n) => s.bots.some((b) => b.name === n)).length;
  const inSettings = s.ui.view === "settings";
  const automations = s.automations?.length ?? 0;
  const inChat = s.ui.view === "chat";

  return (
    <aside className="side" data-testid="sidebar">
      <div className="side-top">
        <div className="brand">
          <img src={logo} alt="" />
          <b>omher</b>
        </div>
        <div className="side-add">
          <IconButton label={t("nav.addBot")} onClick={() => AddBot && setAdding((v) => !v)} aria-expanded={adding} disabled={!AddBot}>
            <PlusIcon />
          </IconButton>
          {AddBot && adding && <AddBot onClose={() => setAdding(false)} />}
        </div>
      </div>
      <label className="search">
        <SearchIcon />
        <input
          type="search"
          placeholder={t("nav.search")}
          aria-label={t("nav.searchBots")}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && setQ("")}
        />
      </label>
      <NeedsStrip asks={asks} />
      <section className="side-sec" data-testid="side-bots">
        <div className="side-sh">{t("nav.bots")}</div>
        <nav className="bot-list" aria-label={t("nav.bots")}>
          {bots.map((b) => {
            const pinned = s.ui.pinned.includes(b.name);
            return (
            <BotRow
              key={b.name}
              bot={b}
              chat={s.chats[b.name]}
              unread={s.unread[b.name] ?? 0}
              active={inChat && s.selectedBot === b.name}
              asks={asks.filter((a) => a.bot === b.name)}
              pinned={pinned}
              onSelect={() => void s.selectBot(b.name)}
              menu={{
                pinned,
                onPin: () => s.pinBot(b.name, !pinned),
                onEdit: () => s.openSettings(`bot:${b.name}`),
                onHide: () => s.hideBot(b.name, true),
                onShowHidden: hiddenCount ? () => setShowHidden(true) : undefined,
              }}
            />
            );
          })}
          {needle && bots.length === 0 && <div className="bot-empty">No bot named “{q.trim()}”</div>}
          {!needle && bots.length === 0 && hiddenCount > 0 && (
            <button type="button" className="bot-empty bot-unhide" onClick={() => setShowHidden(true)}>
              Show hidden bots ({hiddenCount})
            </button>
          )}
          {!needle && listed.length === 0 && <FirstRunHint text={t("onb.botsHint")} testId="onb-hint-bots" />}
          {showHidden && hiddenCount > 0 && <HiddenList onClose={closeHidden} />}
        </nav>
      </section>
      <section className="side-sec" data-testid="side-sessions">
        <SessionsHeader />
        <SessionList />
      </section>
      <div className="side-foot">
        <button
          type="button"
          className={`nav${s.ui.view === "automations" ? " on" : ""}`}
          aria-current={s.ui.view === "automations" ? "page" : undefined}
          onClick={() => s.openAutomations()}
          data-testid="nav-automations"
        >
          <CalendarIcon />
          {t("nav.automations")}
          {automations > 0 && <span className="nav-count">{automations}</span>}
        </button>
        <button
          type="button"
          className={`nav${s.ui.view === "plugins" ? " on" : ""}`}
          aria-current={s.ui.view === "plugins" ? "page" : undefined}
          onClick={() => s.openPlugins()}
          data-testid="nav-plugins"
        >
          <GridIcon />
          {t("nav.plugins")}
        </button>
        <button
          type="button"
          className={`nav${inSettings && s.ui.settingsPage !== "accounts" ? " on" : ""}`}
          onClick={() => (inSettings ? s.closeSettings() : s.openSettings())}
          data-testid="nav-settings"
        >
          <GearIcon />
          {t("nav.settings")}
        </button>
        <Usage />
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
