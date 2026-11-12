// When a plugin change takes effect for one bot, and the one press that makes it happen when one is needed.
// live: it is ready in the bot's next conversation (Hermes reloaded the bot's gateway itself). reload: the gateway
// did not reload, so "Load now" asks it (`plugins.reload`, Hermes' own `reload-plugins`: restarts nothing). restart:
// only a restart of the process that serves the bot loads it (Hermes says its dependencies are missing there); the
// press is that bot's Restart (restart.ts), whose confirm names every bot that goes down with it.
import { useState } from "react";
import type { Bot } from "../lib/protocol";
import { useStore } from "../state/store";
import { t } from "../i18n";
import { RestartAction, RestartLine } from "../sidebar/RestartLine";

type Load = "live" | "reload" | "restart";

export function PluginLoad({ bot, plugin, load, restartBot, testId = "plug-load" }: {
  bot: Bot;
  plugin: string;
  load: Load;
  restartBot?: string;
  testId?: string;
}) {
  const s = useStore();
  const [st, setSt] = useState<{ load: Load | "loading" | "failed"; host?: string; why?: string }>({ load, host: restartBot });
  const host = s.bots.find((b) => b.name === (st.host ?? "default")) ?? bot;
  if (st.load === "live") {
    return (
      <span className="pl-load" data-testid={testId} data-load="live">
        {t("plug.sheet.live", { bot: bot.display_name })}
      </span>
    );
  }
  if (st.load === "restart") {
    return (
      <span className="pl-load" data-testid={testId} data-load="restart">
        {t("plug.sheet.needsRestart", { host: host.display_name })} <RestartAction bot={host} testId={`${testId}-restart`} />
        <RestartLine bot={host} testId={`${testId}-restart-line`} />
      </span>
    );
  }
  const reload = async () => {
    setSt((x) => ({ ...x, load: "loading" }));
    try {
      const r = await s.reloadPlugins(bot.name, plugin);
      if (r.load === "failed") setSt({ load: "failed", why: r.line ?? "" });
      else setSt({ load: r.load, host: r.restart_bot });
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
        <button type="button" className="rs-act" onClick={() => void reload()} data-testid={`${testId}-now`}>
          {st.load === "failed" ? t("rs.again") : t("plug.sheet.loadNow")}
        </button>
      )}
    </span>
  );
}
