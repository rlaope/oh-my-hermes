import { useCallback, useState } from "react";
import "./sidebar.css";
import logo from "../assets/omher-mark.png";
import { selectAsks, selectSidebarBots, useStore } from "../state/store";
import { slots } from "../features";
import { CalendarIcon, GearIcon, GridIcon, IconButton, PlusIcon, SearchIcon } from "../ui";
import { BotRow } from "./BotRow";
import "../sessions/sessions.css";
import { SessionList, SessionsHeader } from "../sessions/SessionsSection";
import { HiddenList, NeedsStrip } from "./Needs";

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
  const inChat = s.ui.view === "chat";

  return (
    <aside className="side" data-testid="sidebar">
      <div className="side-top">
        <div className="brand">
          <img src={logo} alt="" />
          <b>omher</b>
        </div>
        <div className="side-add">
          <IconButton label="Add a bot" onClick={() => AddBot && setAdding((v) => !v)} aria-expanded={adding} disabled={!AddBot}>
            <PlusIcon />
          </IconButton>
          {AddBot && adding && <AddBot onClose={() => setAdding(false)} />}
        </div>
      </div>
      <label className="search">
        <SearchIcon />
        <input
          type="search"
          placeholder="Search"
          aria-label="Search bots"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && setQ("")}
        />
      </label>
      <NeedsStrip asks={asks} />
      <section className="side-sec" data-testid="side-bots">
        <div className="side-sh">Bots</div>
        <nav className="bot-list" aria-label="Bots">
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
        {showHidden && hiddenCount > 0 && <HiddenList onClose={closeHidden} />}
      </nav>
      </section>
      <section className="side-sec" data-testid="side-sessions">
        <SessionsHeader />
        <SessionList />
      </section>
      <div className="side-foot">
        <button type="button" className="nav" disabled title="Coming in a later version" data-testid="nav-automations">
          <CalendarIcon />
          Automations<span className="nav-soon">Soon</span>
        </button>
        <button type="button" className="nav" disabled title="Coming in a later version" data-testid="nav-plugins">
          <GridIcon />
          Plugins<span className="nav-soon">Soon</span>
        </button>
        <button
          type="button"
          className={`nav${inSettings ? " on" : ""}`}
          onClick={() => (inSettings ? s.closeSettings() : s.openSettings())}
          data-testid="nav-settings"
        >
          <GearIcon />
          Settings
        </button>
        <div className="me">
          <span className="me-i" aria-hidden="true">
            Y
          </span>
          <span>You</span>
        </div>
      </div>
    </aside>
  );
}
