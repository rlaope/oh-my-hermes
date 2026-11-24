// Where the keyboard goes back to when a TERMINALS row's or split card cell's menu or Hand card closes (termBack): the
// invoker while it is on the page, else the session's face as the list draws it now, else the list's New terminal
// button; never the page's body.
import { describe, expect, it, vi } from "vitest";

// the test runs without a DOM: CSS.escape is the browser's
vi.stubGlobal("CSS", { escape: (s: string) => s.replace(/"/g, '\\"') });
const { termBack } = await import("./SessionsSection");

const el = (name: string, isConnected = true) => ({ name, isConnected }) as unknown as HTMLElement;
const FACE = '[data-testid="session-s1"] .ss-open, [data-testid="split-cell"][data-session="s1"] .sc-open';
const NEW = '[data-testid="session-new"]';
/** A page whose querySelector answers the selectors in `has`, and records what was asked. */
const page = (has: Record<string, HTMLElement>) => {
  const asked: string[] = [];
  return { asked, doc: { querySelector: (s: string) => (asked.push(s), has[s] ?? null) } as unknown as Pick<Document, "querySelector"> };
};

describe("termBack", () => {
  it("is the invoker while it is on the page, and looks nothing up", () => {
    const invoker = el("row face");
    const p = page({ [FACE]: el("other"), [NEW]: el("new") });
    expect(termBack(invoker, "s1", p.doc)).toBe(invoker);
    expect(p.asked).toEqual([]);
  });

  it("is the session's face as drawn now when the invoker is gone (a split made or ended since)", () => {
    const face = el("cell face");
    const p = page({ [FACE]: face, [NEW]: el("new") });
    expect(termBack(null, "s1", p.doc)).toBe(face);
    expect(termBack(el("old row face", false), "s1", p.doc)).toBe(face);
  });

  it("is the New terminal button when the session is gone too", () => {
    const plus = el("new");
    expect(termBack(el("gone", false), "s1", page({ [NEW]: plus }).doc)).toBe(plus);
  });

  it("is nothing, not the body, with none of them on the page", () => {
    expect(termBack(null, "s1", page({}).doc)).toBeNull();
  });
});
