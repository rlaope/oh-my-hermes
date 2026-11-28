// A node's (or a subagent's) session as the bridge reads it (`runs.node_session`), and the pure mapping of it onto
// our own chat's pieces: right bubbles for what the parent said, left bubbles for the child's words, step rows for
// its tool calls (grouped between bubbles, in order), subagent rows for its own children. No thinking text ever
// reaches here (the bridge never reads it).
import type { Step, SubagentRow } from "../state/store";
import { t } from "../i18n";

export type SessionItem =
  | { type: "user"; text: string; ts?: number | null }
  | { type: "assistant"; text: string; ts?: number | null }
  | { type: "step"; tool: string; input: string; result: string; ok: boolean; ts?: number | null }
  /** What happened to the session, not anyone's words (bridge `_claude_items`): the person interrupted it, the
   *  harness compacted the conversation, or an API call failed (its own short text, HTTP status and retry). */
  | { type: "status"; code: string; text?: string; status?: number; retry?: number; retries?: number; ts?: number | null }
  | {
      type: "child";
      ref: string;
      kind: string;
      goal: string;
      state: string;
      summary?: string;
      model?: string;
      provider?: string;
      started?: number | null;
      ended?: number | null;
    };

export interface NodeSession {
  kind: string;
  ref?: string;
  prompt: string;
  steps: { tool: string; input: string; result: string; ok: boolean }[];
  answer: string;
  children: Extract<SessionItem, { type: "child" }>[];
  items: SessionItem[];
  model?: string;
  provider?: string;
  /** The parent's name (the bot's display name): who the right bubbles are. */
  parent?: string;
  title?: string;
  cwd?: string;
  started?: number | null;
  ended?: number | null;
  state?: string;
}

export interface NodeSessionResult {
  session: NodeSession | null;
  /** Why there is none: `no_cli_session` (the fanout's CLI session is not on this computer). */
  why?: string;
  executor?: string;
}

/** The shell commands of a current Codex `exec` step, whose input is JavaScript (`const r = await
 *  tools.exec_command({cmd: "…"})`, several in a `Promise.all`): each `cmd:` followed by a quoted string (`"`, `'` or a
 *  backtick), its escapes decoded. A template's `${…}` stays as written. Empty when the code names no command. */
export function codexExecCommands(src: string): string[] {
  const out: string[] = [];
  const re = /\bcmd\s*:\s*(["'`])/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(src))) {
    const quote = m[1];
    let i = re.lastIndex;
    let cmd = "";
    let closed = false;
    while (i < src.length) {
      const c = src[i];
      if (c === quote) {
        closed = true;
        i += 1;
        break;
      }
      if (c === "\\" && i + 1 < src.length) {
        const e = src[i + 1];
        const hex = e === "u" ? /^[0-9a-fA-F]{4}/.exec(src.slice(i + 2)) : e === "x" ? /^[0-9a-fA-F]{2}/.exec(src.slice(i + 2)) : null;
        if (hex) {
          cmd += String.fromCharCode(parseInt(hex[0], 16));
          i += 2 + hex[0].length;
          continue;
        }
        cmd += ESC[e] ?? e;
        i += 2;
        continue;
      }
      cmd += c;
      i += 1;
    }
    if (!closed) break;
    re.lastIndex = i;
    if (cmd.trim()) out.push(cmd.trim());
  }
  return out;
}

const ESC: Record<string, string> = { n: "\n", t: "\t", r: "\r", b: "\b", f: "\f", v: "\v", "0": "\0" };

/** A Codex `exec` step's commands as its one line: the command, or "<first line of the first> + N more". */
function execLabel(cmds: string[]): string {
  const first = oneLine(cmds[0].split("\n")[0]);
  return cmds.length === 1 ? oneLine(cmds[0]) : t("harness.moreCommands", { first, n: cmds.length - 1 });
}

/** What a step's one-line detail shows: the command, path, query or goal out of its input, else its first line. A
 *  Codex `exec` step shows the commands its code runs. */
export function stepDetail(tool: string, input: string): string {
  if (tool === "exec") {
    const cmds = codexExecCommands(input);
    if (cmds.length) return execLabel(cmds);
  }
  let args: unknown = null;
  try {
    args = JSON.parse(input);
  } catch {
    /* plain text input (a Codex custom tool's script) */
  }
  if (args && typeof args === "object" && !Array.isArray(args)) {
    const a = args as Record<string, unknown>;
    for (const k of ["command", "cmd", "path", "file_path", "pattern", "query", "url", "goal", "description", "name", "code"]) {
      const v = a[k];
      if (typeof v === "string" && v.trim()) return oneLine(v);
      if (Array.isArray(v) && v.every((x) => typeof x === "string")) return oneLine(v.join(" "));
    }
    const first = Object.values(a).find((v) => typeof v === "string" && v.trim());
    if (typeof first === "string") return oneLine(first);
    return "";
  }
  return oneLine(input);
}

/** A tool result as a person reads it: a Hermes tool's `{"output": …}` / `{"content": …}` JSON as its text (with a
 *  non-zero exit code after it), other JSON pretty-printed, plain text as it came. */
export function resultText(result: string): string {
  let v: unknown = null;
  try {
    v = JSON.parse(result);
  } catch {
    return result;
  }
  if (v && typeof v === "object" && !Array.isArray(v)) {
    const o = v as Record<string, unknown>;
    const body = typeof o.output === "string" ? o.output : typeof o.content === "string" ? o.content : null;
    if (body !== null) {
      const code = typeof o.exit_code === "number" && o.exit_code !== 0 ? `\n(exit ${o.exit_code})` : "";
      const err = typeof o.error === "string" && o.error ? `\n${o.error}` : "";
      return `${body}${code}${err}`;
    }
  }
  return JSON.stringify(v, null, 2);
}

const oneLine = (s: string, n = 160) => {
  const t = s.replace(/\s+/g, " ").trim();
  return t.length <= n ? t : `${t.slice(0, n - 1)}…`;
};

/** Claude Code / Codex tool names onto the verbs our activity rows already have. */
const TOOL_ALIAS: Record<string, string> = {
  Bash: "terminal",
  bash: "terminal",
  shell: "terminal",
  exec_command: "terminal",
  exec: "terminal",
  local_shell: "terminal",
  Read: "read_file",
  Grep: "search_files",
  Glob: "search_files",
  Edit: "patch",
  MultiEdit: "patch",
  Write: "write_file",
  apply_patch: "patch",
  WebSearch: "web_search",
  WebFetch: "web_extract",
  Agent: "delegate_task",
  Task: "delegate_task",
  spawn_agent: "delegate_task",
};

export type ChatPiece =
  | { kind: "user"; key: string; text: string }
  | { kind: "assistant"; key: string; text: string; last: boolean }
  | { kind: "steps"; key: string; steps: (Step & { input: string; result: string })[] }
  | { kind: "child"; key: string; sub: SubagentRow; ref: string; childKind: string; provider?: string }
  | { kind: "status"; key: string; code: string; text: string };

/** A status item as its one quiet line: "Interrupted", "Conversation compacted", "API error 529 · retry 3/10 ·
 *  Overloaded". An unknown code shows its own text, or nothing. */
export function statusLine(it: Extract<SessionItem, { type: "status" }>): string {
  if (it.code === "interrupted") return t("harness.status.interrupted");
  if (it.code === "compacted") return t("harness.status.compacted");
  if (it.code !== "api_error") return it.text ?? "";
  const head = it.status ? `${t("harness.status.apiError")} ${it.status}` : t("harness.status.apiError");
  const retry = it.retry && it.retries ? t("harness.status.retry", { n: it.retry, max: it.retries }) : "";
  return [head, retry, it.text ?? ""].filter(Boolean).join(" · ");
}

/** The input is `{"command": <the row's own text>}` and nothing more. */
function onlyCommand(input: string, detail: string): boolean {
  try {
    const a = JSON.parse(input) as unknown;
    if (!a || typeof a !== "object" || Array.isArray(a)) return false;
    const keys = Object.keys(a);
    const c = (a as Record<string, unknown>).command ?? (a as Record<string, unknown>).cmd;
    return keys.length === 1 && typeof c === "string" && !c.includes("\n") && c.trim() === detail;
  } catch {
    return false;
  }
}

/** The session's items as chat pieces, in order: consecutive tool calls share one step block. */
export function chatPieces(s: Pick<NodeSession, "items">): ChatPiece[] {
  const out: ChatPiece[] = [];
  const items = s.items ?? [];
  const lastAnswer = items.map((i) => i.type).lastIndexOf("assistant");
  items.forEach((it, i) => {
    const key = `${i}`;
    if (it.type === "user") out.push({ kind: "user", key, text: it.text });
    else if (it.type === "assistant") out.push({ kind: "assistant", key, text: it.text, last: i === lastAnswer });
    else if (it.type === "step") {
      const at = (it.ts ?? 0) * 1000;
      const next = items.slice(i + 1).find((x) => "ts" in x && x.ts);
      const end = next && "ts" in next && next.ts ? next.ts * 1000 : at;
      const detail = stepDetail(it.tool, it.input);
      // a Codex exec step reads as the shell step it is: its box shows the commands, not the code around them
      const cmds = it.tool === "exec" ? codexExecCommands(it.input) : [];
      const shown = cmds.length === 1 && !cmds[0].includes("\n") ? "" : cmds.length ? cmds.join("\n") : it.input;
      const step = {
        id: `s${i}`,
        name: TOOL_ALIAS[it.tool] ?? it.tool,
        detail,
        startedAt: at,
        endedAt: Math.max(at, end),
        // no later timestamp to end it: its length is unknown, so it shows none (never "0.0s")
        ...(next && at ? {} : { untimed: true }),
        ok: it.ok,
        // a single shell command already reads in full on the "Ran" row: its box shows only the result
        input: cmds.length ? shown : onlyCommand(it.input, detail) ? "" : it.input,
        result: resultText(it.result),
      };
      const prev = out[out.length - 1];
      if (prev?.kind === "steps") prev.steps.push(step);
      else out.push({ kind: "steps", key, steps: [step] });
    } else if (it.type === "status") {
      const text = statusLine(it);
      if (text) out.push({ kind: "status", key, code: it.code, text });
    } else if (it.type === "child") {
      const started = (it.started ?? 0) * 1000;
      const ended = it.ended ? it.ended * 1000 : undefined;
      const state = (["done", "failed", "cancelled", "running"].includes(it.state) ? it.state : "done") as SubagentRow["state"];
      out.push({
        kind: "child",
        key,
        ref: it.ref,
        childKind: it.kind,
        provider: it.provider,
        sub: {
          id: it.ref,
          index: i,
          goal: it.goal,
          model: it.model || undefined,
          agent: it.kind === "hermes" ? undefined : it.kind,
          state,
          summary: it.summary || undefined,
          startedAt: started,
          endedAt: ended,
          ...(ended !== undefined && started ? { seconds: Math.round((ended - started) / 1000) } : {}),
        },
      });
    }
  });
  return out;
}
