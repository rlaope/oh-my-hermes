// What a terminal does when its program ends (agents.ts termEnd; e2e/term-exit.spec.ts runs it in a terminal).
import { describe, expect, it } from "vitest";
import { RESUME_FAILS_MS, termEnd } from "./agents";

describe("termEnd", () => {
  it("a TERMINALS CLI row goes on as the login shell, however its CLI ended", () => {
    for (const code of [0, 3, null]) for (const typed of [true, false]) expect(termEnd({ ofChat: false, shell: false, typed, code })).toBe("shell");
  });

  it("a CLI continuing its conversation that ends before anything was typed, or soon after it started, stays with it", () => {
    for (const code of [0, 1, null]) {
      expect(termEnd({ ofChat: false, shell: false, typed: false, code, resumed: true, ms: 60_000 })).toBe("ended");
      expect(termEnd({ ofChat: false, shell: false, typed: true, code, resumed: true, ms: 200 })).toBe("ended");
      expect(termEnd({ ofChat: false, shell: false, typed: true, code, resumed: true, ms: RESUME_FAILS_MS - 1 })).toBe("ended");
    }
  });

  it("a continued CLI the person used and then left goes on as the login shell, as a new one does", () => {
    expect(termEnd({ ofChat: false, shell: false, typed: true, code: 0, resumed: true, ms: RESUME_FAILS_MS })).toBe("shell");
    expect(termEnd({ ofChat: false, shell: false, typed: true, code: 2, resumed: true, ms: 60_000 })).toBe("shell");
    // a new conversation that ends at once is not kept: there is nothing of it to continue
    expect(termEnd({ ofChat: false, shell: false, typed: false, code: 1, resumed: false, ms: 50 })).toBe("shell");
  });

  it("a TERMINALS shell closes its row on exit, Ctrl+D or any code once the person typed", () => {
    expect(termEnd({ ofChat: false, shell: true, typed: true, code: 0 })).toBe("close");
    expect(termEnd({ ofChat: false, shell: true, typed: true, code: 3 })).toBe("close");
    expect(termEnd({ ofChat: false, shell: true, typed: true, code: null })).toBe("close");
    expect(termEnd({ ofChat: false, shell: true, typed: false, code: 0 })).toBe("close");
  });

  it("a shell that ends with an error before anything was typed stays, so its error can be read", () => {
    expect(termEnd({ ofChat: false, shell: true, typed: false, code: 1 })).toBe("ended");
    expect(termEnd({ ofChat: false, shell: true, typed: false, code: null })).toBe("ended");
  });

  it("a chat session's terminal view only says it ended", () => {
    expect(termEnd({ ofChat: true, shell: false, typed: true, code: 0 })).toBe("ended");
  });
});
