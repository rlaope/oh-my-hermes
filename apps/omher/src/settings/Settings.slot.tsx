// Settings view (main column while `ui.view === "settings"`). Left list: Bots (one page per bot: Profile,
// Model, Work) and App (General, Providers, Computer). Pages are `bot:<name>` and the App page names; the
// page lives in the store (`ui.settingsPage`) so the model popover can deep-link to a bot.
import { useEffect, useState } from "react";
import "./settings.css";
import type { SlotProps } from "../features";
import type { Bot, ModelOptions } from "../lib/protocol";
import { notifyEnabled, setNotifyEnabled, useStore } from "../state/store";
import { Avatar, GridIcon, SourceIcon } from "../ui";
import { Seg } from "../chat/model/Seg";
import { reasoningLabel } from "../chat/model/levels";
import { Appearance } from "./Appearance";
import { AvatarEditor, BotFacts, NameEditor, PictureActions, placeName, useBotInfo, usePictureEditor } from "./BotIdentity";

export const slot = "settings";

const APP_PAGES = [
  { id: "general", label: "General" },
  { id: "providers", label: "Providers" },
  { id: "computer", label: "Computer" },
];

const STATUS: Record<string, string> = { online: "Connected", offline: "Not connected", starting: "Starting…" };

export default function Settings({ page }: SlotProps["settings"]) {
  const s = useStore();
  const botName = page.startsWith("bot:") ? page.slice(4) : null;
  const bot = botName ? s.bots.find((b) => b.name === botName) : undefined;
  const current = bot
    ? `bot:${bot.name}`
    : page === "bots" || APP_PAGES.some((p) => p.id === page)
      ? page
      : "general";

  return (
    <div className="st" data-testid="settings-view">
      <nav className="st-nav" aria-label="Settings sections">
        <div className="st-sh">Bots</div>
        <NavItem id="bots" current={current} onPick={s.openSettings}>
          <span className="st-nav-i" aria-hidden="true">
            <GridIcon />
          </span>
          All bots<span className="st-count">{s.bots.length}</span>
        </NavItem>
        {s.bots.map((b) => (
          <NavItem key={b.name} id={`bot:${b.name}`} current={current} onPick={s.openSettings}>
            <Avatar bot={b.name} size={18} />
            <span className="st-nav-n">{b.display_name}</span>
          </NavItem>
        ))}
        <div className="st-sh st-sh2">App</div>
        {APP_PAGES.map((p) => (
          <NavItem key={p.id} id={p.id} current={current} onPick={s.openSettings}>
            {p.label}
          </NavItem>
        ))}
      </nav>
      <div className="st-body" data-testid={`settings-page-${current.replace(":", "-")}`}>
        {bot ? (
          <BotPage bot={bot} />
        ) : current === "bots" ? (
          <BotsPage />
        ) : current === "providers" ? (
          <ProvidersPage />
        ) : current === "computer" ? (
          <ComputerPage />
        ) : (
          <GeneralPage />
        )}
      </div>
    </div>
  );
}

function NavItem({
  id,
  current,
  onPick,
  children,
}: {
  id: string;
  current: string;
  onPick: (id: string) => void;
  children: React.ReactNode;
}) {
  const on = id === current;
  return (
    <button
      type="button"
      className={on ? "on" : undefined}
      aria-current={on ? "page" : undefined}
      onClick={() => onPick(id)}
      data-testid={`settings-nav-${id.replace(":", "-")}`}
    >
      {children}
    </button>
  );
}

function Row({ title, hint, children }: { title: string; hint?: string; children?: React.ReactNode }) {
  return (
    <div className="st-row">
      <div className="st-k">
        <b>{title}</b>
        {hint && <span>{hint}</span>}
      </div>
      {children !== undefined && <div className="st-v">{children}</div>}
    </div>
  );
}

const Value = ({ children, mono }: { children: React.ReactNode; mono?: boolean }) => (
  <span className={`st-val${mono ? " mono" : ""}`}>{children}</span>
);

function providerName(opts: ModelOptions | undefined, slug: string): string {
  return opts?.providers.find((p) => p.slug === slug)?.name ?? slug;
}

function BotPage({ bot }: { bot: Bot }) {
  const s = useStore();
  const chat = s.chats[bot.name];
  const opts = s.models[bot.name];
  const routines = s.routines[bot.name];
  const model = chat?.model || opts?.current.model || bot.model;
  const provider = chat?.provider || opts?.current.provider || bot.provider;
  const reasoning = chat?.reasoning || opts?.current.reasoning || "";
  const offline = bot.status === "offline";
  const info = useBotInfo(bot);
  const picture = usePictureEditor(bot);
  const live = (bot.running || !!chat?.turn) && !offline;

  useEffect(() => {
    if (offline) return;
    if (!s.models[bot.name]) void s.loadModels(bot.name);
    if (!s.routines[bot.name]) void s.loadRoutines(bot.name);
    // fetch once per bot page
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bot.name, offline]);

  return (
    <div className="st-page">
      <div className="be-head" data-testid="bot-head">
        <AvatarEditor bot={bot} ed={picture} />
        <div className="be-id">
          <NameEditor bot={bot} />
          <span className="be-sub">
            <i className={`st-dot ${live ? "working" : bot.status}`} aria-hidden="true" />
            {live ? "Working" : STATUS[bot.status] ?? bot.status}
          </span>
          {bot.description && <p className="be-desc">{bot.description}</p>}
          <div className="be-acts">
            <button type="button" className="st-btn" onClick={() => void s.selectBot(bot.name)} data-testid="bot-open-chat">
              Open chat
            </button>
            <PictureActions ed={picture} />
          </div>
        </div>
      </div>
      <BotFacts info={info} />

      <div className="st-gh">Profile</div>
      <div className="st-grp">
        <Row
          title="Profile id"
          hint={bot.is_default ? "The default Hermes profile. Name and picture are saved here" : "Name and picture are saved in this Hermes profile"}
        >
          <Value mono>{bot.name}</Value>
        </Row>
      </div>

      <div className="st-gh">Model</div>
      <div className="st-grp">
        <Row title="Model" hint="Used by this bot’s main chat">
          <Value>
            {model || "—"}
            {provider && <small>{providerName(opts, provider)}</small>}
          </Value>
        </Row>
        <Row title="Reasoning" hint="How long it thinks before answering">
          <Value>{reasoning ? reasoningLabel(reasoning) : "—"}</Value>
        </Row>
        <Row title="Change" hint="Pick a model and reasoning from the pill in the chat header">
          <button type="button" className="st-btn" onClick={() => void s.selectBot(bot.name)} disabled={offline}>
            Change in chat
          </button>
        </Row>
      </div>

      <div className="st-gh">Work</div>
      <div className="st-grp">
        <Row title="Main chat" hint="One chat per bot; other places stay read-only here">
          <Value>{chat?.loaded ? `${chat.messages.length} messages` : "—"}</Value>
        </Row>
        <Row title="Routines" hint="Scheduled jobs from this profile">
          <Value>
            {(() => {
              const n = routines?.length ?? info?.routines;
              return n === undefined ? "—" : `${n} ${n === 1 ? "routine" : "routines"}`;
            })()}
          </Value>
        </Row>
        <Row title="Ask before" hint="Approvals follow this profile’s Hermes settings">
          <Value>Set in Hermes</Value>
        </Row>
        <Row title="Use this computer" hint="Click and type in your apps">
          <Value>
            <span className="st-soon">Soon</span>
          </Value>
        </Row>
      </div>
    </div>
  );
}

/** Every bot at a glance: picture, name, status, what it is doing and where it works. */
function BotsPage() {
  const s = useStore();
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const bots = needle
    ? s.bots.filter((b) =>
        [b.display_name, b.name, b.description, b.model].some((t) => (t ?? "").toLowerCase().includes(needle)),
      )
    : s.bots;
  const online = s.bots.filter((b) => b.status === "online").length;
  const working = s.bots.filter((b) => b.running || !!s.chats[b.name]?.turn).length;
  return (
    <div className="st-page st-wide">
      <div className="bots-h">
        <div>
          <b>Bots</b>
          <span>
            {s.bots.length} {s.bots.length === 1 ? "bot" : "bots"} · {online} connected
            {working > 0 && ` · ${working} working`}
          </span>
        </div>
        <input
          type="search"
          className="bots-q"
          placeholder="Find a bot"
          aria-label="Find a bot"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          data-testid="bots-search"
        />
      </div>
      <div className="bots-grid" data-testid="bots-grid">
        {bots.map((b) => (
          <BotCard key={b.name} bot={b} />
        ))}
        {needle && bots.length === 0 && <div className="bots-empty">No bot matches “{q.trim()}”</div>}
      </div>
    </div>
  );
}

function BotCard({ bot }: { bot: Bot }) {
  const s = useStore();
  const info = useBotInfo(bot);
  const places = info ? Object.entries(info.places).slice(0, 3) : [];
  const live = bot.running || !!s.chats[bot.name]?.turn;
  return (
    <button
      type="button"
      className="bot-card"
      onClick={() => s.openSettings(`bot:${bot.name}`)}
      data-testid={`bot-card-${bot.name}`}
    >
      <span className="bc-top">
        <Avatar bot={bot.name} size={40} />
        <span className="bc-id">
          <b>{bot.display_name}</b>
          <span>
            <i className={`st-dot ${live ? "working" : bot.status}`} aria-hidden="true" />
            {live ? "Working" : STATUS[bot.status] ?? bot.status}
            {bot.name !== bot.display_name.toLowerCase() && <code>{bot.name}</code>}
          </span>
        </span>
      </span>
      {bot.description && <span className="bc-desc">{bot.description}</span>}
      <span className="bc-foot">
        <span className="bc-model">{bot.model || "—"}</span>
        {places.map(([src, n]) => (
          <span key={src} className="bc-place" title={`${n} ${placeName(src)} sessions`}>
            <SourceIcon source={src} size={11} />
            {n}
          </span>
        ))}
      </span>
    </button>
  );
}

const MOD = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl+";
const SHORTCUTS: [string, string][] = [
  [`${MOD}1 … ${MOD}9`, "Open bot 1 to 9"],
  [`${MOD}K`, "Search bots"],
  [`${MOD}.`, "Show or hide Details"],
  [`${MOD},`, "Settings"],
  ["Esc", "Stop the running answer"],
];

function NotifySeg() {
  const [on, setOn] = useState(notifyEnabled());
  return (
    <Seg
      small
      label="Notify me"
      value={on ? "on" : "off"}
      options={[
        { value: "on", label: "On" },
        { value: "off", label: "Off" },
      ]}
      onChange={(v) => {
        setNotifyEnabled(v === "on");
        setOn(v === "on");
      }}
      testId="notify-seg"
    />
  );
}

function GeneralPage() {
  const s = useStore();
  const h = s.hello;
  return (
    <div className="st-page">
      <div className="st-gh st-gh0">Appearance</div>
      <Appearance />
      <div className="st-gh">Notifications</div>
      <div className="st-grp">
        <Row title="Notify me" hint="When a bot answers, needs an approval or asks you something while omher is in the background">
          <NotifySeg />
        </Row>
      </div>
      <div className="st-gh">Keyboard</div>
      <div className="st-grp" data-testid="shortcuts">
        {SHORTCUTS.map(([keys, what]) => (
          <Row key={keys} title={what}>
            <Value>
              <kbd className="st-kbd">{keys}</kbd>
            </Value>
          </Row>
        ))}
      </div>
      <div className="st-gh">Hermes</div>
      <div className="st-grp">
        <Row title="Hermes home">
          <Value mono>{h?.hermes.home ?? "—"}</Value>
        </Row>
        <Row title="Hermes version">
          <Value>{h?.hermes.version ?? "—"}</Value>
        </Row>
        <Row title="Connection" hint={h?.bridge === "mock" ? "Test bridge (no Hermes)" : undefined}>
          <Value>
            <i className={`st-dot ${s.conn === "open" ? "online" : "offline"}`} aria-hidden="true" />
            {s.conn === "open" ? "Connected" : s.conn === "connecting" ? "Connecting…" : "Not connected"}
          </Value>
        </Row>
      </div>
    </div>
  );
}

function ProvidersPage() {
  const s = useStore();
  const name = s.selectedBot ?? s.bots[0]?.name ?? null;
  const opts = name ? s.models[name] : undefined;
  const bot = s.bots.find((b) => b.name === name);
  useEffect(() => {
    if (name && !opts && bot?.status !== "offline") void s.loadModels(name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);
  return (
    <div className="st-page">
      <div className="st-gh st-gh0">Providers</div>
      <p className="st-note">Read-only. Providers and keys are set up in Hermes.</p>
      <div className="st-grp" data-testid="providers-list">
        {!opts ? (
          <Row title={bot?.status === "offline" ? "Not connected" : "Loading…"} />
        ) : (
          opts.providers.map((p) => (
            <Row key={p.slug} title={p.name} hint={p.models.join(" · ") || "No models"}>
              <Value mono>
                {p.slug}
                {p.slug === opts.current.provider && <small className="st-tag">in use</small>}
              </Value>
            </Row>
          ))
        )}
      </div>
    </div>
  );
}

function ComputerPage() {
  return (
    <div className="st-page">
      <div className="st-gh st-gh0">Computer</div>
      <div className="st-grp">
        <Row title="Use this computer" hint="Let a bot click and type in your apps">
          <Value>
            <span className="st-soon">Soon</span>
          </Value>
        </Row>
      </div>
    </div>
  );
}
