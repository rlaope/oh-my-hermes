// Settings view (main column while `ui.view === "settings"`). Left list: Bots (one page per bot: Profile,
// Model, Work) and App (General, Providers, Computer). Pages are `bot:<name>` and the App page names; the
// page lives in the store (`ui.settingsPage`) so the model popover can deep-link to a bot.
import { useEffect } from "react";
import "./settings.css";
import type { SlotProps } from "../features";
import type { Bot, ModelOptions } from "../lib/protocol";
import { useStore, type Theme } from "../state/store";
import { Avatar } from "../ui";
import { Seg } from "../chat/model/Seg";
import { reasoningLabel } from "../chat/model/levels";

export const slot = "settings";

const APP_PAGES = [
  { id: "general", label: "General" },
  { id: "providers", label: "Providers" },
  { id: "computer", label: "Computer" },
];

const THEMES: { value: Theme; label: string }[] = [
  { value: "system", label: "System" },
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
];

const STATUS: Record<string, string> = { online: "Connected", offline: "Not connected", starting: "Starting…" };

export default function Settings({ page }: SlotProps["settings"]) {
  const s = useStore();
  const botName = page.startsWith("bot:") ? page.slice(4) : null;
  const bot = botName ? s.bots.find((b) => b.name === botName) : undefined;
  const current = bot ? `bot:${bot.name}` : APP_PAGES.some((p) => p.id === page) ? page : "general";

  return (
    <div className="st" data-testid="settings-view">
      <nav className="st-nav" aria-label="Settings sections">
        <div className="st-sh">Bots</div>
        {s.bots.map((b) => (
          <NavItem key={b.name} id={`bot:${b.name}`} current={current} onPick={s.openSettings}>
            {b.display_name}
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

  useEffect(() => {
    if (offline) return;
    if (!s.models[bot.name]) void s.loadModels(bot.name);
    if (!s.routines[bot.name]) void s.loadRoutines(bot.name);
    // fetch once per bot page
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bot.name, offline]);

  return (
    <div className="st-page">
      <div className="st-title">
        <Avatar bot={bot.name} size={36} />
        <div>
          <b>{bot.display_name}</b>
          <span>Engine: Hermes Agent · profile “{bot.name}”</span>
        </div>
      </div>

      <div className="st-gh st-gh0">Profile</div>
      <div className="st-grp">
        <Row title="Name">
          <Value>{bot.display_name}</Value>
        </Row>
        <Row title="Hermes profile" hint={bot.is_default ? "The default profile" : undefined}>
          <Value mono>{bot.name}</Value>
        </Row>
        {bot.description && (
          <Row title="Description">
            <Value>{bot.description}</Value>
          </Row>
        )}
        <Row title="Status">
          <Value>
            <i className={`st-dot ${bot.status}`} aria-hidden="true" />
            {STATUS[bot.status] ?? bot.status}
            {bot.running && !offline ? " · working" : ""}
          </Value>
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
            Open chat
          </button>
        </Row>
      </div>

      <div className="st-gh">Work</div>
      <div className="st-grp">
        <Row title="Main chat" hint="One chat per bot; other places stay read-only here">
          <Value>{chat?.loaded ? `${chat.messages.length} messages` : "—"}</Value>
        </Row>
        <Row title="Routines" hint="Scheduled jobs from this profile">
          <Value>{routines ? `${routines.length} ${routines.length === 1 ? "routine" : "routines"}` : "—"}</Value>
        </Row>
        <Row title="Ask before" hint="Approvals follow this profile’s Hermes settings">
          <Value>Set in Hermes</Value>
        </Row>
        <Row title="Use this Mac" hint="Click and type in your apps">
          <Value>Not in this version</Value>
        </Row>
      </div>
    </div>
  );
}

function GeneralPage() {
  const s = useStore();
  const h = s.hello;
  return (
    <div className="st-page">
      <div className="st-gh st-gh0">Appearance</div>
      <div className="st-grp">
        <Row title="Theme" hint="System follows your Mac">
          <Seg
            small
            label="Theme"
            value={s.ui.theme}
            options={THEMES}
            onChange={(t) => s.setTheme(t as Theme)}
            testId="theme-seg"
          />
        </Row>
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
        <Row title="Use this Mac" hint="Let a bot click and type in your apps">
          <Value>Not in this version</Value>
        </Row>
      </div>
    </div>
  );
}
