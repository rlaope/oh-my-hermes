// Settings view (main column while `ui.view === "settings"`). Left list: You (Accounts), Bots (one page per bot: its
// picture and name, Persona, Memory, Automations, Elsewhere, Open threads, then Profile, Model, Work) and App (General,
// Terminal, Agents, Providers, Computer). Pages are `bot:<name>` and the App page names; the page lives in the store
// (`ui.settingsPage`) so the model popover, the Details panel and the row menu's Edit bot can deep-link to a bot.
import { useEffect, useState } from "react";
import "./settings.css";
import type { SlotProps } from "../features";
import type { Bot, ModelOptions } from "../lib/protocol";
import { getStore, notifyEnabled, notifyErrorsEnabled, setNotifyEnabled, setNotifyErrorsEnabled, useStore } from "../state/store";
import { addToList } from "../addbot/bots";
import { appSounds, setSoundsEnabled, soundsEnabled } from "../lib/sounds";
import { LANG_NAMES, LANGS, t, type Key, type Lang } from "../i18n";
import { Avatar, GridIcon, ModelIcon, SourceIcon } from "../ui";
import { Seg } from "../chat/model/Seg";
import { reasoningPill } from "../chat/model/levels";
import { Appearance } from "./Appearance";
import { AccountsPage } from "./accounts/AccountsPage";
import { ProvidersPage } from "./providers/ProvidersPage";
import { TerminalPage } from "./terminal/TerminalPage";
import { SshMarker } from "../peers/SshMarker";
import { RemoteMachines } from "../peers/RemoteMachines";
import { openChangeServer, serverLabel, useServerMode } from "../app/remote";
import { gateShell } from "../app/BridgeGate";
import { setBar, useTasks } from "../tasks/state";
import { DISK_WARN_CHOICES, diskWarn, setDiskWarn } from "../lib/disk";
import { cpuWarn, setCpuWarn } from "../lib/cpu";
import { Toggle } from "../pages/kit";
import { awakeEnabled, closeHides, isMacPlatform, setAwakeEnabled, setCloseHides } from "../lib/power";
import { AgentsPage } from "./agents/AgentsPage";
import { ComputerPage } from "./computer/ComputerPage";
import { AvatarEditor, BotFacts, NameEditor, PictureActions, placeName, useBotInfo, usePictureEditor } from "./BotIdentity";
import { BotSections } from "./BotSections";
import { matchesSearch, searchKey } from "../lib/textMatch";

export const slot = "settings";

const APP_PAGES: { id: string; label: Key }[] = [
  { id: "general", label: "set.general" },
  { id: "terminal", label: "set.terminal" },
  { id: "agents", label: "set.agents" },
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
        ) : current === "terminal" ? (
          <TerminalPage />
        ) : current === "agents" ? (
          <AgentsPage />
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
  // what the route sends for that level, from the same source as the level itself (as the model picker's pill)
  const wire = chat?.reasoning ? chat.reasoningWire : opts?.current.reasoning_wire;
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
            <span className="be-st">{live ? t("bot.working") : statusText(bot.status)}</span>
            {bot.host && <SshMarker bot={bot} full testId="page-ssh" />}
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
      <BotSections key={bot.name} bot={bot} />

      <div className="st-gh">{t("set.profile")}</div>
      <div className="st-grp">
        <Row title={t("set.profileId")} hint={bot.is_default ? t("set.profileDefault") : t("set.profileHere")}>
          <Value mono>{bot.name}</Value>
        </Row>
      </div>

      <div className="st-gh">{t("set.model")}</div>
      <div className="st-grp">
        <Row title={t("set.modelMain")}>
          <Value>
            {model || "—"}
            {provider && <small>{providerName(opts, provider)}</small>}
          </Value>
        </Row>
        <Row title={t("set.reasoning")} hint={t("set.reasoningHint")}>
          <Value>{reasoningPill(reasoning, wire, opts?.reasoning_levels) || "—"}</Value>
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
          <button type="button" className="st-btn" onClick={() => s.openSettings("computer")} data-testid="bot-computer">
            {t("set.computerOpen")}
          </button>
        </Row>
      </div>
    </div>
  );
}

/** Every bot at a glance: picture, name, status, what it is doing and where it works. It lists every profile on
 *  this computer (management, not the sidebar list); each card says whether the bot is in the sidebar, or adds it. */
function BotsPage() {
  const s = useStore();
  const [q, setQ] = useState("");
  const needle = searchKey(q.trim());
  const bots = needle ? s.bots.filter((b) => matchesSearch(needle, b.display_name, b.name, b.description, b.model)) : s.bots;
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
  const listed = (s.ui.roster ?? []).includes(bot.name);
  const stWord = live ? t("bot.working") : statusText(bot.status);
  return (
    <div className="bot-card-w">
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
            <span className="bc-st" title={stWord} data-testid={`bot-status-${bot.name}`}>
              {stWord}
            </span>
            {bot.host ? (
              <SshMarker bot={bot} testId={`card-ssh-${bot.name}`} />
            ) : (
              bot.name !== bot.display_name.toLowerCase() && <code title={bot.name}>{bot.name}</code>
            )}
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
      {listed ? (
        <span className="bc-list in" data-testid={`bot-inlist-${bot.name}`}>
          {t("set.inList")}
        </span>
      ) : (
        <button
          type="button"
          className="bc-list"
          onClick={() => void addToList(getStore(), bot.name, { open: false })}
          aria-label={t("ab.addOf", { name: bot.display_name })}
          data-testid={`bot-addlist-${bot.name}`}
        >
          {t("set.addToList")}
        </button>
      )}
    </div>
  );
}

const MOD = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl+";
const WIN = typeof navigator !== "undefined" && /^Win/.test(navigator.platform);
const SHORTCUTS: [string, Key][] = [
  [`${MOD}1 … ${MOD}9`, "key.openBot"],
  [`${MOD}K`, "key.search"],
  [`${MOD}.`, "key.details"],
  [`${MOD},`, "key.settings"],
  [`${MOD}J`, "key.nextAsk"],
  [MOD === "⌘" ? `${MOD}N · ${MOD}T` : `${MOD}N`, "key.newSession"],
  [MOD === "⌘" ? "⌘D · ⌘⇧D" : "Ctrl+Shift+D · Alt+Shift+D", "key.splitPane"],
  [MOD === "⌘" ? "⌘W" : "Ctrl+Shift+W", "key.closePane"],
  [MOD === "⌘" ? "⌘⌥ ←↑↓→" : "Ctrl+Alt+ ←↑↓→", "key.focusPane"],
  [MOD === "⌘" ? "⌘] · ⌘[" : "Ctrl+Tab · Ctrl+Shift+Tab", "key.stepPane"],
  [MOD === "⌘" ? "⌘⇧⌥ ←↑↓→" : "Ctrl+Alt+Shift+ ←↑↓→", "key.movePane"],
  [MOD === "⌘" ? "⌘⇧↩" : "Ctrl+Shift+Enter", "key.zoomPane"],
  [MOD === "⌘" ? "⌘⌃=" : "Ctrl+Alt+=", "key.equalizePanes"],
  [MOD === "⌘" ? "⌘= · ⌘- · ⌘0" : "Ctrl+= · Ctrl+- · Ctrl+0", "key.termFont"],
  ...(MOD === "⌘"
    ? ([
        ["⌘← · ⌘→ · ⌘⌫ · ⌘⌦", "key.termLine"],
        ["⌥← · ⌥→", "key.termWord"],
      ] as [string, Key][])
    : ([
        [WIN ? "Ctrl+C · Ctrl+V · Ctrl+Shift+C · Ctrl+Shift+V · Ctrl+Insert · Shift+Insert" : "Ctrl+Shift+C · Ctrl+Shift+V · Ctrl+Insert · Shift+Insert", "key.termCopyPaste"],
        ["Ctrl+Shift+A", "key.termSelectAll"],
      ] as [string, Key][])),
  [MOD === "⌘" ? "⌘K" : "Ctrl+Shift+K", "key.termClear"],
  [MOD === "⌘" ? "⌘Home · ⌘End" : "Ctrl+Home · Ctrl+End", "key.termScroll"],
  [MOD === "⌘" ? "⌘↑ · ⌘↓" : "Ctrl+↑ · Ctrl+↓", "key.termPrompt"],
  [MOD === "⌘" ? "⌘⇧C" : "Alt+Shift+C", "key.copyLink"],
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

function NotifyErrorsSeg() {
  const [on, setOn] = useState(notifyErrorsEnabled());
  return (
    <Seg
      small
      label={t("set.notifyErrors")}
      value={on ? "on" : "off"}
      options={[
        { value: "on", label: t("set.on") },
        { value: "off", label: t("set.off") },
      ]}
      onChange={(v) => {
        setNotifyErrorsEnabled(v === "on");
        setOn(v === "on");
      }}
      testId="notify-errors-seg"
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

/** Settings › General: warn below 5/10/20/50 GB of free disk space, or not at all (src/lib/disk.ts). */
function DiskWarnSeg() {
  const [v, setV] = useState(diskWarn());
  return (
    <Seg
      small
      label={t("disk.setting")}
      value={String(v)}
      options={DISK_WARN_CHOICES.map((n) => ({ value: String(n), label: n ? t("disk.gb", { n }) : t("set.off") }))}
      onChange={(x) => {
        setV(Number(x));
        setDiskWarn(Number(x));
      }}
      testId="set-disk-warn"
    />
  );
}

/** Settings › General: warn when another app keeps a CPU core busy for over a minute (src/lib/cpu.ts). On by default. */
function CpuWarnToggle() {
  const [on, setOn] = useState(cpuWarn());
  return (
    <Toggle
      on={on}
      label={t("cpu.setting")}
      onChange={(v) => {
        setOn(v);
        setCpuWarn(v);
      }}
      testId="set-cpu-warn"
    />
  );
}

function TasksBarToggle() {
  const tk = useTasks();
  return <Toggle on={tk.bar} label={t("tasks.barSetting")} onChange={setBar} testId="set-tasks-bar" />;
}

function CloseSeg() {
  const [hide, setHide] = useState(closeHides());
  return (
    <Seg
      small
      label={t("win.close")}
      value={hide ? "tray" : "quit"}
      options={[
        { value: "tray", label: t("win.closeTray") },
        { value: "quit", label: t("win.closeQuit") },
      ]}
      onChange={(v) => {
        setCloseHides(v === "tray");
        setHide(v === "tray");
      }}
      testId="window-close-seg"
    />
  );
}

function AwakeToggle() {
  const [on, setOn] = useState(awakeEnabled());
  return (
    <Toggle
      on={on}
      label={t("awake.title")}
      onChange={(v) => {
        setAwakeEnabled(v);
        setOn(v);
      }}
      testId="set-awake"
    />
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
            small
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
        <Row title={t("set.notifyErrors")} hint={t("set.notifyErrorsHint")}>
          <NotifyErrorsSeg />
        </Row>
        <Row title={t("sounds.title")} hint={t("sounds.hint")}>
          <SoundsSeg />
        </Row>
        <Row title={t("disk.setting")} hint={t("disk.settingHint")}>
          <DiskWarnSeg />
        </Row>
        <Row title={t("cpu.setting")} hint={t("cpu.settingHint")}>
          <CpuWarnToggle />
        </Row>
      </div>
      <div className="st-gh">{t("set.sidebar")}</div>
      <div className="st-grp">
        <Row title={t("tasks.barSetting")} hint={t("tasks.barSettingHint")}>
          <TasksBarToggle />
        </Row>
      </div>
      <div className="st-gh">{t("set.system")}</div>
      <div className="st-grp" data-testid="set-system">
        <Row title={t("win.close")} hint={t(isMacPlatform() ? "win.closeHint" : "win.closeHintOther")}>
          <CloseSeg />
        </Row>
        <Row title={t("awake.title")} hint={t("awake.hint")}>
          <AwakeToggle />
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
      <ServerBlock />
      <RemoteMachines />
    </div>
  );
}

/** Remote-only mode (rule 47): the server omher uses, Change server (the gate's Connect form) and Use this computer. */
function ServerBlock() {
  const m = useServerMode();
  const [leaving, setLeaving] = useState(false);
  const [err, setErr] = useState("");
  if (m.mode !== "remote") return null;
  const leave = async () => {
    setLeaving(true);
    setErr("");
    try {
      await (await gateShell())?.remoteLeave?.();
      // this computer's bridge starts again (or the install screen shows if Hermes is missing here)
      window.location.reload();
    } catch (e) {
      setErr(String(e));
      setLeaving(false);
    }
  };
  return (
    <div data-testid="server-block">
      <div className="st-gh">{t("remote.server")}</div>
      <div className="st-grp">
        <Row title={serverLabel(m)} hint={t("remote.serverHint")}>
          <Value mono>
            <span data-testid="server-host">{m.host}</span>
          </Value>
        </Row>
        <Row title={t("remote.change")}>
          <button type="button" className="st-btn" onClick={openChangeServer} data-testid="server-change">
            {t("remote.change")}
          </button>
        </Row>
        <Row title={t("remote.useHere")} hint={t("remote.leaveHint")}>
          <button type="button" className="st-btn" disabled={leaving} onClick={() => void leave()} data-testid="server-leave">
            {t("remote.useHere")}
          </button>
        </Row>
      </div>
      {err && (
        <p className="peer-warn" role="alert">
          {err}
        </p>
      )}
    </div>
  );
}
