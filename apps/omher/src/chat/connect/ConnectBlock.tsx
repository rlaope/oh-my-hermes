// The chat's connect block: one quiet line in the bot's timeline when Hermes says the bot cannot answer
// (`bots.ready`, ready.ts), with a short row of sign-ins. Each opens the person's own system terminal running exactly
// `hermes auth add <id>` (src-tauri hermes_auth.rs, BOUNDARY rule 23), where Hermes runs that provider's sign-in; "API
// key…" opens Settings › Providers, whose Add key menu is the `--type api-key` form (an Anthropic key goes there).
// There is no Claude sign-in: Hermes' Anthropic OAuth answers only on Claude Max with purchased extra-usage credits,
// so most people who picked it got a 400 "out of extra usage". omher sees nothing typed in the terminal.
// After a pick the line says to finish in the terminal and the bot is asked again until it can answer; then the
// block goes and the composer gets focus. The composer stays usable the whole time.
import { useEffect, useRef, useState } from "react";
import type { Bot } from "../../lib/protocol";
import { getStore } from "../../state/store";
import { t, tx } from "../../i18n";
import { signInHost } from "../../settings/providers/authHost";
import { SIGN_IN, getReady, useBotReady, type SignIn } from "./ready";
import "./connect.css";

const LABEL: Record<SignIn, "cn.codex" | "cn.nous"> = {
  "openai-codex": "cn.codex",
  nous: "cn.nous",
};

export const signInCommand = (provider: SignIn) => `hermes auth add ${provider}`;

export function ConnectBlock({ bot }: { bot: Bot }) {
  const r = useBotReady(bot.name);
  const [problem, setProblem] = useState<{ provider: SignIn; error?: string } | null>(null);
  const was = useRef(r.status);
  useEffect(() => {
    if (bot.status !== "offline") void getReady().ensure(bot.name);
  }, [bot.name, bot.status, r.stale]);
  // ready again after a wait: the block goes and the composer takes the focus
  useEffect(() => {
    if (was.current === "not" && r.status === "ready") {
      setProblem(null);
      document.querySelector<HTMLTextAreaElement>('[data-testid="composer"]')?.focus();
    }
    was.current = r.status;
  }, [r.status]);
  useEffect(() => setProblem(null), [bot.name]);
  if (r.status !== "not" || bot.status === "offline") return null;

  const open = (provider: SignIn) => {
    const host = signInHost();
    if (!host) return setProblem({ provider });
    setProblem(null);
    getReady().waitFor(bot.name, provider);
    host.open(provider).catch((e: unknown) => {
      getReady().stop(bot.name);
      setProblem({ provider, error: e instanceof Error ? e.message : String(e) });
    });
  };

  return (
    <div className="cn" role="note" data-testid="connect-block" data-bot={bot.name}>
      <div className="cn-t" data-testid="connect-text">
        {r.waiting ? t("cn.finish") : t("cn.needs", { bot: bot.display_name })}
      </div>
      <div className="cn-row">
        {SIGN_IN.map((p) => (
          <button
            key={p}
            type="button"
            className={`cn-go${r.waiting === p ? " on" : ""}`}
            title={signInCommand(p)}
            onClick={() => open(p)}
            data-testid={`connect-${p}`}
          >
            {t(LABEL[p])}
          </button>
        ))}
        <button type="button" className="cn-go" onClick={() => getStore().actions.openSettings("providers")} data-testid="connect-key">
          {t("cn.key")}
        </button>
      </div>
      {problem && (
        <div className="cn-t cn-sub" role="status" data-testid="connect-problem">
          {problem.error
            ? tx("cn.openFailed", { error: problem.error, cmd: <code>{signInCommand(problem.provider)}</code> })
            : tx("cn.manual", { cmd: <code>{signInCommand(problem.provider)}</code> })}
        </div>
      )}
    </div>
  );
}
