// A chat Hermes paused: a turn of it was lost when Hermes' gateway stopped mid-turn (a crash, a kill, Windows ending
// the process), and Hermes holds every later message of that chat until someone acknowledges the lost turn (#3123).
// One quiet block above the composer, like the connect block, says so and offers Discard (bridge `chat.discard`,
// Hermes' own `prompt.resolve_unknown`). The composer stays usable: what is sent meanwhile waits in Hermes' queue.
import { useEffect, useState } from "react";
import type { Bot } from "../../lib/protocol";
import { getStore, type Chat } from "../../state/store";
import { t } from "../../i18n";
import "../connect/connect.css";

export function LostTurnBlock({ bot, chat, thread }: { bot: Bot; chat: Chat | undefined; thread?: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = thread ?? bot.name;
  useEffect(() => setError(null), [key]);
  const lost = chat?.lost ?? [];
  if (!lost.length || bot.status === "offline") return null;
  const discard = () => {
    setBusy(true);
    setError(null);
    getStore()
      .actions.discardLost(bot.name, thread ?? null)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String((e as { message?: unknown })?.message ?? e)))
      .finally(() => setBusy(false));
  };
  return (
    <div className="cn" role="alert" data-testid="lost-turn" data-bot={bot.name}>
      <div className="cn-t" data-testid="lost-turn-text">
        {t("lost.paused", { bot: bot.display_name })}
      </div>
      {lost.map((l) =>
        l.text ? (
          <div key={l.id} className="cn-t cn-sub" data-testid="lost-turn-quote">
            {t("lost.turn", { text: l.text.length > 160 ? `${l.text.slice(0, 160)}…` : l.text })}
          </div>
        ) : null,
      )}
      <div className="cn-t cn-sub">{t("lost.after")}</div>
      <div className="cn-row">
        <button type="button" className="cn-go" disabled={busy} onClick={discard} data-testid="lost-turn-discard">
          {busy ? t("lost.discarding") : t("lost.discard")}
        </button>
      </div>
      {error && (
        <div className="cn-t cn-sub" role="status" data-testid="lost-turn-error">
          {t("lost.failed", { error })}
        </div>
      )}
    </div>
  );
}
