// Where session processes run. In the desktop app: the Tauri shell, which starts an allow-listed agent
// in a pseudo-terminal (src-tauri/src/sessions.rs) or in its structured chat mode on pipes
// (src-tauri/src/agent_chat.rs). In a plain browser (dev, e2e against the mock bridge) there is no shell,
// so a mock host echoes terminal typing and a mock agent answers chats with the same events.
import { AGENTS, agentDef, type AgentId, type AgentInfo } from "./agents";
import type { ApprovalChoice, ClarifyAnswers } from "../lib/protocol";
import { t } from "../i18n";

/** What the person did in a chat. Mirrors `Input` in src-tauri/src/agent_chat.rs. `images`: saved copies
 *  (`saveFile`) of attached pictures, for the agent's own image input. */
export type ChatInput =
  | { kind: "send"; text: string; images?: string[] }
  | { kind: "interrupt" }
  | { kind: "approve"; request_id: string; choice: ApprovalChoice }
  | { kind: "clarify"; request_id: string; answer: string | ClarifyAnswers }
  | { kind: "model"; model: string };

/** An event from a chat agent: the bot chat's events (`turn.start`, `tool.start`, `delta`, `message`,
 *  `approval.request`, `turn.end`, …) plus `session.info`, `session.models`, `session.error` and, once,
 *  `exit`. */
export type ChatEvent = { event: string; [k: string]: unknown };

export interface SessionHost {
  readonly kind: "tauri" | "mock";
  /** Stop anything an earlier page load left running (a webview reload keeps the shell alive). */
  reset(): Promise<void>;
  agents(): Promise<AgentInfo[]>;
  home(): Promise<string>;
  /** Native folder picker; null when the person cancels. */
  pickFolder(defaultPath: string): Promise<string | null>;
  /** Start `agent` in `cwd` in a terminal. Only the agent id goes to the shell: never a command line.
   *  `resume` is a Claude Code session id (the terminal view of a chat); the shell checks it is a UUID. `account`
   *  names the Settings › Accounts login it runs as (the one it ran with, after a restart); none = the one picked
   *  for new sessions. */
  start(
    agent: AgentId,
    cwd: string,
    cols: number,
    rows: number,
    onData: (data: Uint8Array | string) => void,
    onExit: (code: number | null) => void,
    resume?: string,
    account?: string,
  ): Promise<number>;
  write(id: number, data: string): Promise<void>;
  resize(id: number, cols: number, rows: number): Promise<void>;
  close(id: number): Promise<void>;
  /** Start `agent` in its chat mode in `cwd` (`resume`: a Claude Code or OmO session id or a Codex thread id to continue;
   *  `account`: as for `start`). */
  chatStart(agent: AgentId, cwd: string, onEvent: (ev: ChatEvent) => void, resume?: string, account?: string): Promise<number>;
  chatInput(id: number, input: ChatInput): Promise<void>;
  chatClose(id: number): Promise<void>;
  /** Save a file the person attached in session `session` under omher's own folder
   *  (`~/.omher/session-files/<session>/`); the saved copy's absolute path. */
  saveFile(session: string, name: string, data: Uint8Array): Promise<string>;
  /** The bytes of a file `saveFile` saved (a sent bubble's picture after a restart). */
  readFile(path: string): Promise<Uint8Array>;
  /** Remove session `session`'s saved files. */
  removeFiles(session: string): Promise<void>;
  /** Remove the saved files of every session not in `keep`. */
  pruneFiles(keep: string[]): Promise<void>;
}

// ---- Tauri ----------------------------------------------------------------------------------

export class TauriHost implements SessionHost {
  readonly kind = "tauri" as const;
  private async core() {
    return import("@tauri-apps/api/core");
  }
  async reset() {
    const { invoke } = await this.core();
    await Promise.all([invoke("session_close_all"), invoke("chat_close_all")]);
  }
  async agents() {
    const { invoke } = await this.core();
    return invoke<AgentInfo[]>("sessions_agents");
  }
  async home() {
    const { homeDir } = await import("@tauri-apps/api/path");
    return homeDir();
  }
  async pickFolder(defaultPath: string) {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const r = await open({ directory: true, multiple: false, defaultPath, title: t("ss.pickFolder") });
    return typeof r === "string" ? r : null;
  }
  async start(agent: AgentId, cwd: string, cols: number, rows: number, onData: (d: Uint8Array) => void, onExit: (c: number | null) => void, resume?: string, account?: string) {
    const { invoke, Channel } = await this.core();
    const data = new Channel<ArrayBuffer>();
    data.onmessage = (b) => onData(new Uint8Array(b));
    const exit = new Channel<number | null>();
    exit.onmessage = (c) => onExit(c);
    return invoke<number>("session_start", { agent, cwd, resume: resume ?? null, account: account ?? null, cols, rows, onData: data, onExit: exit });
  }
  async chatStart(agent: AgentId, cwd: string, onEvent: (ev: ChatEvent) => void, resume?: string, account?: string) {
    const { invoke, Channel } = await this.core();
    const ch = new Channel<ChatEvent>();
    ch.onmessage = (ev) => onEvent(ev);
    return invoke<number>("chat_start", { agent, cwd, resume: resume ?? null, account: account ?? null, onEvent: ch });
  }
  async chatInput(id: number, input: ChatInput) {
    const { invoke } = await this.core();
    await invoke("chat_input", { id, input });
  }
  async chatClose(id: number) {
    const { invoke } = await this.core();
    await invoke("chat_close", { id });
  }
  async saveFile(session: string, name: string, data: Uint8Array) {
    const { invoke } = await this.core();
    // the bytes go raw (no JSON array of numbers); the name rides in a header
    return invoke<string>("session_file_save", data, { headers: { "x-session": session, "x-name": encodeURIComponent(name) } });
  }
  async readFile(path: string) {
    const { invoke } = await this.core();
    return new Uint8Array(await invoke<ArrayBuffer>("session_file_read", { path }));
  }
  async removeFiles(session: string) {
    const { invoke } = await this.core();
    await invoke("session_files_remove", { session });
  }
  async pruneFiles(keep: string[]) {
    const { invoke } = await this.core();
    await invoke("session_files_prune", { keep });
  }
  async write(id: number, data: string) {
    const { invoke } = await this.core();
    await invoke("session_write", { id, data });
  }
  async resize(id: number, cols: number, rows: number) {
    const { invoke } = await this.core();
    await invoke("session_resize", { id, cols, rows });
  }
  async close(id: number) {
    const { invoke } = await this.core();
    await invoke("session_close", { id });
  }
}

// ---- mock (browser, e2e) --------------------------------------------------------------------

export interface MockCall {
  op: "reset" | "start" | "write" | "resize" | "close" | "chat.start" | "chat.input" | "chat.close" | "file.save" | "file.remove" | "file.prune";
  id?: number;
  agent?: string;
  cwd?: string;
  data?: string;
  cols?: number;
  rows?: number;
  resume?: string;
  account?: string;
  input?: ChatInput;
  session?: string;
  name?: string;
  size?: number;
  path?: string;
  keep?: string[];
}

const BANNER: Record<AgentId, string> = {
  claude: "\x1b[38;2;217;119;87m✻\x1b[0m \x1b[1mClaude Code\x1b[0m \x1b[2m(mock)\x1b[0m",
  codex: "\x1b[1m>_ Codex\x1b[0m \x1b[2m(mock)\x1b[0m",
  omo: "\x1b[1mOmO\x1b[0m \x1b[2m(mock)\x1b[0m",
  dsh: "\x1b[1mDeepSeek Harness\x1b[0m \x1b[2m(mock)\x1b[0m",
  omh: "\x1b[38;2;211;60;141m◆\x1b[0m \x1b[1moh-my-hermes\x1b[0m \x1b[2m(mock)\x1b[0m",
  pi: "\x1b[1mπ pi\x1b[0m \x1b[2m(mock)\x1b[0m",
  omp: "\x1b[1mπ oh-my-pi\x1b[0m \x1b[2m(mock)\x1b[0m",
  grok: "\x1b[1m𝕏 Grok\x1b[0m \x1b[2m(mock)\x1b[0m",
};
const PROMPT = "\x1b[2m›\x1b[0m ";

type MockGlobals = {
  __omherPickFolder?: string | null;
  __omherSessionCalls?: MockCall[];
  __omherMockAgents?: AgentId[];
  /** e2e: the next file saves fail with this message */
  __omherFileSaveError?: string;
  /** e2e: these agents are an old version that never answers in chat mode (the shell's start deadline ends them) */
  __omherMockNoChat?: AgentId[];
  /** e2e: the Codex thread a chat resumes is gone (deleted or archived): the shell starts a new one */
  __omherMockGoneThreads?: boolean;
};

/** Echoes typing, answers each line, ends on `exit` or Ctrl+D. Installed: claude, codex, omh. */
export class MockHost implements SessionHost {
  readonly kind = "mock" as const;
  private next = 0;
  private live = new Map<number, { line: string; out: (d: string) => void; exit: (c: number | null) => void }>();
  constructor(private g: MockGlobals = globalThis as MockGlobals) {}

  private log(c: MockCall) {
    (this.g.__omherSessionCalls ??= []).push(c);
  }
  async reset() {
    this.log({ op: "reset" });
    this.live.clear();
    for (const c of this.chats.values()) c.stop();
    this.chats.clear();
  }
  async agents(): Promise<AgentInfo[]> {
    const installed = this.g.__omherMockAgents ?? ["claude", "codex", "omh"];
    return AGENTS.map((a) => ({ id: a.id, label: a.label, mode: a.mode, path: installed.includes(a.id) ? `/usr/local/bin/${a.program}` : null }));
  }
  async home() {
    return "/Users/you";
  }
  async pickFolder(defaultPath: string) {
    const v = this.g.__omherPickFolder;
    return v === undefined ? defaultPath : v;
  }
  async start(agent: AgentId, cwd: string, cols: number, rows: number, onData: (d: string) => void, onExit: (c: number | null) => void, resume?: string, account?: string) {
    const id = ++this.next;
    this.log({ op: "start", id, agent, cwd, cols, rows, ...(resume ? { resume } : {}), ...(account ? { account } : {}) });
    this.live.set(id, { line: "", out: onData, exit: onExit });
    setTimeout(() => {
      onData(`${BANNER[agent]}\r\n\x1b[2m  ${agentDef(agent).program} in ${cwd}\x1b[0m\r\n\r\n${PROMPT}`);
    }, 30);
    return id;
  }
  async write(id: number, data: string) {
    this.log({ op: "write", id, data });
    const s = this.live.get(id);
    if (!s) throw new Error("no such session");
    for (const ch of data) {
      if (ch === "\r") {
        const line = s.line.trim();
        s.line = "";
        if (line === "exit") {
          s.out("\r\n");
          this.live.delete(id);
          setTimeout(() => s.exit(0), 10);
          return;
        }
        s.out(line ? `\r\n\x1b[2m(mock) you said:\x1b[0m ${line}\r\n${PROMPT}` : `\r\n${PROMPT}`);
      } else if (ch === "\x03") {
        s.line = "";
        s.out(`^C\r\n${PROMPT}`);
      } else if (ch === "\x04") {
        this.live.delete(id);
        setTimeout(() => s.exit(0), 10);
        return;
      } else if (ch === "\x7f") {
        if (s.line) {
          s.line = s.line.slice(0, -1);
          s.out("\b \b");
        }
      } else if (ch >= " ") {
        s.line += ch;
        s.out(ch);
      }
    }
  }
  async resize(id: number, cols: number, rows: number) {
    this.log({ op: "resize", id, cols, rows });
  }
  async close(id: number) {
    this.log({ op: "close", id });
    this.live.delete(id);
  }

  // ---- chat: a scripted agent with the same events the Rust adapters emit -------------------
  private chats = new Map<number, MockChat>();
  async chatStart(agent: AgentId, cwd: string, onEvent: (ev: ChatEvent) => void, resume?: string, account?: string) {
    const id = ++this.next;
    this.log({ op: "chat.start", id, agent, cwd, ...(resume ? { resume } : {}), ...(account ? { account } : {}) });
    const c = new MockChat(agent, onEvent, resume, cwd, {
      noChat: !!this.g.__omherMockNoChat?.includes(agent),
      gone: agent === "codex" && !!resume && !!this.g.__omherMockGoneThreads,
    });
    this.chats.set(id, c);
    c.boot();
    return id;
  }
  async chatInput(id: number, input: ChatInput) {
    this.log({ op: "chat.input", id, input });
    const c = this.chats.get(id);
    if (!c) throw new Error("no such session");
    c.input(input);
  }
  async chatClose(id: number) {
    this.log({ op: "chat.close", id });
    this.chats.get(id)?.stop();
    this.chats.delete(id);
  }

  // ---- files: kept in memory under the same paths the shell would use ------------------------
  private files = new Map<string, Uint8Array>();
  async saveFile(session: string, name: string, data: Uint8Array) {
    if (this.g.__omherFileSaveError) throw new Error(this.g.__omherFileSaveError);
    const dir = `/Users/you/.omher/session-files/${session}/`;
    let n = 1;
    while (this.files.has(`${dir}${n}-${name}`)) n += 1;
    const path = `${dir}${n}-${name}`;
    this.files.set(path, data);
    this.log({ op: "file.save", session, name, size: data.length, path });
    return path;
  }
  async readFile(path: string) {
    const d = this.files.get(path);
    if (!d) throw new Error("not a file omher saved");
    return d;
  }
  async removeFiles(session: string) {
    this.log({ op: "file.remove", session });
    for (const k of [...this.files.keys()]) if (k.includes(`/session-files/${session}/`)) this.files.delete(k);
  }
  async pruneFiles(keep: string[]) {
    this.log({ op: "file.prune", keep });
  }
}

const MOCK_MODELS: Record<string, { id: string; label: string }[]> = {
  claude: [
    { id: "opus", label: "Opus 5.5" },
    { id: "sonnet", label: "Sonnet 5.5" },
    { id: "haiku", label: "Haiku 5.5" },
  ],
  codex: [
    { id: "gpt-6.1-sol", label: "GPT-6.1 Sol" },
    { id: "gpt-6.1-terra", label: "GPT-6.1 Terra" },
  ],
  pi: [{ id: "anthropic/claude-sonnet-5-5", label: "Claude Sonnet 5.5" }],
  omp: [{ id: "anthropic/claude-sonnet-5-5", label: "Claude Sonnet 5.5" }],
  omo: [{ id: "claude-fable-5-1", label: "Claude Fable 5.1" }],
};

/** One mock chat agent. `/approve` asks to run `rm -rf ./build`; `/slow` streams long enough to stop with
 *  Esc; `/exit` ends the program; `/title <name>` names the conversation as the agent; anything else gets a
 *  short answer after one tool step. `noChat`: an old version that never speaks its chat protocol, ended by the
 *  shell's start deadline (shortened here). `gone`: a Codex resume onto a thread that no longer exists. */
class MockChat {
  private timers: ReturnType<typeof setTimeout>[] = [];
  private turn = false;
  private seq = 0;
  private waiting: string | null = null;
  private model: string;
  /** a model picked while a turn ran (Claude Code): the next turn's init confirms it */
  private next = "";
  private session: string;
  private dead = false;
  constructor(
    private agent: AgentId,
    private emit: (ev: ChatEvent) => void,
    resume?: string,
    private cwd = "",
    private how: { noChat?: boolean; gone?: boolean } = {},
  ) {
    this.model = MOCK_MODELS[agent]?.[0]?.label ?? agentDef(agent).label;
    this.session = resume ?? `${agent}-mock-${Math.random().toString(16).slice(2, 10)}-0000-0000-000000000000`;
    if (agent === "claude" && !resume) this.session = "11111111-2222-4333-8444-555555555555";
    if (how.gone) this.session = `codex-mock-${Math.random().toString(16).slice(2, 10)}-0000-0000-000000000000`;
    // DeepSeek Harness names its session `session-<uuid>` and reports no model in its headless stream
    if (agent === "dsh") {
      if (!resume) this.session = "session-8c11e2bc-9f55-4bcb-a597-19ea472184e8";
      this.model = "";
    }
  }
  private at(ms: number, fn: () => void) {
    this.timers.push(setTimeout(fn, ms));
  }
  boot() {
    if (this.how.noChat) {
      // the shell's start deadline (agent_chat.rs START_DEADLINE): no protocol line came, so it ends the session
      const why = `${agentDef(this.agent).label} did not answer in chat mode; it may be an old version: update it, then Restart.`;
      this.timers.push(
        setTimeout(() => {
          this.dead = true;
          this.emit({ event: "session.error", kind: "no_chat_mode", message: why });
          if (this.turn) this.emit({ event: "turn.end", outcome: "error", error: why });
          this.turn = false;
          this.emit({ event: "exit", code: null, error: why });
        }, 600),
      );
      return;
    }
    this.at(20, () => {
      if (this.how.gone) this.emit({ event: "session.note", kind: "new_conversation", text: "The earlier Codex conversation was not found; a new one started." });
      this.emit({ event: "session.info", agent_session: this.session, ...(this.model ? { model: this.model } : {}) });
      this.emit({ event: "session.models", options: (MOCK_MODELS[this.agent] ?? []).map((m) => ({ ...m, detail: "" })) });
    });
  }
  stop() {
    this.timers.forEach(clearTimeout);
    this.timers = [];
  }
  private end(outcome: "done" | "interrupted" | "ended" | "error", error?: string) {
    if (!this.turn) return;
    this.stop();
    this.turn = false;
    this.waiting = null;
    this.emit({ event: "turn.end", outcome, ...(error ? { error } : {}) });
  }
  private say(text: string, at: number) {
    const parts = [text.slice(0, Math.ceil(text.length / 2)), text.slice(Math.ceil(text.length / 2))];
    this.at(at, () => this.emit({ event: "delta", text: parts[0] }));
    this.at(at + 120, () => this.emit({ event: "delta", text: parts[1] }));
    this.at(at + 240, () => this.emit({ event: "message", id: `m${++this.seq}`, text }));
  }
  input(i: ChatInput) {
    if (this.dead) throw new Error("the session has ended");
    if (i.kind === "send") {
      if (!this.turn) {
        this.turn = true;
        this.emit({ event: "turn.start" });
        if (this.next) {
          // the turn's init: it runs on the model picked during the last one
          this.model = this.next;
          this.next = "";
          this.emit({ event: "session.info", model: this.model, model_next: "" });
        }
      }
      if (this.how.noChat) return; // the old program reads it and says nothing
      const text = i.text.trim();
      if (text === "/exit") {
        this.at(30, () => {
          // a clean exit mid-turn, as the Rust watcher reports it (exit_turn_end)
          this.end("ended");
          this.emit({ event: "exit", code: 0, error: "" });
        });
        return;
      }
      if (text.startsWith("/approve")) {
        const rid = `req-${++this.seq}`;
        this.at(60, () => this.emit({ event: "tool.start", tool_id: "t-rm", name: "terminal", detail: "rm -rf ./build" }));
        this.at(140, () => {
          this.waiting = rid;
          this.emit({ event: "approval.request", request_id: rid, title: "Run this command?", command: "rm -rf ./build", cwd: this.cwd, choices: ["deny", "once", "session"] });
        });
        return;
      }
      if (text.startsWith("/ask")) {
        // the shapes the adapters emit for a question (Claude Code AskUserQuestion, a Codex question) and a file edit
        const rid = `ask-${++this.seq}`;
        this.at(60, () => {
          this.waiting = rid;
          this.emit({ event: "clarify.request", request_id: rid, question: "Which greeting should go in greet.txt?", choices: ["hello", "hi"] });
        });
        return;
      }
      if (text.startsWith("/bad")) {
        this.at(60, () => this.emit({ event: "tool.start", tool_id: "t-bad", name: "terminal", detail: "definitely-not-a-command-xyz --flag" }));
        this.at(140, () => this.emit({ event: "tool.end", tool_id: "t-bad", name: "", ok: false, ms: 20 }));
        this.say("Exit code: 127.", 200);
        this.at(600, () => this.end("done"));
        return;
      }
      if (text.startsWith("/title ")) {
        // the agent names the conversation (Claude Code session_title_changed, Codex thread/name/updated)
        const name = text.slice(7).trim();
        this.at(40, () => this.emit({ event: "session.info", title: name }));
        this.say("Named it.", 80);
        this.at(400, () => this.end("done"));
        return;
      }
      if (text.startsWith("/signedout")) {
        this.at(60, () => this.end("error", `${agentDef(this.agent).label} is not signed in. Sign in from Settings › Accounts, then Restart.`));
        return;
      }
      if (text === "/die") {
        // the program dies mid-turn with nothing more on its stdout (a crash before the shell saw the turn)
        this.at(60, () => this.emit({ event: "delta", text: "partial" }));
        this.at(120, () => {
          this.stop();
          this.turn = false;
          this.emit({ event: "exit", code: null, error: "" });
        });
        return;
      }
      if (text.endsWith("/late")) {
        // OmO (omo-1-plain.jsonl): the answer, the turn's end, then a status of its own (`setStatus`) after it
        this.say("ok", 60);
        this.at(400, () => {
          this.end("done"); // clears the pending timers: the late events are scheduled after it
          this.at(50, () => this.emit({ event: "status", text: "mem:khope-sionic-ai-d09472c9 9d ago (+1)" }));
          this.at(100, () => this.emit({ event: "thinking" }));
        });
        return;
      }
      if (text.startsWith("/slow")) {
        for (let k = 0; k < 40; k++) this.at(100 + k * 250, () => this.emit({ event: "delta", text: `line ${k + 1}\n` }));
        return;
      }
      this.at(60, () => this.emit({ event: "tool.start", tool_id: `t${this.seq}`, name: "read_file", detail: "README.md" }));
      this.at(300, () => this.emit({ event: "tool.end", tool_id: `t${this.seq}`, name: "", ok: true, ms: 240 }));
      const pics = i.images?.length ? ` (${i.images.length} picture${i.images.length > 1 ? "s" : ""})` : "";
      this.say(`(mock ${agentDef(this.agent).label}) You said: ${text}${pics}`, 360);
      this.at(800, () => this.end("done"));
    } else if (i.kind === "interrupt") {
      if (!this.turn) throw new Error("nothing is running");
      this.at(20, () => this.end("interrupted"));
    } else if (i.kind === "approve") {
      if (i.request_id !== this.waiting) throw new Error("no such request");
      this.waiting = null;
      if (i.choice === "deny") {
        this.at(40, () => this.emit({ event: "tool.end", tool_id: "t-rm", name: "", ok: false, ms: 0 }));
        this.say("Okay, I left the build folder alone.", 80);
        this.at(500, () => this.end("done"));
      } else {
        this.at(80, () => this.emit({ event: "tool.end", tool_id: "t-rm", name: "", ok: true, ms: 300 }));
        this.say(`Cleaned the build folder (${i.choice === "session" ? "allowed for this session" : "allowed once"}).`, 140);
        this.at(560, () => this.end("done"));
      }
    } else if (i.kind === "model") {
      const m = (MOCK_MODELS[this.agent] ?? []).find((x) => x.id === i.model);
      if (!m) throw new Error(`unknown model ${i.model}`);
      if (this.agent === "claude" && this.turn) {
        // Claude Code keeps the running turn on its model: the pick is for the next turn
        this.next = m.label === this.model ? "" : m.label;
        this.timers.push(setTimeout(() => this.emit({ event: "session.info", model_next: this.next }), 20));
        return;
      }
      this.model = m.label;
      this.at(20, () => this.emit({ event: "session.info", model: this.model }));
    } else if (i.kind === "clarify") {
      if (i.request_id !== this.waiting) throw new Error("no question is open");
      this.waiting = null;
      const answer = typeof i.answer === "string" ? i.answer : Object.values(i.answer).filter(Boolean).join(", ");
      this.at(40, () => this.emit({ event: "tool.start", tool_id: "t-w", name: "patch", detail: "greet.txt +1" }));
      this.at(120, () => this.emit({ event: "tool.end", tool_id: "t-w", name: "", ok: true, ms: 60 }));
      this.say(`Wrote ${answer} to greet.txt.`, 160);
      this.at(600, () => this.end("done"));
    } else {
      throw new Error("unknown input");
    }
  }
}

const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

let host: SessionHost | null = null;
export function getHost(): SessionHost {
  return (host ??= inTauri() ? new TauriHost() : new MockHost());
}
