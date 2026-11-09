// Where session processes run. In the desktop app: the Tauri shell (src-tauri/src/sessions.rs), which
// starts an allow-listed agent in a pseudo-terminal. In a plain browser (dev, e2e against the mock
// bridge) there is no shell, so a mock host echoes what you type and prints a "(mock)" banner.
import { AGENTS, agentDef, type AgentId, type AgentInfo } from "./agents";

export interface SessionHost {
  readonly kind: "tauri" | "mock";
  /** Stop anything an earlier page load left running (a webview reload keeps the shell alive). */
  reset(): Promise<void>;
  agents(): Promise<AgentInfo[]>;
  home(): Promise<string>;
  /** Native folder picker; null when the person cancels. */
  pickFolder(defaultPath: string): Promise<string | null>;
  /** Start `agent` in `cwd`. Only the agent id goes to the shell: never a command line. */
  start(
    agent: AgentId,
    cwd: string,
    cols: number,
    rows: number,
    onData: (data: Uint8Array | string) => void,
    onExit: (code: number | null) => void,
  ): Promise<number>;
  write(id: number, data: string): Promise<void>;
  resize(id: number, cols: number, rows: number): Promise<void>;
  close(id: number): Promise<void>;
}

// ---- Tauri ----------------------------------------------------------------------------------

export class TauriHost implements SessionHost {
  readonly kind = "tauri" as const;
  private async core() {
    return import("@tauri-apps/api/core");
  }
  async reset() {
    const { invoke } = await this.core();
    await invoke("session_close_all");
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
    const r = await open({ directory: true, multiple: false, defaultPath, title: "Choose a folder for the session" });
    return typeof r === "string" ? r : null;
  }
  async start(agent: AgentId, cwd: string, cols: number, rows: number, onData: (d: Uint8Array) => void, onExit: (c: number | null) => void) {
    const { invoke, Channel } = await this.core();
    const data = new Channel<ArrayBuffer>();
    data.onmessage = (b) => onData(new Uint8Array(b));
    const exit = new Channel<number | null>();
    exit.onmessage = (c) => onExit(c);
    return invoke<number>("session_start", { agent, cwd, cols, rows, onData: data, onExit: exit });
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
  op: "reset" | "start" | "write" | "resize" | "close";
  id?: number;
  agent?: string;
  cwd?: string;
  data?: string;
  cols?: number;
  rows?: number;
}

const BANNER: Record<AgentId, string> = {
  claude: "\x1b[38;2;217;119;87m✻\x1b[0m \x1b[1mClaude Code\x1b[0m \x1b[2m(mock)\x1b[0m",
  codex: "\x1b[1m>_ Codex\x1b[0m \x1b[2m(mock)\x1b[0m",
  omh: "\x1b[38;2;211;60;141m◆\x1b[0m \x1b[1moh-my-hermes\x1b[0m \x1b[2m(mock)\x1b[0m",
  pi: "\x1b[1mπ pi\x1b[0m \x1b[2m(mock)\x1b[0m",
  omp: "\x1b[1mπ oh-my-pi\x1b[0m \x1b[2m(mock)\x1b[0m",
  grok: "\x1b[1m𝕏 Grok\x1b[0m \x1b[2m(mock)\x1b[0m",
};
const PROMPT = "\x1b[2m›\x1b[0m ";

type MockGlobals = { __omherPickFolder?: string | null; __omherSessionCalls?: MockCall[]; __omherMockAgents?: AgentId[] };

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
  }
  async agents(): Promise<AgentInfo[]> {
    const installed = this.g.__omherMockAgents ?? ["claude", "codex", "omh"];
    return AGENTS.map((a) => ({ id: a.id, label: a.label, path: installed.includes(a.id) ? `/usr/local/bin/${a.program}` : null }));
  }
  async home() {
    return "/Users/you";
  }
  async pickFolder(defaultPath: string) {
    const v = this.g.__omherPickFolder;
    return v === undefined ? defaultPath : v;
  }
  async start(agent: AgentId, cwd: string, cols: number, rows: number, onData: (d: string) => void, onExit: (c: number | null) => void) {
    const id = ++this.next;
    this.log({ op: "start", id, agent, cwd, cols, rows });
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
}

const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

let host: SessionHost | null = null;
export function getHost(): SessionHost {
  return (host ??= inTauri() ? new TauriHost() : new MockHost());
}
