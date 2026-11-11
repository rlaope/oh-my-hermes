// The cards in a bot's main chat for what the bot made there itself: an automation (`routine.added`, a new job id in
// its jobs.json) or a plugin (`plugin.added`, a new folder in its plugins/). Each is the same item the Automations
// or Plugins page lists; omher keeps no copy of its own. Their actions are the pages' own: a chat message, the
// bot's `cron.manage remove`, its `plugins.manage toggle`.
import { useState } from "react";
import type { Automation } from "../lib/protocol";
import { useStore, type PluginAddedItem, type RoutineAddedItem } from "../state/store";
import { t } from "../i18n";
import { Avatar, SourceIcon } from "../ui";
import { deliverParts } from "./Automations";
import { addsOf } from "./Plugins";
import { ClockIcon, PlugIcon } from "./icons";
import { errorLine, nextWords, toSec } from "./kit";

export function RoutineAddedCard({ bot, item }: { bot: string; item: RoutineAddedItem }) {
  const s = useStore();
  const [state, setState] = useState<"idle" | "confirm" | "busy" | "undone">("idle");
  const [err, setErr] = useState<string | null>(null);
  const botName = s.bots.find((b) => b.name === bot)?.display_name ?? bot;
  // the freshest copy the Automations list has (a later pause or edit shows here too)
  const live = s.automations?.find((a) => a.bot === bot && a.id === item.routine_id);
  const gone = state === "undone";
  const next = toSec(live?.next_run_at ?? item.next_run_at);
  const asAuto = { bot, deliver: item.deliver, origin: item.origin } as Automation;
  const undo = async () => {
    setState("busy");
    setErr(null);
    try {
      await s.automationDo(bot, item.routine_id, "remove");
      setState("undone");
    } catch (e) {
      setErr(errorLine(e, botName));
      setState("idle");
    }
  };
  return (
    <div className="mk-card" data-testid="routine-added-card">
      <div className="mk-top">
        <span className="mk-ic">
          <ClockIcon />
        </span>
        <span className="mk-name">{live?.name ?? item.name}</span>
        <span className="mk-tag">{gone ? t("card.undone") : t("card.newAuto")}</span>
      </div>
      <dl className="mk-meta">
        <dt>{t("card.when")}</dt>
        <dd>
          {live?.schedule ?? item.schedule}
          {next && !gone && <span className="mk-quiet"> · {t("auto.next", { when: nextWords(next) })}</span>}
        </dd>
        <dt>{t("card.deliver")}</dt>
        <dd className="mk-dl">
          {deliverParts(asAuto, s.bots).map((d, i) => (
            <span key={i}>
              {d.bot ? <Avatar bot={d.bot} size={14} /> : d.source ? <SourceIcon source={d.source} size={13} /> : null}
              {d.text}
            </span>
          ))}
        </dd>
      </dl>
      {err && <p className="pg-err">{err}</p>}
      {!gone &&
        (state === "confirm" || state === "busy" ? (
          <div className="pg-btns">
            <span className="mk-confirm">{t("card.confirmUndo", { name: item.name })}</span>
            <button type="button" className="pg-btn danger-fill" disabled={state === "busy"} onClick={() => void undo()} data-testid="card-undo-confirm">
              {t("auto.delete")}
            </button>
            <button type="button" className="pg-btn" onClick={() => setState("idle")}>
              {t("page.cancel")}
            </button>
          </div>
        ) : (
          <div className="pg-btns">
            <button
              type="button"
              className="pg-btn"
              onClick={() => void s.sendTo(bot, t("auto.runMsg", { name: item.name, id: item.routine_id }))}
              data-testid="card-run"
            >
              {t("card.runOnce")}
            </button>
            <button type="button" className="pg-btn" onClick={() => s.openAutomations(`${bot}:${item.routine_id}`)} data-testid="card-open-auto">
              {t("card.openAuto")}
            </button>
            <button type="button" className="pg-btn danger" onClick={() => setState("confirm")} data-testid="card-undo">
              {t("card.undo")}
            </button>
          </div>
        ))}
    </div>
  );
}

export function PluginAddedCard({ bot, item }: { bot: string; item: PluginAddedItem }) {
  const s = useStore();
  const [off, setOff] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const botName = s.bots.find((b) => b.name === bot)?.display_name ?? bot;
  const label = item.title || item.name;
  const adds = addsOf({ tools: item.tools, hooks: item.hooks, category: "" });
  const turnOff = async () => {
    setErr(null);
    try {
      await s.pluginsToggle(bot, item.name, false);
      setOff(true);
    } catch (e) {
      setErr(errorLine(e, botName));
    }
  };
  return (
    <div className="mk-card" data-testid="plugin-added-card">
      <div className="mk-top">
        <span className="mk-ic">
          <PlugIcon />
        </span>
        <span className="mk-name">{t("card.plugInstalled", { name: label })}</span>
        {off && <span className="mk-tag">{t("card.turnedOff")}</span>}
      </div>
      {adds.length > 0 && <p className="mk-line">{t("card.plugAdds", { what: adds.join(" · ") })}</p>}
      {err && <p className="pg-err">{err}</p>}
      <div className="pg-btns">
        <button type="button" className="pg-btn" onClick={() => s.openPlugins(bot)} data-testid="card-open-plug">
          {t("card.openPlug")}
        </button>
        {!off && (
          <button type="button" className="pg-btn" onClick={() => void turnOff()} data-testid="card-turn-off">
            {t("card.turnOff")}
          </button>
        )}
      </div>
    </div>
  );
}
