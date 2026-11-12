// When a plugin change takes effect for one bot, and the one press that makes it happen when one is needed.
// live: it is ready in the bot's next conversation (Hermes reloaded the bot's gateway itself, silently). reload: the
// gateway did not reload, so "Load now" asks it (`plugins.reload`, Hermes' own `reload-plugins`: restarts nothing).
// restart: only a restart of the gateway process that serves the bot loads it (Hermes says its dependencies are
// missing there); the line names every bot on that gateway before the press, and the press is the same Restart as
// the bot row's (restart.ts).
import { useState } from "react";
import type { Bot } from "../lib/protocol";
import { useStore } from "../state/store";
import { listText, t } from "../i18n";
import { RestartAction, RestartLine } from "../sidebar/RestartLine";
import { useMates } from "../sidebar/restart";

type Load = "live" | "reload" | "restart";

function RestartLoad({ bot, testId }: { bot: Bot; testId: string }) {
  const mates = useMates(bot.name);
  return (
    <span className="pl-load" data-testid={testId} data-load="restart">
      {mates.length
        ? t("plug.sheet.needsRestart", { bots: listText([bot.display_name, ...mates.map((m) => m.display_name)]) })
        : t("plug.sheet.needsRestart1", { bots: bot.display_name })}{" "}
      <RestartAction bot={bot} label={t(mates.length ? "plug.sheet.restartThem" : "plug.sheet.restartIt")} testId={`${testId}-restart`} />
      <RestartLine bot={bot} testId={`${testId}-restart-line`} />
    </span>
  );
}

export function PluginLoad({ bot, plugin, load, testId = "plug-load" }: {
  bot: Bot;
  plugin: string;
  load: Load;
  /** The profile whose gateway serves the bot (the bridge's answer); the restart resolves it again on the press. */
  restartBot?: string;
  testId?: string;
}) {
  const s = useStore();
  const [st, setSt] = useState<{ load: Load | "loading" | "failed"; why?: string }>({ load });
  if (st.load === "live") {
    return (
      <span className="pl-load" data-testid={testId} data-load="live">
        {t("plug.sheet.live", { bot: bot.display_name })}
      </span>
    );
  }
  if (st.load === "restart") return <RestartLoad bot={bot} testId={testId} />;
  const reload = async () => {
    setSt({ load: "loading" });
    try {
      const r = await s.reloadPlugins(bot.name, plugin);
      if (r.load === "failed") setSt({ load: "failed", why: r.line ?? "" });
      else setSt({ load: r.load });
    } catch (e) {
      setSt({ load: "failed", why: typeof e === "object" && e && "message" in e ? String((e as { message: unknown }).message) : String(e) });
    }
  };
  return (
    <span className="pl-load" data-testid={testId} data-load={st.load}>
      {st.load === "failed" ? t("plug.sheet.loadFailed", { bot: bot.display_name, why: st.why ?? "" }) : t("plug.sheet.reload", { bot: bot.display_name })}{" "}
      {st.load === "loading" ? (
        <span className="rs-wait" role="status">
          {t("plug.sheet.loading")}
        </span>
      ) : (
        <button type="button" className="rs-act go" onClick={() => void reload()} data-testid={`${testId}-now`}>
          {st.load === "failed" ? t("rs.again") : t("plug.sheet.loadNow")}
        </button>
      )}
    </span>
  );
}
