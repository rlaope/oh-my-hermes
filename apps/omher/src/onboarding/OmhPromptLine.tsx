// The one quiet line above a bot's composer after omher installed oh-my-hermes (omhPrompt.ts): "oh-my-hermes is
// ready. Set up your models?" with one text action that puts the request in the composer (nothing is sent) and an
// x; under it, when the bot's running gateway has not loaded oh-my-hermes' plugin, one more quiet line with Hermes'
// restart command as text; or, when the bot's skills never showed the command, only that the bot needs a restart.
import { useEffect, useLayoutEffect, useRef } from "react";
import type { Bot } from "../lib/protocol";
import { getStore } from "../state/store";
import { CloseIcon } from "../ui";
import { t, tx } from "../i18n";
import { getOmhPrompt, promptText, restartCommand, useOmhPrompt } from "./omhPrompt";
import "./firstrun.css";

export function OmhPromptLine({ bot }: { bot: Bot }) {
  const p = useOmhPrompt();
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (p.phase === "pending") void getOmhPrompt().check(bot.name);
  }, [p.phase, bot.name]);
  const shown = (p.phase === "ready" || p.phase === "restart") && p.bot === bot.name;
  // The line takes its own row above the composer: a thread that sat at its end stays at its end, so the line never
  // hides the last message.
  useLayoutEffect(() => {
    const el = ref.current?.closest(".pane")?.querySelector<HTMLElement>(".thread");
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 80) el.scrollTop = el.scrollHeight;
  }, [shown]);
  if (!shown) return null;
  const close = (
    <button type="button" className="omhp-x" aria-label={t("page.close")} title={t("page.close")} onClick={() => getOmhPrompt().finish()} data-testid="omh-prompt-close">
      <CloseIcon />
    </button>
  );
  const cmd = <code className="omhp-cmd">{restartCommand(bot)}</code>;
  if (p.phase === "restart") {
    // no command in the bot's skills: the restart comes first; after the action: what is still to do
    return (
      <div className="omhp" ref={ref} role="note" data-testid="omh-prompt-restart">
        <span className="omhp-t">{tx(p.command ? "omhp.tools" : "omhp.restart", { bot: bot.display_name, cmd })}</span>
        {close}
      </div>
    );
  }
  return (
    <div className="omhp-wrap" ref={ref} role="note">
      <div className="omhp" data-testid="omh-prompt">
        <span className="omhp-t">{t("omhp.ready")}</span>
        <button
          type="button"
          className="omhp-go"
          title={t("graph.prefill")}
          onClick={() => {
            getStore().actions.prefill(promptText(p.command!));
            getOmhPrompt().used();
          }}
          data-testid="omh-prompt-fill"
        >
          {t("omhp.fill")}
        </button>
        {close}
      </div>
      {p.restart && (
        <div className="omhp omhp-sub" data-testid="omh-prompt-tools">
          <span className="omhp-t">{tx("omhp.tools", { bot: bot.display_name, cmd })}</span>
        </div>
      )}
    </div>
  );
}
