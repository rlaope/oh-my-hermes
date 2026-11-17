// Where the bottom terminal panel's shells run. In the desktop app: the Tauri shell's `shell_start`
// (src-tauri/src/sessions.rs `start_shell`: the person's login shell, decided there, never named by the page) and
// then the same `session_*` commands every PTY session uses. In a plain browser (dev, e2e against the mock bridge)
// a mock shell echoes typing and answers a few commands, and records every call in `window.__omherShellCalls`.

import { mockPtyOut, nextMockPty } from "../sessions/fg";

export interface ShellStarted {
  id: number;
  /** the folder the shell started in: the one asked for when it exists, else home */
  cwd: string;
}

export interface ShellHost {
  readonly kind: "tauri" | "mock";
  /** Start the login shell in `cwd` (null: home). Only a folder and a size go to the shell: never a program. */
  start(cwd: string | null, cols: number, rows: number, onData: (d: Uint8Array | string) => void, onExit: (code: number | null) => void): Promise<ShellStarted>;
  write(id: number, data: string): Promise<void>;
  /** The terminal has drawn `bytes` more of shell `id`'s output (the PTY's output credit). */
  ack(id: number, bytes: number): void;
  resize(id: number, cols: number, rows: number): Promise<void>;
  /** Stop the shell (hang-up, then a hard kill) and forget it. */
  close(id: number): Promise<void>;
}

// ---- Tauri ----------------------------------------------------------------------------------

class TauriShellHost implements ShellHost {
  readonly kind = "tauri" as const;
  private core = () => import("@tauri-apps/api/core");
  async start(cwd: string | null, cols: number, rows: number, onData: (d: Uint8Array) => void, onExit: (c: number | null) => void) {
    const { invoke, Channel } = await this.core();
    const data = new Channel<ArrayBuffer>();
    data.onmessage = (b) => onData(new Uint8Array(b));
    const exit = new Channel<number | null>();
    exit.onmessage = (c) => onExit(c);
    return invoke<ShellStarted>("shell_start", { cwd, cols, rows, onData: data, onExit: exit });
  }
  async write(id: number, data: string) {
    const { invoke } = await this.core();
    await invoke("session_write", { id, data });
  }
  /** Drawn bytes not yet sent, by shell: one `session_ack` per shell for everything drawn in the same task. A failed
   *  call puts its bytes back so they ride on the next one. */
  private drawn = new Map<number, number>();
  private sending = false;
  ack(id: number, bytes: number) {
    this.drawn.set(id, (this.drawn.get(id) ?? 0) + bytes);
    if (this.sending) return;
    this.sending = true;
    queueMicrotask(() => {
      this.sending = false;
      const all = [...this.drawn];
      this.drawn.clear();
      void this.core().then(({ invoke }) => {
        for (const [sid, n] of all) void invoke("session_ack", { id: sid, bytes: n }).catch(() => void this.drawn.set(sid, (this.drawn.get(sid) ?? 0) + n));
      });
    });
  }
  async resize(id: number, cols: number, rows: number) {
    const { invoke } = await this.core();
    await invoke("session_resize", { id, cols, rows });
  }
  async close(id: number) {
    this.drawn.delete(id);
    const { invoke } = await this.core();
    await invoke("session_close", { id });
  }
}

// ---- Mock -----------------------------------------------------------------------------------

export type MockShellCall =
  | { op: "start"; id: number; cwd: string | null; at: string; cols: number; rows: number }
  | { op: "write"; id: number; data: string }
  | { op: "resize"; id: number; cols: number; rows: number }
  | { op: "close"; id: number };

/** `__omherShellDie` (e2e): the next shells cannot start (`error`: start fails with it) or end at once with `code`,
 *  as a broken login shell does. */
type MockGlobals = { __omherShellCalls?: MockShellCall[]; __omherShellHome?: string; __omherShellFolders?: string[]; __omherShellDie?: { error?: string; code?: number } };

const MOCK_HOME = "/home/you";
const leafOf = (p: string) => p.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || p;

/** Coloured output a person recognises (the mock's `git log` and `pnpm test`), so a theme shot shows colours. */
const GIT_LOG = [
  "\x1b[33m4ae1eb5\x1b[0m \x1b[36m(HEAD -> \x1b[32mmain\x1b[36m, \x1b[31morigin/main\x1b[36m)\x1b[0m Merge pull request #2900 from feature/omher-turn-bubbles",
  "\x1b[33m786f610\x1b[0m Merge pull request #2899 from feature/omher-live-plans",
  "\x1b[33m354759c\x1b[0m \x1b[1mfeat(omher):\x1b[0m live plans in the side panel",
  "\x1b[33m9d01c2e\x1b[0m fix(omher): keep the chat scrolled to the newest message",
];
const TEST_RUN = [
  " \x1b[32m✓\x1b[0m src/app/shortcuts.test.ts \x1b[2m(14 tests)\x1b[0m \x1b[33m12ms\x1b[0m",
  " \x1b[32m✓\x1b[0m src/terminal/panel.test.ts \x1b[2m(6 tests)\x1b[0m \x1b[33m9ms\x1b[0m",
  " \x1b[31m✗\x1b[0m src/chat/scroll.test.ts \x1b[2m(1 failed)\x1b[0m",
  "",
  " \x1b[1mTest Files\x1b[0m  \x1b[1;31m1 failed\x1b[0m\x1b[2m | \x1b[0m\x1b[1;32m2 passed\x1b[0m \x1b[2m(3)\x1b[0m",
];

class MockShellHost implements ShellHost {
  readonly kind = "mock" as const;
  private live = new Map<number, { line: string; cwd: string; out: (d: string) => void; exit: (c: number | null) => void }>();
  constructor(private g: MockGlobals = globalThis as MockGlobals) {}
  private log(c: MockShellCall) {
    (this.g.__omherShellCalls ??= []).push(c);
  }
  private prompt(cwd: string) {
    const home = this.g.__omherShellHome ?? MOCK_HOME;
    return `\x1b[32myou@mock\x1b[0m \x1b[34m${cwd === home ? "~" : leafOf(cwd)}\x1b[0m % `;
  }
  async start(cwd: string | null, cols: number, rows: number, onData: (d: string) => void, onExit: (c: number | null) => void) {
    const id = nextMockPty();
    const home = this.g.__omherShellHome ?? MOCK_HOME;
    // as the shell does: the folder when it exists (the mock's list; any absolute path when none is set), else home
    const folders = this.g.__omherShellFolders;
    const ok = !!cwd && cwd.startsWith("/") && (!folders || folders.includes(cwd));
    const at = ok ? cwd! : home;
    const die = this.g.__omherShellDie;
    if (die?.error) throw new Error(die.error);
    this.log({ op: "start", id, cwd, at, cols, rows });
    this.live.set(id, { line: "", cwd: at, out: onData, exit: onExit });
    mockPtyOut(id, onData);
    if (typeof die?.code === "number") {
      setTimeout(() => {
        onData(`\x1b[31m(mock) the login shell could not read its profile\x1b[0m\r\n`);
        this.live.delete(id);
        onExit(die.code!);
      }, 20);
      return { id, cwd: at };
    }
    setTimeout(() => onData(`\x1b[2m(mock) login shell in ${at}\x1b[0m\r\n${this.prompt(at)}`), 20);
    return { id, cwd: at };
  }
  ack() {}
  async write(id: number, data: string) {
    this.log({ op: "write", id, data });
    const s = this.live.get(id);
    if (!s) throw new Error("no such session");
    for (const ch of data) {
      if (ch === "\r") {
        const line = s.line.trim();
        s.line = "";
        const quit = /^exit(?: (\d+))?$/.exec(line);
        if (quit) {
          s.out("\r\nlogout\r\n");
          this.live.delete(id);
          setTimeout(() => s.exit(Number(quit[1] ?? 0)), 10);
          return;
        }
        const body = line === "pwd" ? [s.cwd] : line === "git log --oneline" ? GIT_LOG : line === "pnpm test" ? TEST_RUN : line ? [`${line}`] : [];
        s.out(`\r\n${body.map((l) => `${l}\r\n`).join("")}${this.prompt(s.cwd)}`);
      } else if (ch === "\x04" && !s.line) {
        // Ctrl+D at an empty prompt: the shell logs out
        s.out("\r\nlogout\r\n");
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
let host: ShellHost | null = null;
export function getShellHost(): ShellHost {
  return (host ??= inTauri() ? new TauriShellHost() : new MockShellHost());
}
