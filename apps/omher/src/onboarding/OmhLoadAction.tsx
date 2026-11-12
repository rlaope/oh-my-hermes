// The one place a "load oh-my-hermes into this bot" action attaches to, beside the quiet line that says a bot does not
// have oh-my-hermes' tools (or skills) yet (OmhPromptLine). Restarting one named bot does not load a new plugin
// (Hermes serves it again in the same process, and plugins are discovered once per process), so the press is Hermes'
// own `reload-plugins` on the bot's gateway (PluginLoad below); only when Hermes answers that a restart is still
// needed does it offer that restart, of the process that serves the bot, naming every bot that goes down with it.
import type { Bot } from "../lib/protocol";
import { PluginLoad } from "../pages/PluginLoad";

export function OmhLoadAction({ bot }: { bot: Bot }) {
  return <PluginLoad bot={bot} plugin="omh" load="reload" compact testId="omh-load" />;
}
