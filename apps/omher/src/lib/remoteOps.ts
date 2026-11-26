// Remote-only mode's one outgoing filter (BOUNDARY rule 46). Every op the page sends goes through
// `BridgeClient.request`, which asks `remoteRefusal` first: while omher uses a server, an op that would carry this
// computer's folder, path or file bytes there is refused and never written to the socket. The table names every op the
// page can send (the type makes a new op fail to compile until it is placed here), and anything not in it is refused
// on a server too. In local mode nothing is refused: the page behaves as before rule 46.
import type { Key } from "../i18n";
import type { Op } from "./protocol";
import type { ThreadOps } from "../threads/types";

/** Every op name the page sends: the protocol's, the threads lane's, and the node-session read's. */
export type PageOp = Op | keyof ThreadOps | "runs.node_session";

export type OpRule =
  /** Sent on a server too: what it carries is the person's own typing, a name, or an id or path the server named. */
  | { send: "always"; why: string }
  /** Never sent on a server: it is about a folder, file or session of this computer. */
  | { send: "never"; key: Key; why: string }
  /** Refused on a server when `field` is given (it holds this computer's folder or bytes); sent without it. */
  | { send: "without"; field: string; key: Key; why: string };

const ok = (why: string): OpRule => ({ send: "always", why });
const FOLDER: Key = "remote.noFolderChat";
const FILES: Key = "remote.noFiles";
const HERE: Key = "remote.notHere";

/** The audit: each op, the field that could carry this computer, and whether it goes to a server. */
export const REMOTE_OPS: Record<PageOp, OpRule> = {
  hello: ok("no fields"),
  "bots.list": ok("no fields"),
  "chat.open": ok("bot name only"),
  "chat.send": ok("text the person typed; reply_to is a session id the server listed"),
  "chat.interrupt": ok("bot and session ids"),
  "chat.discard": ok("bot and session ids"),
  "chat.steer": ok("text the person typed"),
  "approval.respond": ok("a card's request id and the person's choice"),
  "clarify.respond": ok("the person's answers"),
  "folder.open": { send: "never", key: FOLDER, why: "cwd is a folder of this computer" },
  "folder.close": { send: "never", key: FOLDER, why: "closes a folder chat, which only a folder.open from here makes" },
  "folder.resume": { send: "never", key: FOLDER, why: "cwd is a folder of this computer, stored a session made for it" },
  "elsewhere.list": ok("bot name only"),
  "routines.list": ok("bot name only"),
  "automations.list": ok("no fields"),
  "automations.add": ok("a name, schedule and prompt the person typed"),
  "automations.pause": ok("a job id the server listed"),
  "automations.resume": ok("a job id the server listed"),
  "automations.remove": ok("a job id the server listed"),
  "plugins.list": ok("bot name only"),
  "plugins.catalog": ok("a search the person typed"),
  "plugins.inspect": ok("a catalog name the server listed"),
  "plugins.install": ok("a catalog name and the sha the server returned"),
  "plugins.toggle": ok("a plugin key the server listed"),
  "plugins.update": ok("a plugin name the server listed"),
  "plugins.reload": ok("a plugin name the server listed"),
  "plugins.remove": ok("a plugin name the server listed"),
  "bots.restart": ok("bot name only"),
  "bots.restart_scope": ok("bot name only"),
  "peers.probe": { send: "never", key: HERE, why: "url is a loopback port and token of this computer; no peer links on a server" },
  "peers.attach": { send: "never", key: HERE, why: "host and url name a link this computer made; no peer links on a server" },
  "peers.detach": { send: "never", key: HERE, why: "no peer links on a server" },
  "apps.list": ok("bot name only"),
  "apps.install": ok("a catalog name the server listed"),
  "apps.login": ok("a catalog name the server listed"),
  "apps.remove": ok("a catalog name the server listed"),
  "models.options": ok("bot name only"),
  "bots.ready": ok("bot and provider ids"),
  "chat.set_model": ok("model, provider and level ids the server listed"),
  "bots.rename": ok("a name the person typed"),
  "bots.avatar": ok("bot name only (a read)"),
  "bots.set_avatar": { send: "without", field: "data", key: FILES, why: "data is a picture file of this computer; clear sends none" },
  "bots.info": ok("bot name only"),
  "bots.page": ok("bot name only"),
  "bots.platforms": ok("no path; fresh flag only"),
  "bots.templates": ok("no fields"),
  "bots.create": ok("a name the person typed"),
  "skills.list": ok("bot name only"),
  "commands.list": ok("bot name only"),
  "links.places": ok("bot name only"),
  "panel.terminal": ok("bot name only"),
  "panel.worktrees": ok("bot name only"),
  "panel.diff": ok("path is a worktree the server listed in panel.worktrees"),
  "media.read": ok("path is a file the bot named in its own answer, on the server"),
  "chat.attach": { send: "never", key: FILES, why: "data_base64 is a file of this computer" },
  "runs.list": ok("bot name only"),
  "runs.get": ok("a run id the server listed"),
  "runs.prs": ok("a run id the server listed"),
  "runs.cli": { send: "without", field: "cwd", key: HERE, why: "cwd is a SESSIONS folder of this computer; without it the server reads its own" },
  "cli.title": { send: "never", key: HERE, why: "session and cwd are a CLI conversation and folder of this computer" },
  "usage.read": ok("no fields"),
  "accounts.list": ok("no fields"),
  "accounts.add": ok("a CLI id and a label the person typed"),
  "accounts.set_active": ok("ids the server listed"),
  "accounts.remove": ok("ids the server listed"),
  "accounts.label": ok("a label the person typed"),
  "accounts.discard": ok("ids the server listed"),
  "thread.create": { send: "without", field: "cwd", key: FOLDER, why: "cwd would be a folder of this computer; a plain thread sends none" },
  "thread.list": ok("bot name only"),
  "thread.open": ok("a thread id the server listed"),
  "thread.remove": ok("a thread id the server listed"),
  "thread.prs": ok("a thread id the server listed"),
  "runs.node_session": ok("run, node or ref ids the server's own reads named"),
};

const given = (v: unknown) => v !== undefined && v !== null && v !== "";

/** The rule for `op` (an op not in the table has none, and is refused on a server). */
export const ruleOf = (op: string): OpRule | undefined => (Object.prototype.hasOwnProperty.call(REMOTE_OPS, op) ? REMOTE_OPS[op as PageOp] : undefined);

/** Whether `op` could be refused on a server: the client waits for the mode before sending such an op. */
export const mayRefuse = (op: string): boolean => ruleOf(op)?.send !== "always";

/** On a server: the reason `op` with `params` is not sent, or null when it goes. Local mode never asks. */
export function remoteRefusal(op: string, params: Record<string, unknown> | undefined): Key | null {
  const r = ruleOf(op);
  if (!r) return HERE;
  if (r.send === "always") return null;
  if (r.send === "never") return r.key;
  return given(params?.[r.field]) ? r.key : null;
}
