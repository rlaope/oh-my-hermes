// A node's (or a subagent's) session as the bridge reads it (`runs.node_session`), and the pure mapping of it onto
// our own chat's pieces: right bubbles for what the parent said, left bubbles for the child's words, step rows for
// its tool calls (grouped between bubbles, in order), subagent rows for its own children. No thinking text ever
// reaches here (the bridge never reads it).
import type { Step, SubagentRow } from "../state/store";

export type SessionItem =
  | { type: "user"; text: string; ts?: number | null }
  | { type: "assistant"; text: string; ts?: number | null }
  | { type: "step"; tool: string; input: string; result: string; ok: boolean; ts?: number | null }
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

/** What a step's one-line detail shows: the command, path, query or goal out of its input, else its first line. */
export function stepDetail(tool: string, input: string): string {
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
  | { kind: "child"; key: string; sub: SubagentRow; ref: string; childKind: string; provider?: string };

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
      const step = {
        id: `s${i}`,
        name: TOOL_ALIAS[it.tool] ?? it.tool,
        detail: stepDetail(it.tool, it.input),
        startedAt: at,
        endedAt: Math.max(at, end),
        ok: it.ok,
        input: it.input,
        result: resultText(it.result),
      };
      const prev = out[out.length - 1];
      if (prev?.kind === "steps") prev.steps.push(step);
      else out.push({ kind: "steps", key, steps: [step] });
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
