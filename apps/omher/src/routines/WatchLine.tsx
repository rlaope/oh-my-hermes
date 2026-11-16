// The line above an automation's answer in a bot's chat: "Watch · <name> · 14:05". The result Hermes handed to the
// Bot Chat is not drawn as a message from the person; only this line and the bot's answer under it.
import { useState } from "react";
import { hhmm } from "../app/time";
import { t } from "../i18n";
import { notUsefulQuote } from "../pages/watch";
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
          {t("watch.line")} · <span className="routine-name">{name}</span> · {hhmm(new Date(ts * 1000))}
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
