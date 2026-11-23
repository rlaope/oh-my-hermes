// Apps: one bot's apps (BOUNDARY rule 42). Hermes' MCP catalog and its integration skills, grouped by tier, each with
// its state for that bot, read from files by the bridge. Connect, Sign in and Remove run the bot's own
// `hermes -p <bot> mcp install|login|remove <name>`; the sign-in itself is Hermes' own browser flow, and omher never
// sees a key or a token. Skills only show their state: the bot sets one up when asked in chat.
import { useCallback, useEffect, useState } from "react";
import type { AppRow, AppSkill, Bot } from "../lib/protocol";
import { useStore } from "../state/store";
import { t, type Key } from "../i18n";
import { SearchIcon } from "../ui";
import { BrandIcon } from "../ui/brandIcons";
import { AskBox, BotChip, errorLine, PageHead } from "../pages/kit";
import { CopyButton } from "../chat/parts/Copy";
import { openShellAt } from "../tasks/TasksPage";
import { actionsOf, markOf, sections, titleOf, type Card } from "./tiers";
import "../pages/pages.css";

type Verb = "install" | "login" | "remove";
type Data = { catalog: boolean; apps: AppRow[]; skills: AppSkill[] };
type Result = { bot: string; name: string; verb: Verb; ok: boolean; text: string; asks: string[] };

/** The line after a run that worked: what changed, and when the bot has the app's tools (Hermes' gateway connects a new
 *  server on its own about once a minute; a chat already open gets its tools after `/reload-mcp`). */
export function doneWords(verb: Verb, state: string, name: string, bot: string): string {
  const v = { name: titleOf(name), bot };
  if (verb === "remove") return t("apps.removed", v);
  if (verb === "login") return t("apps.signedIn", v);
  return state === "needs_signin" ? t("apps.addedSignin", v) : t("apps.connected", v);
}

export function AppsPage() {
  const s = useStore();
  const local = s.bots.filter((b) => !b.host);
  const scope = local.find((b) => b.name === s.ui.appsBot) ?? local.find((b) => b.name === s.selectedBot) ?? local[0];
  const scopeName = scope?.name;
  const [data, setData] = useState<Data | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<{ bot: string; name: string; verb: Verb } | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [askBot, setAskBot] = useState<string | null>(null);
  const [text, setText] = useState("");
  const askTo = local.find((b) => b.name === askBot) ?? scope;

  const reload = useCallback(async () => {
    if (!scopeName) return;
    try {
      setData(await s.appsList(scopeName));
      setErr(null);
    } catch (e) {
      setData({ catalog: true, apps: [], skills: [] });
      setErr(errorLine(e, local.find((b) => b.name === scopeName)?.display_name ?? scopeName));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeName]);

  useEffect(() => {
    setData(null);
    void reload();
  }, [reload]);

  const run = async (verb: Verb, app: AppRow) => {
    if (!scope) return;
    setBusy({ bot: scope.name, name: app.name, verb });
    setResult(null);
    let r: Result;
    try {
      const out = await s.appsRun(verb, scope.name, app.name);
      const ok = out.outcome === "ok";
      r = { bot: scope.name, name: app.name, verb, ok, asks: app.asks,
            text: ok ? doneWords(verb, out.state, app.name, scope.display_name) : (out.line ?? t("apps.failed", { name: titleOf(app.name) })) };
    } catch (e) {
      r = { bot: scope.name, name: app.name, verb, ok: false, asks: app.asks, text: errorLine(e, scope.display_name) };
    }
    setBusy(null);
    setResult(r);
    await reload();
  };

  const send = () => {
    if (!askTo || !text.trim()) return;
    const msg = text.trim();
    setText("");
    void s.sendTo(askTo.name, msg);
  };

  const groups = data ? sections(data.apps, data.skills, query) : [];
  const mine = busy && busy.bot === scopeName ? busy : null;
  const shown = result && result.bot === scopeName ? result : null;
  const cmd = shown && scope ? `hermes -p ${scope.name} mcp install ${shown.name}` : "";

  return (
    <div className="pg" data-testid="apps">
      <PageHead
        title={t("apps.title")}
        sub={t("apps.sub")}
        right={
          <BotChip
            bots={local}
            bot={scope}
            wide
            label={scope ? t("apps.scope", { bot: scope.display_name }) : undefined}
            onPick={(n) => s.openApps(n)}
            testId="apps-scope"
          />
        }
      />
      <div className="pg-body">
        <div className="pg-scroll">
          <AskBox bots={local} bot={askTo} onBot={setAskBot} value={text} onChange={setText} placeholder={t("apps.placeholder")} onSend={send} />
          <div className="pl-browsebar">
            <label className="pl-search">
              <SearchIcon />
              <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("apps.search")} aria-label={t("apps.search")} data-testid="apps-search" />
            </label>
          </div>
          {err && (
            <p className="pg-err" role="alert" data-testid="page-error">
              {err}
            </p>
          )}
          {mine?.verb === "login" && (
            <p className="pg-note" role="status" data-testid="apps-signing">
              {t("apps.signingIn", { name: titleOf(mine.name) })}
            </p>
          )}
          {shown && (
            <div className={shown.ok ? "pg-note ap-said" : "pg-err ap-said"} role={shown.ok ? "status" : "alert"} data-testid="apps-result">
              <span>{shown.text}</span>
              {!shown.ok && shown.verb === "install" && shown.asks.length > 0 && (
                <div className="ap-term">
                  <span>{t("apps.terminalHint", { env: shown.asks.join(", ") })}</span>
                  <code className="ap-cmd" data-testid="apps-terminal-cmd">
                    {cmd}
                    <CopyButton text={() => cmd} />
                  </code>
                  <button type="button" className="pg-btn" onClick={() => openShellAt(null)} data-testid="apps-terminal">
                    {t("tasks.openTerminal")}
                  </button>
                </div>
              )}
            </div>
          )}
          {!scope ? (
            <div className="pg-empty" data-testid="apps-no-bot">
              <b>{t("apps.noBot")}</b>
            </div>
          ) : !data ? (
            <div className="pg-empty">{t("apps.loading")}</div>
          ) : (
            <>
              {!data.catalog && (
                <div className="pg-empty" data-testid="apps-no-catalog">
                  <b>{t("apps.noCatalog")}</b>
                  <span>{t("apps.noCatalogHint")}</span>
                </div>
              )}
              {groups.length === 0 && query.trim() !== "" && <div className="pg-empty">{t("apps.noMatch")}</div>}
              {groups.map((g) => (
                <section key={g.tier} className="ap-sec" data-testid={`apps-sec-${g.tier}`}>
                  <h3 className="ap-h">{t(`apps.tier.${g.tier}` as Key)}</h3>
                  <div className="pl-grid">
                    {g.cards.map((c) => (
                      <AppCard key={`${c.kind}:${nameOf(c)}`} card={c} bot={scope} busy={mine} onRun={(verb, app) => void run(verb, app)} />
                    ))}
                  </div>
                  {g.tier === "work" && g.cards.some((c) => c.kind === "skill") && (
                    <p className="pg-foot">{t("apps.skillNote", { bot: scope.display_name })}</p>
                  )}
                </section>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const nameOf = (c: Card) => (c.kind === "mcp" ? c.app.name : c.skill.name);

const STATE_KEY: Record<string, Key> = {
  available: "apps.state.available",
  installed: "apps.state.installed",
  disabled: "apps.state.disabled",
  needs_signin: "apps.state.needs_signin",
  unknown: "apps.state.unknown",
};
const SKILL_KEY: Record<string, Key> = {
  installed: "apps.skill.installed",
  disabled: "apps.skill.disabled",
  available: "apps.skill.available",
};

export function AppCard({
  card,
  bot,
  busy,
  onRun,
}: {
  card: Card;
  bot: Bot;
  busy: { name: string; verb: Verb } | null;
  onRun: (verb: Verb, app: AppRow) => void;
}) {
  const [confirm, setConfirm] = useState(false);
  const name = nameOf(card);
  const label = titleOf(name);
  const state = card.kind === "mcp" ? card.app.state : card.skill.state;
  const stateWord = card.kind === "mcp" ? t(STATE_KEY[state] ?? "apps.state.unknown") : t(SKILL_KEY[state] ?? "apps.state.unknown");
  const warn = state === "needs_signin" || state === "unknown";
  const desc = card.kind === "mcp" ? card.app.description : card.skill.description;
  const acts = card.kind === "mcp" ? actionsOf(card.app) : [];
  const running = (verb: Verb) => busy?.name === name && busy.verb === verb;
  const pressLabel = (verb: Verb) =>
    verb === "install"
      ? running(verb) ? t("apps.connecting") : t("apps.connect")
      : verb === "login"
        ? running(verb) ? t("apps.waiting") : state === "needs_signin" ? t("apps.signin") : t("apps.signinAgain")
        : running(verb) ? t("apps.removing") : t("apps.remove");
  return (
    <div className="pl-card" data-testid={`app-card-${name}`}>
      <span className="pl-pic" aria-hidden="true">
        <BrandIcon service={markOf(name)} size={18} />
      </span>
      <div className="pl-main">
        <div className="pl-nm">
          <span className="pl-nm-t">{label}</span>
          <span className="pl-badge">{card.kind === "mcp" ? t("apps.kind.mcp") : t("apps.kind.skill")}</span>
        </div>
        <p className="pl-ds">{desc}</p>
        <div className="pl-adds">
          <span className={`ap-state ${state}${warn ? " need" : ""}`} data-testid={`app-state-${name}`}>
            {stateWord}
          </span>
          {card.kind === "mcp" && card.app.asks.length > 0 && state === "available" && (
            <span className="need">{t("apps.asks", { env: card.app.asks.join(", ") })}</span>
          )}
        </div>
      </div>
      {card.kind === "mcp" && acts.length > 0 && (
        <div className="pl-ctl">
          {confirm ? (
            <div className="ap-confirm" role="alertdialog" aria-label={t("apps.confirmRemove", { name: label, bot: bot.display_name })}>
              <span>{t("apps.confirmRemove", { name: label, bot: bot.display_name })}</span>
              <button
                type="button"
                className="pg-btn danger-fill"
                onClick={() => {
                  setConfirm(false);
                  onRun("remove", card.app);
                }}
                data-testid="app-confirm-remove"
              >
                {t("apps.remove")}
              </button>
              <button type="button" className="pg-btn" onClick={() => setConfirm(false)}>
                {t("page.cancel")}
              </button>
            </div>
          ) : (
            acts.map((verb) => (
              <button
                key={verb}
                type="button"
                className={`pg-btn${verb === "remove" ? " danger" : verb === "install" || state === "needs_signin" ? " pri" : ""}`}
                disabled={!!busy}
                aria-label={`${pressLabel(verb)} · ${label}`}
                onClick={() => (verb === "remove" ? setConfirm(true) : onRun(verb, card.app))}
                data-testid={`app-${verb}-${name}`}
              >
                {pressLabel(verb)}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
