// The line above an automation's answer in a bot's chat: "Watch · <name> · 14:05". The result Hermes handed to the
// Bot Chat is not drawn as a message from the person; only this line and the bot's answer under it.
import { useState } from "react";
import { hhmm } from "../app/time";
import { t } from "../i18n";
import { BRIEF_JOB, notUsefulQuote } from "../pages/watch";
import type { Bot } from "../lib/protocol";
import { useStore } from "../state/store";
import "./routines.css";

/** `text`: the answer under the line. "Not useful" tells the bot once, as one chat message naming the watch and the
 *  alert, so it can narrow what it flags; it changes no automation itself. */
export function WatchLine({ name, ts, text }: { name: string; ts: number; text: string }) {
  const s = useStore();
  const [sent, setSent] = useState(false);
  const first = notUsefulQuote(text);
  return (
    <div className="routine watch-line" data-testid="watch-line">
      <span className="routine-row">
        <span className="routine-ic" aria-hidden>
          ◉
        </span>
        <span className="routine-t">
          {t(name === BRIEF_JOB ? "brief.line" : "watch.line")} · <span className="routine-name">{name}</span> · {hhmm(new Date(ts * 1000))}
        </span>
        <button
          type="button"
          className="watch-nu"
          data-testid="watch-not-useful"
          disabled={sent}
          title={t("watch.notUsefulTip")}
          onClick={() => {
            if (sent) return;
            setSent(true);
            void s.send(t("watch.notUsefulMsg", { name, alert: first }));
          }}
        >
          {sent ? t("watch.notUsefulSent") : t("watch.notUseful")}
        </button>
      </span>
    </div>
  );
}

/** The one gray line omher draws once in a bot's chat after it set up the Slack briefing: "Kami will brief you here
 *  when something in Slack needs you · Turn off". Turn off pauses that job through the same automations op. */
export function BriefNotice({ bot }: { bot: Bot }) {
  const s = useStore();
  const [off, setOff] = useState(false);
  const job = (s.automations ?? []).find((a) => a.bot === bot.name && a.name === BRIEF_JOB);
  return (
    <div className="line sys brief-notice" data-testid="brief-notice">
      <span className="line-t">{t("brief.notice", { bot: bot.display_name })}</span>
      <span aria-hidden>·</span>
      <button
        type="button"
        className="brief-off"
        data-testid="brief-turn-off"
        disabled={off || !job}
        onClick={() => {
          if (!job || off) return;
          setOff(true);
          void s.automationDo(bot.name, job.id, "pause").catch(() => setOff(false));
        }}
      >
        {off ? t("brief.off") : t("brief.turnOff")}
      </button>
    </div>
  );
}
