// The one place a "load oh-my-hermes into this bot" action attaches to, beside the quiet line that says a bot does not
// have oh-my-hermes' tools (or skills) yet (OmhPromptLine). Empty on purpose: which press really loads a newly
// enabled plugin is Hermes' `reload-plugins` control verb or a restart of the host gateway, never a restart of one
// named bot. Slot 14 of the merge train (`feat/omher-bot-restart`) fills this with that action; nothing else here
// runs, restarts or reloads anything.
import type { Bot } from "../lib/protocol";

export function OmhLoadAction(_props: { bot: Bot }) {
  return null;
}
