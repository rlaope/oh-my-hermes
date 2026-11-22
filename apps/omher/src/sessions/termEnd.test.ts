// What a terminal does when its program ends (agents.ts termEnd; e2e/term-exit.spec.ts and e2e/term-resume-fail.spec.ts
// run it in a terminal).
import { describe, expect, it } from "vitest";
import { idInUse, refusedResume, RESUME_FAILS_MS, setsUpScreen, termEnd } from "./agents";

describe("termEnd", () => {
  it("a TERMINALS CLI row goes on as the login shell, however its CLI ended", () => {
    for (const code of [0, 3, null]) for (const keyed of [true, false]) expect(termEnd({ ofChat: false, shell: false, keyed, code })).toBe("shell");
  });

  it("a CLI continuing its conversation that ends before it set up its screen stays with it, however late", () => {
    for (const code of [0, 1, null]) for (const ms of [50, 60_000]) expect(termEnd({ ofChat: false, shell: false, keyed: false, code, resumed: true, drew: false, ms })).toBe("ended");
  });

  it("one that set up its screen first stays only when it ended at once (Codex looks for the conversation after that)", () => {
    expect(termEnd({ ofChat: false, shell: false, keyed: false, code: 1, resumed: true, drew: true, ms: RESUME_FAILS_MS - 1 })).toBe("ended");
    expect(termEnd({ ofChat: false, shell: false, keyed: false, code: 1, resumed: true, drew: true, ms: RESUME_FAILS_MS })).toBe("shell");
  });

  it("one that printed its CLI's refusal and ended with an error stays, however late and whatever it drew", () => {
    for (const ms of [50, 2_500, 60_000]) {
      expect(termEnd({ ofChat: false, shell: false, keyed: false, code: 1, resumed: true, drew: true, refused: true, ms })).toBe("ended");
      expect(termEnd({ ofChat: false, shell: false, keyed: true, code: 1, resumed: true, drew: true, refused: true, ms })).toBe("ended");
    }
    // a refusal's words in a session that ended well are the person's own text, not a refusal
    expect(termEnd({ ofChat: false, shell: false, keyed: true, code: 0, resumed: true, drew: true, refused: true, ms: 60_000 })).toBe("shell");
    // a new conversation is never kept
    expect(termEnd({ ofChat: false, shell: false, keyed: false, code: 1, resumed: false, drew: false, refused: true, ms: 50 })).toBe("shell");
  });

  it("a continued CLI the person pressed keys in goes on as the login shell, however soon it ended", () => {
    for (const drew of [true, false]) for (const ms of [200, 60_000]) expect(termEnd({ ofChat: false, shell: false, keyed: true, code: 0, resumed: true, drew, ms })).toBe("shell");
    // a new conversation that ends at once is not kept: there is nothing of it to continue
    expect(termEnd({ ofChat: false, shell: false, keyed: false, code: 1, resumed: false, drew: false, ms: 50 })).toBe("shell");
  });

  it("a TERMINALS shell closes its row on exit, Ctrl+D or any code once the person pressed a key", () => {
    expect(termEnd({ ofChat: false, shell: true, keyed: true, code: 0 })).toBe("close");
    expect(termEnd({ ofChat: false, shell: true, keyed: true, code: 3 })).toBe("close");
    expect(termEnd({ ofChat: false, shell: true, keyed: true, code: null })).toBe("close");
    expect(termEnd({ ofChat: false, shell: true, keyed: false, code: 0 })).toBe("close");
  });

  it("a shell that ends with an error before any key stays, so its error can be read", () => {
    expect(termEnd({ ofChat: false, shell: true, keyed: false, code: 1 })).toBe("ended");
    expect(termEnd({ ofChat: false, shell: true, keyed: false, code: null })).toBe("ended");
  });

  it("a chat session's terminal view only says it ended", () => {
    expect(termEnd({ ofChat: true, shell: false, keyed: true, code: 0 })).toBe("ended");
  });
});

describe("setsUpScreen", () => {
  it("sees a program turn on its screen modes, alone or among others", () => {
    for (const s of ["\x1b[?1049h", "\x1b[?47h", "\x1b[?1047h", "\x1b[?2004h", "\x1b[?1004h", "\x1b[?25l\x1b[?2004h\x1b[?2031h", "\x1b[?1000;1049h", "\x1b[>7u", "\x1b[>1u", "\x1b[=1;1u"])
      expect(setsUpScreen(`x${s}y`), JSON.stringify(s)).toBe(true);
  });

  it("does not count a refusal with its terminal resets: modes turned off, Kitty popped or queried", () => {
    // what `claude --resume <unknown id>` prints in a terminal (Claude Code 2.1.330)
    const refusal =
      "\x1b7\x1b[r\x1b8\x1b[?25h\x1b[38;2;255;107;128mNo conversation found with session ID: 22222222-2222-4333-8444-555555555555\x1b[39m\r\r\n" +
      "\x1b[?25h\x1b(B\x0f\x1b[?1016l\x1b[?1006l\x1b[?1003l\x1b[?1002l\x1b[?1000l\x1b[>4m\x1b[?1004l\x1b[?2031l\x1b[?2004l\x1b[?7h\x1b[<u\x1b[?25h\x1b]0;\x07";
    expect(setsUpScreen(refusal)).toBe(false);
    for (const s of ["\x1b[?u", "\x1b[<1u", "\x1b[?25h", "\x1b[?7h", "\x1b[>4;0m", "plain text"]) expect(setsUpScreen(s), JSON.stringify(s)).toBe(false);
  });
});

describe("refusedResume", () => {
  it("knows Claude Code's and Codex's refusals, and nothing else", () => {
    expect(refusedResume("\x1b[38;2;255;107;128mNo conversation found with session ID: 22222222-2222-4333-8444-555555555555\x1b[39m")).toBe(true);
    expect(refusedResume("Error: Session ID 22222222-2222-4333-8444-555555555555 is already in use.")).toBe(true);
    expect(refusedResume("Error: No saved session found with ID 01a1f29c-c5b1-7301-a199-2dd07ff4b0aa. Run `codex resume` without an ID")).toBe(true);
    for (const s of ["", "Welcome back", "No conversation", "session found"]) expect(refusedResume(s), s).toBe(false);
    expect(idInUse("Error: Session ID x is already in use.")).toBe(true);
    expect(idInUse("No conversation found with session ID: x")).toBe(false);
  });
});
