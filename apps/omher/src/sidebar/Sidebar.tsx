import { useState } from "react";
import "./sidebar.css";
import logo from "../assets/omher-mark.png";
import { useStore } from "../state/store";
import { slots } from "../features";
import { CalendarIcon, GearIcon, GridIcon, IconButton, PlusIcon, SearchIcon } from "../ui";
import { BotRow } from "./BotRow";
import { Usage } from "./Usage";

export function Sidebar() {
  const s = useStore();
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const AddBot = slots.addBot;
  const needle = q.trim().toLowerCase();
  const bots = needle
    ? s.bots.filter((b) => b.display_name.toLowerCase().includes(needle) || b.name.toLowerCase().includes(needle))
    : s.bots;
  const inSettings = s.ui.view === "settings";

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
      <div className="side-sh">Bots</div>
      <nav className="bot-list" aria-label="Bots">
        {bots.map((b) => (
          <BotRow
            key={b.name}
            bot={b}
            chat={s.chats[b.name]}
            unread={s.unread[b.name] ?? 0}
            active={!inSettings && s.selectedBot === b.name}
            onSelect={() => void s.selectBot(b.name)}
          />
        ))}
        {needle && bots.length === 0 && <div className="bot-empty">No bot named “{q.trim()}”</div>}
      </nav>
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
        <Usage />
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
