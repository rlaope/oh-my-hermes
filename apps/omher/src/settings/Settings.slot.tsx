// Settings view (main column while `ui.view === "settings"`). Left list: You (Accounts), Bots (one page per bot: Profile,
// Model, Work) and App (General, Providers, Computer). Pages are `bot:<name>` and the App page names; the
// page lives in the store (`ui.settingsPage`) so the model popover can deep-link to a bot.
import { useEffect, useState } from "react";
import "./settings.css";
import type { SlotProps } from "../features";
import type { Bot, ModelOptions } from "../lib/protocol";
import { notifyEnabled, setNotifyEnabled, useStore } from "../state/store";
import { appSounds, setSoundsEnabled, soundsEnabled } from "../lib/sounds";
import { LANG_NAMES, LANGS, t, type Key, type Lang } from "../i18n";
import { Avatar, GridIcon, ModelIcon, SourceIcon } from "../ui";
import { Seg } from "../chat/model/Seg";
import { reasoningLabel } from "../chat/model/levels";
import { Appearance } from "./Appearance";
import { AccountsPage } from "./accounts/AccountsPage";
import { ProvidersPage } from "./providers/ProvidersPage";
import { AvatarEditor, BotFacts, NameEditor, PictureActions, placeName, useBotInfo, usePictureEditor } from "./BotIdentity";

export const slot = "settings";

const APP_PAGES: { id: string; label: Key }[] = [
  { id: "general", label: "set.general" },
  { id: "providers", label: "set.providers" },
  { id: "computer", label: "set.computer" },
];

const STATUS: Record<string, Key> = { online: "bot.online", offline: "bot.offline", starting: "bot.starting" };
/** A bot's status in words; a status omher does not know stays as the bridge wrote it. */
export const statusText = (status: string) => (STATUS[status] ? t(STATUS[status]) : status);

export default function Settings({ page }: SlotProps["settings"]) {
  const s = useStore();
  const botName = page.startsWith("bot:") ? page.slice(4) : null;
  const bot = botName ? s.bots.find((b) => b.name === botName) : undefined;
  const current = bot
    ? `bot:${bot.name}`
    : page === "bots" || page === "accounts" || APP_PAGES.some((p) => p.id === page)
      ? page
      : "general";

  return (
    <div className="st" data-testid="settings-view">
      <nav className="st-nav" aria-label={t("set.sections")}>
        <div className="st-sh">{t("set.you")}</div>
        <NavItem id="accounts" current={current} onPick={s.openSettings}>
          {t("nav.accounts")}
        </NavItem>
        <div className="st-sh st-sh2">{t("set.bots")}</div>
        <NavItem id="bots" current={current} onPick={s.openSettings}>
          <span className="st-nav-i" aria-hidden="true">
            <GridIcon />
          </span>
          {t("set.allBots")}<span className="st-count">{s.bots.length}</span>
        </NavItem>
        {s.bots.map((b) => (
          <NavItem key={b.name} id={`bot:${b.name}`} current={current} onPick={s.openSettings}>
            <Avatar bot={b.name} size={18} />
            <span className="st-nav-n">{b.display_name}</span>
          </NavItem>
        ))}
        <div className="st-sh st-sh2">{t("set.app")}</div>
        {APP_PAGES.map((p) => (
          <NavItem key={p.id} id={p.id} current={current} onPick={s.openSettings}>
            {t(p.label)}
          </NavItem>
        ))}
      </nav>
      <div className="st-body" data-testid={`settings-page-${current.replace(":", "-")}`}>
        {bot ? (
          <BotPage bot={bot} />
        ) : current === "accounts" ? (
          <AccountsPage />
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

function Row({
  title,
  hint,
  icon,
  children,
}: {
  title: string;
  hint?: string;
  icon?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="st-row">
      <div className="st-k">
        <b className={icon ? "st-kt" : undefined}>
          {icon}
          {title}
        </b>
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
            {live ? t("bot.working") : statusText(bot.status)}
          </span>
          {bot.description && <p className="be-desc">{bot.description}</p>}
          <div className="be-acts">
            <button type="button" className="st-btn" onClick={() => void s.selectBot(bot.name)} data-testid="bot-open-chat">
              {t("set.openChat")}
            </button>
            <PictureActions ed={picture} />
          </div>
        </div>
      </div>
      <BotFacts info={info} />

      <div className="st-gh">{t("set.profile")}</div>
      <div className="st-grp">
        <Row title={t("set.profileId")} hint={bot.is_default ? t("set.profileDefault") : t("set.profileHere")}>
          <Value mono>{bot.name}</Value>
        </Row>
      </div>

      <div className="st-gh">{t("set.model")}</div>
      <div className="st-grp">
        <Row title={t("set.model")} hint={t("set.modelHint")}>
          <Value>
            {model || "—"}
            {provider && <small>{providerName(opts, provider)}</small>}
          </Value>
        </Row>
        <Row title={t("set.reasoning")} hint={t("set.reasoningHint")}>
          <Value>{reasoning ? reasoningLabel(reasoning) : "—"}</Value>
        </Row>
        <Row title={t("set.change")} hint={t("set.changeHint")}>
          <button type="button" className="st-btn" onClick={() => void s.selectBot(bot.name)} disabled={offline}>
            {t("set.changeInChat")}
          </button>
        </Row>
      </div>

      <div className="st-gh">{t("set.work")}</div>
      <div className="st-grp">
        <Row title={t("set.mainChat")} hint={t("set.mainChatHint")}>
          <Value>
            {chat?.loaded ? (chat.messages.length === 1 ? t("set.messages1") : t("set.messages", { n: chat.messages.length })) : "—"}
          </Value>
        </Row>
        <Row title={t("set.routines")} hint={t("set.routinesHint")}>
          <Value>
            {(() => {
              const n = routines?.length ?? info?.routines;
              return n === undefined ? "—" : n === 1 ? t("set.routine1") : t("set.routinesN", { n });
            })()}
          </Value>
        </Row>
        <Row title={t("set.askBefore")} hint={t("set.askBeforeHint")}>
          <Value>{t("set.inHermes")}</Value>
        </Row>
        <Row title={t("set.useComputer")} hint={t("set.useComputerHint")}>
          <Value>
            <span className="st-soon">{t("set.soon")}</span>
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
          <b>{t("set.bots")}</b>
          <span>
            {s.bots.length === 1 ? t("set.botsCount1", { online }) : t("set.botsCount", { n: s.bots.length, online })}
            {working > 0 && t("set.botsWorking", { n: working })}
          </span>
        </div>
        <input
          type="search"
          className="bots-q"
          placeholder={t("set.findBot")}
          aria-label={t("set.findBot")}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          data-testid="bots-search"
        />
      </div>
      <div className="bots-grid" data-testid="bots-grid">
        {bots.map((b) => (
          <BotCard key={b.name} bot={b} />
        ))}
        {needle && bots.length === 0 && <div className="bots-empty">{t("set.noBotMatch", { q: q.trim() })}</div>}
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
            {live ? t("bot.working") : statusText(bot.status)}
            {bot.name !== bot.display_name.toLowerCase() && <code>{bot.name}</code>}
          </span>
        </span>
      </span>
      {bot.description && <span className="bc-desc">{bot.description}</span>}
      <span className="bc-foot">
        <span className="bc-model">
          <ModelIcon model={bot.model} provider={bot.provider} size={11} />
          {bot.model || "—"}
        </span>
        {places.map(([src, n]) => (
          <span key={src} className="bc-place" title={t("set.placeSessions", { n, place: placeName(src) })}>
            <SourceIcon source={src} size={11} />
            {n}
          </span>
        ))}
      </span>
    </button>
  );
}

const MOD = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl+";
const SHORTCUTS: [string, Key][] = [
  [`${MOD}1 … ${MOD}9`, "key.openBot"],
  [`${MOD}K`, "key.search"],
  [`${MOD}.`, "key.details"],
  [`${MOD},`, "key.settings"],
  [`${MOD}J`, "key.nextAsk"],
  ["1 · 2 · 3", "key.cardKeys"],
  ["Esc", "key.stop"],
];

function NotifySeg() {
  const [on, setOn] = useState(notifyEnabled());
  return (
    <Seg
      small
      label={t("set.notify")}
      value={on ? "on" : "off"}
      options={[
        { value: "on", label: t("set.on") },
        { value: "off", label: t("set.off") },
      ]}
      onChange={(v) => {
        setNotifyEnabled(v === "on");
        setOn(v === "on");
      }}
      testId="notify-seg"
    />
  );
}

function SoundsSeg() {
  const [on, setOn] = useState(soundsEnabled());
  return (
    <span className="st-pair">
      <button type="button" className="st-btn" disabled={!on} onClick={() => appSounds().preview()} data-testid="sounds-play">
        {t("sounds.play")}
      </button>
      <Seg
        small
        label={t("sounds.title")}
        value={on ? "on" : "off"}
        options={[
          { value: "on", label: t("sounds.on") },
          { value: "off", label: t("sounds.off") },
        ]}
        onChange={(v) => {
          setSoundsEnabled(v === "on");
          setOn(v === "on");
        }}
        testId="sounds-seg"
      />
    </span>
  );
}

function GeneralPage() {
  const s = useStore();
  const h = s.hello;
  return (
    <div className="st-page">
      <div className="st-gh st-gh0">{t("set.appearance")}</div>
      <Appearance />
      <div className="st-grp st-grp-lang">
        <Row title={t("lang.title")} hint={t("lang.hint")}>
          <Seg
            label={t("lang.title")}
            value={s.ui.lang}
            onChange={(v) => s.setLanguage(v as Lang)}
            options={LANGS.map((l) => ({ value: l, label: LANG_NAMES[l] }))}
            testId="language"
          />
        </Row>
      </div>
      <div className="st-gh">{t("set.notifications")}</div>
      <div className="st-grp">
        <Row title={t("set.notify")} hint={t("set.notifyHint")}>
          <NotifySeg />
        </Row>
        <Row title={t("sounds.title")} hint={t("sounds.hint")}>
          <SoundsSeg />
        </Row>
      </div>
      <div className="st-gh">{t("set.keyboard")}</div>
      <div className="st-grp" data-testid="shortcuts">
        {SHORTCUTS.map(([keys, what]) => (
          <Row key={keys} title={t(what)}>
            <Value>
              <kbd className="st-kbd">{keys}</kbd>
            </Value>
          </Row>
        ))}
      </div>
      <div className="st-gh">Hermes</div>
      <div className="st-grp">
        <Row title={t("set.hermesHome")}>
          <Value mono>{h?.hermes.home ?? "—"}</Value>
        </Row>
        <Row title={t("set.hermesVersion")}>
          <Value>{h?.hermes.version ?? "—"}</Value>
        </Row>
        <Row title={t("set.connection")} hint={h?.bridge === "mock" ? t("set.testBridge") : undefined}>
          <Value>
            <i className={`st-dot ${s.conn === "open" ? "online" : "offline"}`} aria-hidden="true" />
            {s.conn === "open" ? t("bot.online") : s.conn === "connecting" ? t("bot.connecting") : t("bot.offline")}
          </Value>
        </Row>
      </div>
    </div>
  );
}

function ComputerPage() {
  return (
    <div className="st-page">
      <div className="st-gh st-gh0">{t("set.computer")}</div>
      <div className="st-grp">
        <Row title={t("set.useComputer")} hint={t("set.useComputerHint2")}>
          <Value>
            <span className="st-soon">{t("set.soon")}</span>
          </Value>
        </Row>
      </div>
    </div>
  );
}
