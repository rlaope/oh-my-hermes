// Where session processes run. In the desktop app: the Tauri shell, which starts an allow-listed agent
// in a pseudo-terminal (src-tauri/src/sessions.rs) or in its structured chat mode on pipes
// (src-tauri/src/agent_chat.rs). In a plain browser (dev, e2e against the mock bridge) there is no shell,
// so a mock host echoes terminal typing and a mock agent answers chats with the same events.
import { AGENTS, acpRow, agentDef, HERMES_LABEL, type AcpRow, type AgentId, type AgentInfo } from "./agents";
import mockAcpAgents from "./mockAcpAgents.json";
import { botRefusal, mockCheck, mockNewId, type CustomEntry, type CustomList, type CustomPreview, type CustomWhy } from "./custom";
import type { ApprovalChoice, ClarifyAnswers } from "../lib/protocol";
import { t } from "../i18n";

/** What the person did in a chat. Mirrors `Input` in src-tauri/src/agent_chat.rs. `images`: saved copies
 *  (`saveFile`) of attached pictures, for the agent's own image input. */
export type ChatInput =
  | { kind: "send"; text: string; images?: string[]; /** the bubble's id: a queued message is reported by it */ id?: string }
  | { kind: "interrupt" }
  | { kind: "approve"; request_id: string; choice: ApprovalChoice }
  | { kind: "clarify"; request_id: string; answer: string | ClarifyAnswers }
  | { kind: "model"; model: string }
  /** the permission mode, one the shell offers for the agent (controls.ts MODES) */
  | { kind: "mode"; mode: string }
  /** reasoning effort, one of the levels the agent reported */
  | { kind: "effort"; effort: string }
  /** take back the last message, through the agent's own rewind (Claude Code and Codex) */
  | { kind: "rewind" };

/** An event from a chat agent: the bot chat's events (`turn.start`, `tool.start`, `delta`, `message`,
 *  `approval.request`, `turn.end`, …) plus `session.info`, `session.models`, `session.error` and, once,
 *  `exit`. */
export type ChatEvent = { event: string; [k: string]: unknown };

/** A conversation Claude Code or Codex keeps for a folder (src-tauri/src/past_chats.rs), listed read-only so it can be
 *  continued here. `at`: last change, seconds since the epoch. `named`: the title is a name, not the first words. */
export interface PastChat {
  agent: "claude" | "codex";
  id: string;
  cwd: string;
  title: string;
  named: boolean;
  at: number;
}

/** One message of such a conversation (what the person typed, or the agent's answer text). */
export interface PastMsg {
  role: "user" | "assistant";
  text: string;
  ts: number;
}

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
  /** The terminal has drawn `bytes` more of session `id`'s output. The shell stops reading the program while the
   *  page is behind and reads again as these come back, so every message handed to `onData` is acknowledged once,
   *  in order. Never waited for; a session that is gone takes none. */
  ack(id: number, bytes: number): void;
  resize(id: number, cols: number, rows: number): Promise<void>;
  close(id: number): Promise<void>;
  /** Start `agent` in its chat mode in `cwd` (`resume`: a Claude Code or OmO session id or a Codex thread id to continue;
   *  `account`: as for `start`; `session`: the SESSIONS id, whose attachment folder a Claude Code chat reads without a card). */
  chatStart(agent: AgentId, cwd: string, onEvent: (ev: ChatEvent) => void, resume?: string, account?: string, session?: string): Promise<number>;
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
  /** The git branch checked out in `cwd` (read from its `.git/HEAD`; no program runs), "" when it is not a
   *  repository, a short commit id when detached. */
  branch(cwd: string): Promise<string>;
  /** Show folder `cwd` in the file manager. */
  reveal(cwd: string): Promise<void>;
  /** Open the person's own system terminal in folder `cwd` (their shell; nothing typed into it). */
  openTerminal(cwd: string): Promise<void>;
  /** The recent conversations `agent` keeps for `cwds`, newest first (read-only). */
  pastChats(agent: "claude" | "codex", cwds: string[]): Promise<PastChat[]>;
  /** The last messages of `agent`'s conversation `id` in `cwd`. */
  pastMessages(agent: "claude" | "codex", id: string, cwd: string): Promise<PastMsg[]>;
  /** How many asks wait: a Dock / launcher count, or a dot on the Windows taskbar button. 0 clears it. */
  badge(count: number): Promise<void>;
  /** Settings › Agents: the person's own agents, read and checked by the shell from omher's own file, and the broken
   *  entries. */
  customList(): Promise<CustomList>;
  /** The confirm card for the Add agent form: the checked entry and the exact command omher will run. Writes nothing.
   *  A refusal rejects with `why:<code>`. */
  customPreview(label: string, program: string, args: string, install: string): Promise<CustomPreview>;
  /** The same card for a bot's `omher-agent` draft: the form's checks and stricter (no shell, interpreter or built-in
   *  program), the arguments as the draft's own list. Writes nothing. A refusal rejects with `why:<code>`. */
  customBotPreview(label: string, program: string, args: string[], install: string): Promise<CustomPreview>;
  /** The card's Add: the only call that writes an entry. */
  customConfirm(entry: CustomEntry): Promise<void>;
  /** The remove confirm: agent `id` leaves the file. */
  customRemove(id: string): Promise<void>;
}

// ---- Tauri ----------------------------------------------------------------------------------

export class TauriHost implements SessionHost {
  readonly kind = "tauri" as const;
  /** The shell's command bridge (a test stands in for it by overriding this). */
  protected async core(): Promise<Pick<typeof import("@tauri-apps/api/core"), "invoke" | "Channel">> {
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
  async chatStart(agent: AgentId, cwd: string, onEvent: (ev: ChatEvent) => void, resume?: string, account?: string, session?: string) {
    const { invoke, Channel } = await this.core();
    const ch = new Channel<ChatEvent>();
    ch.onmessage = (ev) => onEvent(ev);
    return invoke<number>("chat_start", { agent, cwd, resume: resume ?? null, account: account ?? null, session: session ?? null, onEvent: ch });
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
  async branch(cwd: string) {
    const { invoke } = await this.core();
    return invoke<string>("session_branch", { cwd });
  }
  async reveal(cwd: string) {
    const { invoke } = await this.core();
    await invoke("session_reveal", { cwd });
  }
  async openTerminal(cwd: string) {
    const { invoke } = await this.core();
    await invoke("session_open_terminal", { cwd });
  }
  async pastChats(agent: "claude" | "codex", cwds: string[]) {
    const { invoke } = await this.core();
    return invoke<PastChat[]>("past_chats_list", { agent, cwds });
  }
  async pastMessages(agent: "claude" | "codex", id: string, cwd: string) {
    const { invoke } = await this.core();
    return invoke<PastMsg[]>("past_chat_messages", { agent, id, cwd });
  }
  async badge(count: number) {
    const { invoke } = await this.core();
    await invoke("asks_badge", { count });
  }
  async customList() {
    const { invoke } = await this.core();
    return invoke<CustomList>("custom_agents_list");
  }
  async customPreview(label: string, program: string, args: string, install: string) {
    const { invoke } = await this.core();
    return invoke<CustomPreview>("custom_agent_preview", { label, program, args, install });
  }
  async customBotPreview(label: string, program: string, args: string[], install: string) {
    const { invoke } = await this.core();
    return invoke<CustomPreview>("custom_agent_bot_preview", { label, program, args, install });
  }
  async customConfirm(entry: CustomEntry) {
    const { invoke } = await this.core();
    await invoke("custom_agent_confirm", { entry });
  }
  async customRemove(id: string) {
    const { invoke } = await this.core();
    await invoke("custom_agent_remove", { id });
  }
  async write(id: number, data: string) {
    const { invoke } = await this.core();
    await invoke("session_write", { id, data });
  }
  /** Drawn bytes not yet sent to the shell, by session. */
  private drawn = new Map<number, number>();
  /** A send of `drawn` is waiting for the end of this task. */
  private sending = false;
  /** One `session_ack` per session for everything drawn in the same task: xterm runs the callbacks of a whole
   *  slice of its write queue (up to 12 ms of messages) in one task, so a flood costs one call per slice instead
   *  of one per message. A call that fails is not lost credit: its bytes go back into `drawn` and ride on the next
   *  acknowledgement (any session's), so the shell's count of what the page has drawn stays whole. */
  ack(id: number, bytes: number) {
    this.drawn.set(id, (this.drawn.get(id) ?? 0) + bytes);
    if (this.sending) return;
    this.sending = true;
    queueMicrotask(() => {
      this.sending = false;
      const all = [...this.drawn];
      this.drawn.clear();
      const keep = (sid: number, n: number) => void this.drawn.set(sid, (this.drawn.get(sid) ?? 0) + n);
      void this.core().then(
        ({ invoke }) => {
          for (const [sid, n] of all) void invoke("session_ack", { id: sid, bytes: n }).catch(() => keep(sid, n));
        },
        () => all.forEach(([sid, n]) => keep(sid, n)),
      );
    });
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
  op:
    | "reset"
    | "start"
    | "write"
    | "ack"
    | "resize"
    | "close"
    | "chat.start"
    | "chat.input"
    | "chat.close"
    | "file.save"
    | "file.remove"
    | "file.prune"
    | "reveal"
    | "terminal"
    | "custom.preview"
    | "custom.botPreview"
    | "custom.confirm"
    | "custom.remove";
  id?: number;
  /** ack: how many drawn bytes it acknowledges */
  bytes?: number;
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

const BANNER: Record<string, string> = {
  claude: "\x1b[38;2;217;119;87m✻\x1b[0m \x1b[1mClaude Code\x1b[0m \x1b[2m(mock)\x1b[0m",
  codex: "\x1b[1m>_ Codex\x1b[0m \x1b[2m(mock)\x1b[0m",
  omo: "\x1b[1mOmO\x1b[0m \x1b[2m(mock)\x1b[0m",
  dsh: "\x1b[1mDeepSeek Harness\x1b[0m \x1b[2m(mock)\x1b[0m",
  omh: "\x1b[38;2;211;60;141m◆\x1b[0m \x1b[1moh-my-hermes\x1b[0m \x1b[2m(mock)\x1b[0m",
  pi: "\x1b[1mπ pi\x1b[0m \x1b[2m(mock)\x1b[0m",
  omp: "\x1b[1mπ oh-my-pi\x1b[0m \x1b[2m(mock)\x1b[0m",
  grok: "\x1b[1m𝕏 Grok\x1b[0m \x1b[2m(mock)\x1b[0m",
  opencode: "\x1b[1mopencode\x1b[0m \x1b[2m(mock)\x1b[0m",
};
/** A generic ACP agent's banner: its program's name, as the built-ins without art show theirs. */
const banner = (agent: AgentId) => BANNER[agent] ?? `\x1b[1m${agentDef(agent).program}\x1b[0m \x1b[2m(mock)\x1b[0m`;

/** The shell's generic ACP agents as `sessions_agents` sends them (src-tauri/src/acp_agents.rs `ACP_LIST`; a Rust
 *  test keeps this copy equal), for the mock host only: a browser has no shell to ask. */
const MOCK_ACP: readonly AcpRow[] = mockAcpAgents;
const PROMPT = "\x1b[2m›\x1b[0m ";

/** One step of a mock terminal's output: a message handed to the terminal (`feed`), or its acknowledgement. */
export interface MockFlow {
  op: "feed" | "ack";
  id: number;
  bytes: number;
}

const utf8 = new TextEncoder();

/** One message of a mock program that prints fast: 64 KiB of 64-byte lines, the size the shell hands output on in
 *  (`COALESCE_BYTES` in src-tauri/src/sessions.rs). */
const FLOOD_MESSAGE = `${"build output ".repeat(5).slice(0, 62)}\r\n`.repeat(1024);

type MockGlobals = {
  __omherPickFolder?: string | null;
  __omherSessionCalls?: MockCall[];
  /** e2e: every message a mock terminal's program printed and every acknowledgement of one, in the order they happened */
  __omherSessionFlow?: MockFlow[];
  __omherMockAgents?: AgentId[];
  /** e2e: Hermes is here and `omh` is not (the oh-my-hermes row reads "Hermes" and opens a Hermes chat) */
  __omherMockNoOmh?: boolean;
  /** e2e: the next file saves fail with this message */
  __omherFileSaveError?: string;
  /** e2e: the branch of each folder (none = not a repository) */
  __omherBranches?: Record<string, string>;
  /** e2e: these agents are an old version that never answers in chat mode (the shell's start deadline ends them) */
  __omherMockNoChat?: AgentId[];
  /** ACP agents the mock host treats as signed in (the others of MOCK_SIGNED_OUT answer -32000). */
  __omherMockSignedIn?: AgentId[];
  /** e2e: the Codex thread a chat resumes is gone (deleted or archived): the shell starts a new one */
  __omherMockGoneThreads?: boolean;
  /** e2e: Codex's own config runs without approvals and with full disk access (its thread reports
   *  `approvalPolicy: never`, `sandbox: dangerFullAccess`, as codex-12-late-step-init.jsonl) */
  __omherMockCodexUnguarded?: boolean;
  /** e2e: the conversations Claude Code and Codex keep (none = the built-in ones) */
  __omherPastChats?: PastChat[];
  /** e2e: reads of those conversations, apart from the session calls (opening the + menu lists them) */
  __omherPastReads?: { op: "list" | "read"; agent: string; cwds?: string[]; id?: string; cwd?: string }[];
  /** e2e: the Dock / taskbar count omher last set */
  __omherBadge?: number;
  /** e2e: the mock's copy of omher's custom-agents file (`agents` of `~/.omher/custom-agents.json`, as written) */
  __omherCustomFile?: unknown[];
  /** e2e: programs the mock finds on the search path, bare name -> where (absolute paths: any of the values) */
  __omherMockPrograms?: Record<string, string>;
  /** e2e: custom agents the mock treats as signed out (the others answer) */
  __omherMockCustomSignedOut?: AgentId[];
};

/** The programs the mock host finds unless a test says otherwise. */
const MOCK_PROGRAMS: Record<string, string> = { "cursor-agent": "/opt/homebrew/bin/cursor-agent", "stub-acp": "/usr/local/bin/stub-acp" };

/** The mock's past conversations: two Claude Code and one Codex conversation in the e2e folders. */
const MOCK_PAST: PastChat[] = [
  { agent: "claude", id: "aaaaaaaa-1111-4222-8333-444444444444", cwd: "/Users/you/code/web-app", title: "Fix the login redirect", named: true, at: Date.now() / 1000 - 3_600 },
  { agent: "claude", id: "bbbbbbbb-1111-4222-8333-444444444444", cwd: "/Users/you/code/omher", title: "Remember the word MARIGOLD for later", named: false, at: Date.now() / 1000 - 3 * 86_400 },
  { agent: "codex", id: "01a1d060-4ab7-72b2-b02b-1dbee1d5f52c", cwd: "/Users/you/code/web-app", title: "Add a dark theme", named: true, at: Date.now() / 1000 - 600 },
];
const MOCK_PAST_MSGS: Record<string, PastMsg[]> = {
  "bbbbbbbb-1111-4222-8333-444444444444": [
    { role: "user", text: "Remember the word MARIGOLD for later", ts: Date.now() / 1000 - 3 * 86_400 },
    { role: "assistant", text: "Noted: MARIGOLD.", ts: Date.now() / 1000 - 3 * 86_400 + 5 },
  ],
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
    const noOmh = !!this.g.__omherMockNoOmh;
    const builtins: AgentInfo[] = AGENTS.map((a) =>
      a.id === "omh" && noOmh
        ? { id: a.id, label: HERMES_LABEL, mode: a.mode, path: "/Users/you/.hermes/hermes-agent/venv/bin/python", via: "hermes" as const }
        : { id: a.id, label: a.label, mode: a.mode, path: installed.includes(a.id) ? `/usr/local/bin/${a.program}` : null },
    );
    const acp: AgentInfo[] = MOCK_ACP.map((r) => ({ id: r.id, label: r.label, mode: "chat", path: installed.includes(r.id) ? `/usr/local/bin/${r.program}` : null, acp: r }));
    return [...builtins, ...acp, ...this.customInfos()];
  }

  // ---- the person's own agents: the shell's checks over the mock's file (custom_agents.rs) --------------------
  private programs() {
    return this.g.__omherMockPrograms ?? MOCK_PROGRAMS;
  }
  /** Where `program` is: an absolute path the mock knows, or a bare name it finds. */
  private findProgram(program: string): string | null {
    const p = this.programs();
    if (program.startsWith("/")) return Object.values(p).includes(program) ? program : null;
    return p[program] ?? null;
  }
  /** The file, read and checked as the shell reads it: the agents that may run and the broken entries. */
  private loadCustom(): { agents: CustomEntry[]; broken: { id: string; why: CustomWhy }[] } {
    const agents: CustomEntry[] = [];
    const broken: { id: string; why: CustomWhy }[] = [];
    for (const v of this.g.__omherCustomFile ?? []) {
      const raw = v && typeof v === "object" ? (v as Record<string, unknown>) : {};
      const id = typeof raw.id === "string" && /^[a-z0-9-]{1,64}$/.test(raw.id) ? raw.id : "";
      const why = mockCheck(v, (p) => Object.values(this.programs()).includes(p));
      if (why) broken.push({ id, why });
      else if (agents.some((a) => a.id === id)) broken.push({ id, why: "dup" });
      else agents.push({ ...(v as CustomEntry), install: (v as CustomEntry).install ?? "" });
    }
    return { agents, broken };
  }
  private customInfos(): AgentInfo[] {
    return this.loadCustom().agents.map((c) => ({
      id: c.id,
      label: c.label,
      mode: "chat" as const,
      path: this.findProgram(c.program),
      acp: { id: c.id, label: c.label, program: c.program, args: c.args, login: c.program, install: c.install, mark: "", continues: true, custom: true },
    }));
  }
  async customList(): Promise<CustomList> {
    return { agents: this.customInfos(), broken: this.loadCustom().broken };
  }
  async customPreview(label: string, program: string, args: string, install: string): Promise<CustomPreview> {
    this.log({ op: "custom.preview", name: label, path: program, data: args });
    const taken = (this.g.__omherCustomFile ?? []).map((v) => (v && typeof v === "object" ? String((v as { id?: unknown }).id ?? "") : "")).filter(Boolean);
    const entry: CustomEntry = { id: mockNewId(label.trim(), program.trim(), taken), label: label.trim(), program: program.trim(), args: args.split(/\s+/).filter(Boolean), install: install.trim() };
    const why = mockCheck(entry, (p) => Object.values(this.programs()).includes(p));
    if (why) throw new Error(`why:${why}`);
    if (taken.length >= 32) throw new Error("why:many");
    const found = this.findProgram(entry.program);
    return { entry, command: found ? [found, ...entry.args].join(" ") : null };
  }
  async customBotPreview(label: string, program: string, args: string[], install: string): Promise<CustomPreview> {
    this.log({ op: "custom.botPreview", name: label, path: program, data: args.join(" ") });
    const why = botRefusal(program);
    if (why) throw new Error(`why:${why}`);
    if (!args.every((a) => /^[A-Za-z0-9._=/:-]{1,64}$/.test(a))) throw new Error("why:args");
    return this.customPreview(label, program, args.join(" "), install);
  }
  async customConfirm(entry: CustomEntry) {
    this.log({ op: "custom.confirm", agent: entry.id });
    const why = mockCheck(entry, (p) => Object.values(this.programs()).includes(p));
    if (why) throw new Error(`why:${why}`);
    const file = this.g.__omherCustomFile ?? [];
    if (file.some((v) => (v as { id?: unknown })?.id === entry.id)) throw new Error("why:dup");
    this.g.__omherCustomFile = [...file, { ...entry }];
  }
  async customRemove(id: string) {
    this.log({ op: "custom.remove", agent: id });
    this.g.__omherCustomFile = (this.g.__omherCustomFile ?? []).filter((v) => (v as { id?: unknown })?.id !== id);
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
    const out = (d: string) => {
      (this.g.__omherSessionFlow ??= []).push({ op: "feed", id, bytes: utf8.encode(d).length });
      onData(d);
    };
    this.live.set(id, { line: "", out, exit: onExit });
    setTimeout(() => {
      out(`${banner(agent)}\r\n\x1b[2m  ${agentDef(agent).program} in ${cwd}\x1b[0m\r\n\r\n${PROMPT}`);
    }, 30);
    return id;
  }
  ack(id: number, bytes: number) {
    this.log({ op: "ack", id, bytes });
    (this.g.__omherSessionFlow ??= []).push({ op: "ack", id, bytes });
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
        // `after <ms> bell|osc9|progress` / `after <ms> exit [code]` / `after <ms> flood [MiB]`: the program rings
        // (BEL, or an OSC 9 message), reports progress (OSC 9;4, not a ring), ends, or prints a lot at once (1 MiB
        // unless told, as 64 KiB messages) later, as an agent does while the person looks elsewhere
        const later = /^after (\d+) (bell|osc9|progress|exit|flood)(?: (\d+))?$/.exec(line);
        if (later) {
          s.out(`\r\n${PROMPT}`);
          setTimeout(() => {
            if (this.live.get(id) !== s) return;
            if (later[2] === "bell") return s.out("\x07");
            if (later[2] === "osc9") return s.out("\x1b]9;Needs your approval\x07");
            if (later[2] === "progress") return s.out("\x1b]9;4;1;50\x07");
            if (later[2] === "flood") {
              for (let i = 0; i < Number(later[3] ?? 1) * 16; i++) s.out(FLOOD_MESSAGE);
              return;
            }
            this.live.delete(id);
            s.exit(Number(later[3] ?? 0));
          }, Number(later[1]));
          continue;
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
  async chatStart(agent: AgentId, cwd: string, onEvent: (ev: ChatEvent) => void, resume?: string, account?: string, session?: string) {
    const id = ++this.next;
    this.log({ op: "chat.start", id, agent, cwd, ...(resume ? { resume } : {}), ...(account ? { account } : {}), ...(session ? { session } : {}) });
    const c = new MockChat(agent, onEvent, resume, cwd, {
      noChat: !!this.g.__omherMockNoChat?.includes(agent),
      // the generic ACP agents are signed out on the mock host unless a test signs them in, as on a fresh Mac; a
      // person's own agent answers unless a test signs it out
      signedOut: acpRow(agent)?.custom ? !!this.g.__omherMockCustomSignedOut?.includes(agent) : !!acpRow(agent) && !this.g.__omherMockSignedIn?.includes(agent),
      gone: agent === "codex" && !!resume && !!this.g.__omherMockGoneThreads,
      unguarded: agent === "codex" && !!this.g.__omherMockCodexUnguarded,
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
  async branch(cwd: string) {
    const b = this.g.__omherBranches ?? { "/Users/you/code/omher": "feat/session-controls" };
    return b[cwd] ?? "";
  }
  async reveal(cwd: string) {
    this.log({ op: "reveal", cwd });
  }
  async openTerminal(cwd: string) {
    this.log({ op: "terminal", cwd });
  }
  async pastChats(agent: "claude" | "codex", cwds: string[]) {
    (this.g.__omherPastReads ??= []).push({ op: "list", agent, cwds });
    const all = this.g.__omherPastChats ?? MOCK_PAST;
    return all.filter((c) => c.agent === agent && cwds.includes(c.cwd)).sort((a, b) => b.at - a.at);
  }
  async pastMessages(agent: "claude" | "codex", id: string, cwd: string) {
    (this.g.__omherPastReads ??= []).push({ op: "read", agent, id, cwd });
    const c = (this.g.__omherPastChats ?? MOCK_PAST).find((x) => x.agent === agent && x.id === id && x.cwd === cwd);
    if (!c) throw new Error("no such conversation");
    return MOCK_PAST_MSGS[id] ?? [{ role: "user" as const, text: c.title, ts: c.at }];
  }
  async badge(count: number) {
    this.g.__omherBadge = count;
  }
}

const MOCK_MODELS: Record<string, { id: string; label: string; provider?: string }[]> = {
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
  // as real omo lists them on this Mac: many anthropic models, then two from another provider below the fold
  omo: [
    ...["Claude Fable 5.1", "Claude Opus 5", "Claude Opus 4.7", "Claude Sonnet 5.5", "Claude Sonnet 5", "Claude Haiku 5.5", "Claude Haiku 4.5", "Claude Opus 4.5", "Claude Sonnet 4.5", "Claude Opus 4.1", "Claude Sonnet 4", "Claude Opus 4", "Claude Haiku 4", "Claude 3.7 Sonnet"].map((label) => ({
      id: `anthropic/${label.toLowerCase().replace(/ /g, "-").replace(/\./g, "-")}`,
      label,
      provider: "anthropic",
    })),
    { id: "opengateway/gpt-6", label: "GPT-6 (gateway)", provider: "opengateway" },
    { id: "opengateway/gemini-4-carbon", label: "Gemini 4 Carbon (gateway)", provider: "opengateway" },
  ],
  opencode: [
    { id: "opencode/big-pickle", label: "OpenCode/Big Pickle" },
    { id: "opencode/beam-free", label: "OpenCode/Beam Free" },
  ],
};

/** The agents on the Agent Client Protocol adapter (OpenCode and the generic list): their cards offer Deny and Allow
 *  once only. */
const isAcp = (agent: AgentId) => agent === "opencode" || !!acpRow(agent);
/** A generic ACP agent's sign-in command, from its row (acp_chat.rs's `signed_out` names the same). */
const loginOf = (agent: AgentId) => acpRow(agent)?.login ?? "";

/** What each mock agent reports about its controls, as the real CLIs do (see agent_chat.rs). */
const MOCK_CONTROLS: Partial<Record<AgentId, { mode?: string; efforts: string[]; effort: string; commands: { name: string; description: string; hint: string; kind: "command" | "skill"; prefix: "/" | "$" }[]; max: number }>> = {
  claude: {
    mode: "default",
    efforts: ["low", "medium", "high", "xhigh", "max"],
    effort: "high",
    commands: [
      { name: "compact", description: "Free up context by summarizing the conversation so far", hint: "<instructions>", kind: "command", prefix: "/" },
      { name: "context", description: "Visualize current context usage", hint: "", kind: "command", prefix: "/" },
      { name: "init", description: "Initialize a new CLAUDE.md file with codebase documentation", hint: "", kind: "command", prefix: "/" },
      { name: "review", description: "Review a pull request", hint: "<pr>", kind: "command", prefix: "/" },
      { name: "archify", description: "Architecture diagrams as standalone HTML (user)", hint: "", kind: "skill", prefix: "/" },
      ...Array.from({ length: 60 }, (_, i) => ({ name: `skill-${String(i + 1).padStart(2, "0")}`, description: `Sample skill ${i + 1} (user)`, hint: "", kind: "skill" as const, prefix: "/" as const })),
    ],
    max: 1_000_000,
  },
  codex: {
    mode: "",
    efforts: ["low", "medium", "high", "xhigh", "max", "ultra"],
    effort: "medium",
    commands: [{ name: "review", description: "Review a change", hint: "", kind: "skill", prefix: "$" }],
    max: 258_400,
  },
  omo: {
    efforts: ["minimal", "low", "medium", "high", "xhigh", "max"],
    effort: "medium",
    commands: [
      { name: "todo", description: "Show or edit the todo list", hint: "", kind: "command", prefix: "/" },
      { name: "skill:hyperframes", description: "Make or edit a video", hint: "", kind: "skill", prefix: "$" },
    ],
    max: 1_000_000,
  },
};
const MOCK_MODES: Partial<Record<AgentId, string[]>> = { claude: ["default", "plan", "acceptEdits"], codex: ["read-only", "ask", "auto"] };

/** One mock chat agent. `/approve` asks to run `rm -rf ./build`; `/slow` streams long enough to stop with
 *  Esc; `/exit` ends the program; `/title <name>` names the conversation as the agent; anything else gets a
 *  short answer after one tool step. A message sent while a turn runs is queued and answered after it, as Claude
 *  Code and OmO do; Stop drops it. `noChat`: an old version that never speaks its chat protocol, ended by the
 *  shell's start deadline (shortened here). `gone`: a Codex resume onto a thread that no longer exists. */
/** The agents that can take a message back (their own rewind): Claude Code and Codex. */
const MOCK_REWINDS: AgentId[] = ["claude", "codex"];

/** A real two-file edit as the Claude adapter emitted it (claude-12-work.jsonl, paths made relative). */
const MOCK_WORK = {
  thinking: ["Three small steps: a docstring on `add`, a new `mul`, ", "then list the functions in README.md."],
  todo: ["Add docstring to add() in calc.py", "Add mul(a, b) function to calc.py", "Update README.md with function list"],
  edits: [
    {
      id: "e-1",
      detail: "calc.py +2 -1",
      file: { path: "calc.py", kind: "update", lines: ["@@ -1,4 +1,5 @@", " def add(a, b):", '+    """Return the sum of a and b."""', "     return a + b", " ", " "], added: 1, removed: 0 },
    },
    {
      id: "e-2",
      detail: "calc.py +5 -2",
      file: { path: "calc.py", kind: "update", lines: ["@@ -5,3 +5,7 @@", " def sub(a, b):", "     return a - b", "+", "+", "+def mul(a, b):", "+    return a * b"], added: 4, removed: 0 },
    },
    {
      id: "e-3",
      detail: "README.md +3 -1",
      file: { path: "README.md", kind: "update", lines: ["@@ -1,3 +1,5 @@", " # calc", " ", " Tiny math helpers.", "+", "+Functions: `add(a, b)`, `sub(a, b)`, `mul(a, b)`"], added: 2, removed: 0 },
    },
  ],
  answer: "Done. `add` has a docstring, `mul(a, b)` is in calc.py, and README.md lists the functions:\n\n```python\ndef mul(a, b):\n    return a * b\n```",
};

/** The plan Claude Code 2.1.323 wrote in plan mode (claude-14-plan-deny.jsonl), in English here. */
const MOCK_PLAN =
  "# Plan: add mul(a, b) to calc.py\n\n1. In `calc.py`, add `def mul(a, b): return a * b` below `sub`, two blank lines apart as the others are.\n2. In `README.md`, list the functions (`add`, `sub`, `mul`) under \"Tiny math helpers.\"\n\nCheck: `python3 -c \"from calc import mul; assert mul(3, 4) == 12\"`";

/** The change a Codex 0.167 sub-agent made (codex-15-sub-edit.jsonl), as the adapter's `diff` gives it. */
const MOCK_SUB_EDIT = [
  { path: "README.md", kind: "update" as const, lines: ["@@ -3 +3,3 @@", " Tiny math helpers.", "+", "+Functions: add, sub, mul"], added: 2, removed: 0 },
  { path: "calc.py", kind: "update" as const, lines: ["@@ -6 +6,5 @@", "     return a - b", "+", "+", "+def mul(a, b):", "+    return a * b"], added: 4, removed: 0 },
];

class MockChat {
  private timers: ReturnType<typeof setTimeout>[] = [];
  private turn = false;
  private seq = 0;
  private waiting: string | null = null;
  /** the open approval is a subagent's (/subask) */
  private subWaiting = false;
  /** the open approval is plan mode's plan (/plan) */
  private planAsk = false;
  /** the open approval is a background subagent's, asked after the turn ended (/lateask) */
  private lateAsk = false;
  /** "/subagents hold": the second subagent is still out */
  private holding = false;
  /** work Claude Code says still runs in the background (`background_tasks_changed`), and the background subagent
   *  among it (/lateask) */
  private bg = 0;
  private bgSub = false;
  private model: string;
  /** a model picked while a turn ran (Claude Code): the next turn's init confirms it */
  private next = "";
  private session: string;
  private used = 18_400;
  private queue: { text: string; id: string; images?: string[] }[] = [];
  /** "/stoplate": the command still runs after Stop and ends on its own later */
  private lateStep = "";
  private dead = false;
  /** messages this process took, for a rewind (Claude Code and Codex only) */
  private sent = 0;
  constructor(
    private agent: AgentId,
    private emit: (ev: ChatEvent) => void,
    resume?: string,
    private cwd = "",
    private how: { noChat?: boolean; gone?: boolean; unguarded?: boolean; signedOut?: boolean } = {},
  ) {
    this.model = MOCK_MODELS[agent]?.[0]?.label ?? agentDef(agent).label;
    this.session = resume ?? `${agent}-mock-${Math.random().toString(16).slice(2, 10)}-0000-0000-000000000000`;
    if (agent === "claude" && !resume) this.session = "11111111-2222-4333-8444-555555555555";
    if (agent === "opencode" && !resume) this.session = "ses_e34e28c01ffeKlpLA61p3XV1cy";
    // the id a real OmO 5.1.56 session reported (its subagents' records are keyed by it; mock.sessionRun agent omo)
    if (agent === "omo" && !resume) this.session = "01a1ce7b-1c30-7e45-8913-aa00b3b32296";
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
    if (this.how.signedOut) {
      // `session/new` answered -32000: acp_chat.rs says so once, with the row's sign-in command; omher ends it
      this.at(40, () => {
        const why = `${agentDef(this.agent).label} is not signed in. Run \`${loginOf(this.agent)}\` in a terminal and sign in.`;
        this.emit({ event: "session.error", kind: "signed_out", message: why, login: loginOf(this.agent) });
        if (this.turn) {
          this.turn = false;
          this.emit({ event: "turn.end", outcome: "error", error: why, signed_out: true, login: loginOf(this.agent) });
        }
        this.dead = true;
      });
      return;
    }
    this.at(20, () => {
      if (this.how.gone) this.emit({ event: "session.note", kind: "new_conversation", text: "The earlier Codex conversation was not found; a new one started." });
      const c = MOCK_CONTROLS[this.agent];
      this.emit({ event: "session.info", agent_session: this.session, ...(this.model ? { model: this.model } : {}), ...(c ? { effort: c.effort } : {}), ...(c?.mode !== undefined ? { mode: c.mode } : {}) });
      // the thread's own approval policy and sandbox, as the Codex adapter reports them
      if (this.agent === "codex")
        this.emit({ event: "session.info", ...(this.how.unguarded ? { approval: "never", sandbox: "dangerFullAccess" } : { approval: "untrusted", sandbox: "workspaceWrite" }) });
      this.emit({ event: "session.models", options: (MOCK_MODELS[this.agent] ?? []).map((m) => ({ ...m, detail: "" })) });
      if (c) {
        this.emit({ event: "session.efforts", levels: c.efforts });
        this.emit({ event: "session.commands", commands: c.commands });
        this.emit({ event: "session.usage", used: this.used, max: c.max });
      }
      // the agent's own commands and skills (ACP `available_commands_update`), as acp_chat.rs sends them
      if (this.agent === "opencode")
        this.emit({ event: "session.commands", commands: ["init", "review"].map((name) => ({ name, description: "", hint: "", kind: "command", prefix: "/" })) });
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
    const next = this.queue;
    this.queue = [];
    // Stop drops what waited (OmO clears its queue; Codex never recorded it)
    if (outcome === "interrupted") for (const q of next) this.emit({ event: "message.dropped", id: q.id });
    this.emit({ event: "turn.end", outcome, ...(error ? { error } : {}) });
    if (MOCK_REWINDS.includes(this.agent)) this.emit({ event: "session.info", rewind: this.sent > 0 });
    const c = MOCK_CONTROLS[this.agent];
    if (c) {
      this.used += 6_200;
      this.emit({ event: "session.usage", used: this.used, max: c.max });
    }
    // a finished turn takes what was sent during it as the next turn
    if (outcome === "done" && next.length) {
      const [first, ...rest] = next;
      this.queue = rest;
      this.at(80, () => {
        this.emit({ event: "message.taken", id: first.id });
        this.input({ kind: "send", text: first.text, images: first.images });
      });
    }
  }
  private background(n: number) {
    this.bg = n;
    this.emit({ event: "session.info", background: n });
  }
  private say(text: string, at: number) {
    const parts = [text.slice(0, Math.ceil(text.length / 2)), text.slice(Math.ceil(text.length / 2))];
    this.at(at, () => this.emit({ event: "delta", text: parts[0] }));
    this.at(at + 120, () => this.emit({ event: "delta", text: parts[1] }));
    this.at(at + 240, () => this.emit({ event: "message", id: `m${++this.seq}`, text }));
  }
  input(i: ChatInput) {
    if (this.dead) throw new Error("the session has ended");
    if (i.kind === "send" && this.turn && i.id) {
      // sent while a turn runs: it waits until the agent takes it
      this.queue.push({ text: i.text, id: i.id, images: i.images });
      this.emit({ event: "message.queued", id: i.id });
      return;
    }
    if (i.kind === "mode") {
      if (!(MOCK_MODES[this.agent] ?? []).includes(i.mode)) throw new Error(`not a mode omher offers: ${i.mode}`);
      this.at(20, () => this.emit({ event: "session.info", mode: i.mode }));
      return;
    }
    if (i.kind === "effort") {
      if (!(MOCK_CONTROLS[this.agent]?.efforts ?? []).includes(i.effort)) throw new Error(`unknown effort ${i.effort}`);
      this.at(20, () => this.emit({ event: "session.info", effort: i.effort }));
      return;
    }
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
      if (text === "/quit") {
        // codex-15 (Codex 0.167): the person's own config makes Codex print a warning at start; the program then
        // closes in order (code 0). Before omher 0.2.7 the shell sent that warning as the exit's reason.
        this.at(30, () => {
          this.end("ended");
          this.dead = true;
          this.emit({ event: "exit", code: 0, error: "user (~/.codex/config.toml): `mcp_servers.playwright.type` is ignored." });
        });
        return;
      }
      if (text.startsWith("/plan")) {
        // claude-14-plan-deny.jsonl as the Claude adapter emits it: plan mode's end (ExitPlanMode) with the plan the
        // agent wrote; Claude Code offers no rule to keep for it, so Deny and Allow once only
        const rid = `req-${++this.seq}`;
        this.at(60, () => {
          this.waiting = rid;
          this.planAsk = true;
          this.emit({ event: "approval.request", request_id: rid, title: "Start working on this plan?", command: "", cwd: this.cwd, choices: ["deny", "once"], plan: MOCK_PLAN });
        });
        return;
      }
      if (text.startsWith("/subedit")) {
        // codex-15-sub-edit.jsonl as the Codex adapter emits it: the edit runs in a sub-agent's own thread, whose file
        // change carries its patch; the main thread edits nothing
        const sub = (extra: Record<string, unknown>) =>
          this.emit({ event: "subagent", id: "thr-sub", agent: this.agent, name: "add mul", goal: "", delegation: "codex-turn-1", index: 0, count: 1, state: "running", model: "gpt-6.1-sol", ...extra });
        const step = MOCK_SUB_EDIT.map((f) => `${f.path} +${f.added}`).join(", ");
        this.at(40, () => sub({}));
        this.at(120, () => sub({ tool: "terminal", step: "cat calc.py README.md" }));
        this.at(200, () => sub({ tool: "patch", step, diff: MOCK_SUB_EDIT }));
        this.at(260, () => sub({ tool: "patch", step, diff: MOCK_SUB_EDIT }));
        this.at(400, () => sub({ state: "done", summary: "Added mul(a, b) to calc.py and listed the functions in README.md.", seconds: 18.2 }));
        this.say("The sub-agent added mul(a, b) to calc.py and listed the functions in README.md.", 480);
        this.at(800, () => this.end("done"));
        return;
      }
      if (text.startsWith("/approve")) {
        const rid = `req-${++this.seq}`;
        this.at(60, () => this.emit({ event: "tool.start", tool_id: "t-rm", name: "terminal", detail: "rm -rf ./build" }));
        this.at(140, () => {
          this.waiting = rid;
          // an ACP agent (OpenCode) offers Deny and Allow once only: its "always" is a saved project rule
          const choices = isAcp(this.agent) ? ["deny", "once"] : ["deny", "once", "session"];
          this.emit({ event: "approval.request", request_id: rid, title: "Run this command?", command: "rm -rf ./build", cwd: this.cwd, choices });
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
      if (text.startsWith("/batch")) {
        // omo-13-batch.jsonl as the Pi adapter emits it (OmO 5.1.56): one foreground `task` with two subagents and
        // a todo list; the task result names no answer, so each row ends with what OmO's own record of that task id
        // says (answer, model, its own time), the record Plans reads too
        const d = "pi-toolu_batch";
        const sub = (i: number, extra: Record<string, unknown>) =>
          this.emit({
            event: "subagent", id: `toolu_batch:${i}`, agent: this.agent, name: i ? "helper-b-line-count" : "helper-a-first-line",
            goal: i ? "helper-b-line-count: count lines of a.txt and reply LINE_COUNT: <number>" : "helper-a-first-line: read a.txt and reply FIRST_LINE: <first line>",
            delegation: d, index: i, count: i + 1, state: "queued", ...extra,
          });
        const plan = (a: string, b: string) => this.emit({ event: "plan", items: [{ text: "Spawn foreground batch of two helper tasks", status: a }, { text: "Give one-line summary of batch results", status: b }] });
        this.at(40, () => this.emit({ event: "tool.start", tool_id: "toolu_batch", name: "delegate_task", detail: "helper-a-first-line, helper-b-line-count" }));
        this.at(50, () => sub(0, {}));
        this.at(60, () => sub(1, {}));
        this.at(70, () => plan("in_progress", "pending"));
        this.at(900, () => {
          this.emit({ event: "tool.end", tool_id: "toolu_batch", name: "", ok: true, ms: 0 });
          sub(0, { count: 2, state: "done", summary: "FIRST_LINE: alpha line", model: "claude-haiku-5-5", seconds: 19.9 });
          sub(1, { count: 2, state: "done", summary: "LINE_COUNT: 3", model: "claude-haiku-5-5", seconds: 28.6 });
          plan("completed", "completed");
        });
        this.say("Both helpers came back: `FIRST_LINE: alpha line` and `LINE_COUNT: 3`.", 1000);
        this.at(1200, () => this.end("done"));
        return;
      }
      if (text.startsWith("/subagents")) {
        // the events the Claude adapter emitted for a real run (claude-9-subagents.jsonl): two Agent calls in one
        // message, each subagent's own step, then each one's own answer and time; the second one is slow enough to
        // look at while it works. "/subagents hold" leaves the second one working until Stop or "/release".
        // (OmO's `task` names its subagents' type, `explore`; Claude Code's Agent calls are `general-purpose`)
        const kind = this.agent === "omo" ? "explore" : "general-purpose";
        const sub = (id: string, index: number, goal: string, extra: Record<string, unknown> = {}) =>
          this.emit({ event: "subagent", id, agent: this.agent, name: kind, goal, delegation: "claude-msg_1", index, count: index + 1, state: "running", ...extra });
        this.at(40, () => this.emit({ event: "tool.start", tool_id: "sa-1", name: "delegate_task", detail: "Read a.txt first line" }));
        this.at(50, () => sub("sa-1", 0, "Read a.txt first line"));
        this.at(120, () => sub("sa-1", 0, "Read a.txt first line", { tool: "read_file", step: "a.txt" }));
        this.at(160, () => this.emit({ event: "tool.start", tool_id: "sa-2", name: "delegate_task", detail: "Count lines of b.txt" }));
        this.at(170, () => sub("sa-2", 1, "Count lines of b.txt", { count: 2 }));
        this.at(260, () => sub("sa-2", 1, "Count lines of b.txt", { count: 2, tool: "read_file", step: "b.txt" }));
        this.at(600, () => {
          this.emit({ event: "tool.end", tool_id: "sa-1", name: "", ok: true, ms: 0 });
          sub("sa-1", 0, "Read a.txt first line", { count: 2, state: "done", summary: "alpha line", seconds: 3.7, model: "claude-fable-5-2" });
        });
        if (text.includes("hold")) {
          this.holding = true;
          return;
        }
        this.at(1400, () => {
          this.emit({ event: "tool.end", tool_id: "sa-2", name: "", ok: true, ms: 0 });
          sub("sa-2", 1, "Count lines of b.txt", { count: 2, state: "done", summary: "3", seconds: 9.4, model: "claude-fable-5-2" });
        });
        this.say("a.txt starts with alpha line; b.txt has 3 lines.", 1500);
        this.at(1900, () => this.end("done"));
        return;
      }
      if (text.startsWith("/subask")) {
        // claude-9-subagent-ask.jsonl: a subagent's Bash needs approval; the card names the subagent
        const rid = `req-${++this.seq}`;
        this.at(40, () => this.emit({ event: "tool.start", tool_id: "sa-3", name: "delegate_task", detail: "Write c.txt via echo" }));
        this.at(50, () => this.emit({ event: "subagent", id: "sa-3", agent: this.agent, name: "general-purpose", goal: "Write c.txt via echo", delegation: "claude-msg_2", index: 0, count: 1, state: "running" }));
        this.at(120, () => this.emit({ event: "subagent", id: "sa-3", agent: this.agent, name: "general-purpose", goal: "Write c.txt via echo", delegation: "claude-msg_2", index: 0, count: 1, state: "running", tool: "terminal", step: "echo three > c.txt" }));
        this.at(160, () => {
          this.waiting = rid;
          this.subWaiting = true;
          this.emit({ event: "approval.request", request_id: rid, title: "Run this command?", command: "echo three > c.txt", cwd: this.cwd, choices: ["deny", "once", "session"], subagent: { id: "sa-3", name: "Write c.txt via echo" } });
        });
        return;
      }
      if (text.startsWith("/lateask")) {
        // claude-13-late-ask.jsonl (Claude Code 2.1.322): the subagent runs in the background, the turn ends, and only
        // then the subagent asks; the answer reaches Claude Code with no turn running, the subagent finishes, and
        // Claude Code's own turn tells of it
        const rid = `req-${++this.seq}`;
        const sub = (extra: Record<string, unknown>) =>
          this.emit({ event: "subagent", id: "sa-4", agent: this.agent, name: "general-purpose", goal: "Write gamma to c.txt", delegation: "claude-msg_3", index: 0, count: 1, state: "running", model: "claude-opus-5-5", ...extra });
        this.at(40, () => this.emit({ event: "tool.start", tool_id: "sa-4", name: "delegate_task", detail: "Write gamma to c.txt" }));
        this.at(50, () => {
          this.bgSub = true;
          sub({ model: "claude-opus-5-5" });
        });
        this.at(60, () => this.background(1));
        this.at(80, () => this.emit({ event: "tool.end", tool_id: "sa-4", name: "", ok: true, ms: 0 }));
        this.say("started", 100);
        this.at(500, () => {
          this.end("done"); // clears the pending timers: the late ask is scheduled after it
          this.at(300, () => sub({ tool: "terminal", step: "echo gamma > c.txt" }));
          this.at(400, () => {
            this.waiting = rid;
            this.lateAsk = true;
            this.emit({ event: "approval.request", request_id: rid, title: "Run this command?", command: "echo gamma > c.txt", cwd: this.cwd, choices: ["deny", "once", "session"], subagent: { id: "sa-4", name: "Write gamma to c.txt" } });
          });
        });
        return;
      }
      if (text.startsWith("/retry")) {
        // omo-12-retry.jsonl as the Pi adapter emits it: OmO retries the failed run once by itself (the line says
        // which try), the retry fails too, and the turn ends once with OmO's own reason
        this.at(60, () => this.emit({ event: "status", text: "Retrying 1 of 5", retry: { attempt: 1, max: 5 } }));
        if (text.includes("hold")) return;
        this.at(900, () =>
          this.end("error", "Anthropic rejected this conversation's request format, even after retrying without web search replay data. Run /compact or start a new session to continue, and report it if it happens again."),
        );
        return;
      }
      if (text.startsWith("/stoplate")) {
        // codex-12-late-step.jsonl: a foreground command; Stop ends the turn at once but the command runs on, and
        // Codex reports its end after the turn (`item/completed`, 39.9 s in all)
        this.at(60, () => this.emit({ event: "tool.start", tool_id: "exec-late", name: "terminal", detail: "sleep 40; echo late" }));
        this.lateStep = "exec-late";
        return;
      }
      if (text.startsWith("/background")) {
        // the turn ends with a command still running in the background (Claude background_tasks_changed, OmO
        // waiting_background): the header says so until it ends. "hold": it runs on until Stop; "busy": the turn
        // itself goes on too
        this.at(40, () => this.background(1));
        this.say("started", 80);
        if (text.includes("busy")) return;
        this.at(400, () => {
          this.end("done"); // clears the pending timers: the background's end is scheduled after it
          if (!text.includes("hold")) this.at(1100, () => this.background(0));
        });
        return;
      }
      if (text.startsWith("/slow")) {
        for (let k = 0; k < 40; k++) this.at(100 + k * 250, () => this.emit({ event: "delta", text: `line ${k + 1}\n` }));
        return;
      }
      this.sent++;
      if (text.startsWith("/work")) {
        // the events the Claude adapter emitted for a real two-file edit (Claude Code 2.1.322, claude-12-work.jsonl):
        // thinking text, its todo list (TaskCreate, then TaskUpdate per item), an Edit per file with its change,
        // then the answer. "/work hold" stops before the last item and the answer.
        const hold = text.includes("hold");
        const plan = (s: string[]) => this.emit({ event: "plan", items: MOCK_WORK.todo.map((t, k) => ({ text: t, status: s[k] })) });
        MOCK_WORK.thinking.forEach((t, k) => this.at(30 + k * 20, () => this.emit({ event: "thinking", text: t })));
        this.at(120, () => plan(["pending", "pending", "pending"]));
        this.at(160, () => plan(["in_progress", "pending", "pending"]));
        // held: the last edit has not run yet (the list shows it under way)
        MOCK_WORK.edits.slice(0, hold ? -1 : undefined).forEach((e, k) => {
          const at = 200 + k * 160;
          this.at(at, () => this.emit({ event: "tool.start", tool_id: e.id, name: "patch", detail: e.detail }));
          this.at(at + 10, () => this.emit({ event: "tool.diff", tool_id: e.id, files: [e.file] }));
          this.at(at + 80, () => this.emit({ event: "tool.end", tool_id: e.id, name: "", ok: true, ms: 70 }));
          this.at(at + 100, () => plan(MOCK_WORK.todo.map((_, j) => (j <= k ? "completed" : j === k + 1 ? "in_progress" : "pending"))));
        });
        if (hold) return;
        this.say(MOCK_WORK.answer, 620);
        this.at(1000, () => this.end("done"));
        return;
      }
      this.at(60, () => this.emit({ event: "tool.start", tool_id: `t${this.seq}`, name: "read_file", detail: "README.md" }));
      this.at(300, () => this.emit({ event: "tool.end", tool_id: `t${this.seq}`, name: "", ok: true, ms: 240 }));
      const pics = i.images?.length ? ` (${i.images.length} picture${i.images.length > 1 ? "s" : ""})` : "";
      this.say(`(mock ${agentDef(this.agent).label}) You said: ${text}${pics}`, 360);
      this.at(800, () => this.end("done"));
    } else if (i.kind === "rewind") {
      if (!MOCK_REWINDS.includes(this.agent)) throw new Error(`${agentDef(this.agent).label} cannot take a message back here`);
      if (this.turn) throw new Error("wait until the turn ends");
      if (this.sent < 1) throw new Error("nothing to take back");
      this.sent--;
      this.at(30, () => {
        this.emit({ event: "rewound" });
        this.emit({ event: "session.info", rewind: this.sent > 0 });
      });
    } else if (i.kind === "interrupt") {
      if (!this.turn && this.agent === "claude" && (this.bg > 0 || this.lateAsk)) {
        // claude-13-late-ask-stop / claude-14-background-stop.jsonl: no turn runs; Claude Code withdraws the late ask,
        // stops its background subagent and command, and says nothing is left in the background
        this.stop();
        this.at(20, () => {
          if (this.lateAsk && this.waiting) this.emit({ event: "prompt.expired", request_id: this.waiting, reason: "cancelled" });
          this.lateAsk = false;
          this.waiting = null;
          if (this.bgSub) this.emit({ event: "subagent", id: "sa-4", agent: this.agent, name: "general-purpose", goal: "Write gamma to c.txt", delegation: "claude-msg_3", index: 0, count: 1, state: "cancelled", model: "claude-opus-5-5" });
          this.bgSub = false;
          this.background(0);
        });
        return;
      }
      if (!this.turn) throw new Error("nothing is running");
      this.at(20, () => {
        // as the Claude adapter does: a subagent still out when the turn stops is cancelled with it
        if (this.holding) this.emit({ event: "subagent", id: "sa-2", agent: this.agent, name: "general-purpose", goal: "Count lines of b.txt", delegation: "claude-msg_1", index: 1, count: 2, state: "cancelled" });
        this.holding = false;
        const late = this.lateStep;
        this.lateStep = "";
        this.end("interrupted");
        if (late) this.timers.push(setTimeout(() => this.emit({ event: "tool.end", tool_id: late, name: "", ok: true, ms: 39_887 }), 600));
      });
    } else if (i.kind === "approve") {
      if (i.request_id !== this.waiting) throw new Error("no such request");
      this.waiting = null;
      if (this.lateAsk) {
        // no turn runs: the subagent goes on, ends, the background count drops, and Claude Code's own turn says so
        this.lateAsk = false;
        const done = i.choice !== "deny";
        this.at(300, () => {
          this.bgSub = false;
          this.emit({ event: "subagent", id: "sa-4", agent: this.agent, name: "general-purpose", goal: "Write gamma to c.txt", delegation: "claude-msg_3", index: 0, count: 1, state: "done", summary: done ? "WROTE" : "The command was not allowed.", seconds: 7.4, model: "claude-opus-5-5" });
        });
        this.at(320, () => this.background(0));
        this.at(400, () => {
          this.turn = true;
          this.emit({ event: "turn.start" });
          this.say(done ? "The subagent finished and reported WROTE." : "The subagent could not write c.txt.", 20);
          this.at(400, () => this.end("done"));
        });
      } else if (this.planAsk) {
        // allowed: plan mode ends and the work starts; denied: the agent asks what to change
        this.planAsk = false;
        if (i.choice === "deny") this.say("What should change in the plan?", 60);
        else {
          this.at(30, () => this.emit({ event: "session.info", mode: "default" }));
          this.say("Starting on the plan.", 60);
        }
        this.at(400, () => this.end("done"));
      } else if (i.request_id.startsWith("req-") && this.subWaiting) {
        // the subagent's command ran (or was refused); the subagent hands back, then the agent answers
        this.subWaiting = false;
        const done = i.choice !== "deny";
        this.at(60, () => this.emit({ event: "tool.end", tool_id: "sa-3", name: "", ok: true, ms: 0 }));
        this.at(80, () => this.emit({ event: "subagent", id: "sa-3", agent: this.agent, name: "general-purpose", goal: "Write c.txt via echo", delegation: "claude-msg_2", index: 0, count: 1, state: "done", summary: done ? "done" : "The command was not allowed.", seconds: 4.2 }));
        this.say(done ? "ok" : "The subagent could not write c.txt.", 120);
        this.at(500, () => this.end("done"));
      } else if (i.choice === "deny") {
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
