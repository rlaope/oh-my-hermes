import { describe, expect, it, vi } from "vitest";
import { activateLink, linkModifier, tipTop, webLinkTarget } from "./engine-links";

const click = (o: Partial<{ metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }> = {}) => ({ metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, ...o }) as MouseEvent;

describe("terminal links: the address rule (docs/OMHER-BOUNDARY.md rule 22)", () => {
  it("http and https open; the address comes back as the URL parser writes it", () => {
    expect(webLinkTarget("https://example.com/x")).toBe("https://example.com/x");
    expect(webLinkTarget("http://example.com")).toBe("http://example.com/");
    expect(webLinkTarget("https://example.com:8443/a?b=1#c")).toBe("https://example.com:8443/a?b=1#c");
  });

  it("a user name or password in the address, any other scheme, or no host: nothing", () => {
    for (const bad of [
      "http://user:pw@example.com",
      "https://user@example.com/x",
      "https://good.com@evil.com/",
      "file:///etc/passwd",
      "javascript:alert(1)",
      "ftp://example.com/x",
      "data:text/html,hi",
      "vscode://open?file=1",
      "example.com/x",
      "https://",
      "",
    ]) {
      expect(webLinkTarget(bad), bad).toBeNull();
    }
  });
});

describe("terminal links: which click opens", () => {
  it("Cmd on macOS, Ctrl elsewhere, nothing else held", () => {
    expect(linkModifier(click({ metaKey: true }), true)).toBe(true);
    expect(linkModifier(click({ ctrlKey: true }), true)).toBe(false);
    expect(linkModifier(click({ ctrlKey: true }), false)).toBe(true);
    expect(linkModifier(click({ metaKey: true }), false)).toBe(false);
    expect(linkModifier(click(), true)).toBe(false);
    expect(linkModifier(click(), false)).toBe(false);
    expect(linkModifier(click({ metaKey: true, shiftKey: true }), true)).toBe(false);
    expect(linkModifier(click({ ctrlKey: true, altKey: true }), false)).toBe(false);
  });

  it("opens once, through the opener it is given, only with the key held and an address that passes", () => {
    const open = vi.fn(async () => undefined);
    expect(activateLink(click({ metaKey: true }), "https://example.com/x", open, true)).toBe(true);
    expect(open).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledWith("https://example.com/x");
    open.mockClear();
    expect(activateLink(click(), "https://example.com/x", open, true)).toBe(false); // a plain click selects
    expect(activateLink(click({ metaKey: true }), "http://user:pw@example.com", open, true)).toBe(false);
    expect(activateLink(click({ metaKey: true }), "file:///etc/passwd", open, true)).toBe(false);
    expect(activateLink(click({ ctrlKey: true }), "https://example.com/x", open, true)).toBe(false); // Ctrl is not the key on macOS
    expect(open).not.toHaveBeenCalled();
  });

  it("an opener that fails is swallowed (the click does not throw)", async () => {
    const open = vi.fn(async () => {
      throw new Error("not a thread or web link");
    });
    expect(() => activateLink(click({ ctrlKey: true }), "https://example.com/", open, false)).not.toThrow();
    await Promise.resolve();
    expect(open).toHaveBeenCalledTimes(1);
  });
});

describe("where the hover hint goes", () => {
  /** A terminal whose screen starts at y=100 with `rows` lines of 15px. */
  const host = (rows: number, top = 100) => ({ querySelector: () => ({ getBoundingClientRect: () => ({ top, height: rows * 15 }) }) }) as unknown as HTMLElement;

  it("stands one line clear above the link's line, wherever in the line the pointer is", () => {
    // row 6 is y 190..205; the line above it (175..190) stays uncovered: a 24px hint ends at 175
    for (const y of [190, 197, 204.9]) expect(tipTop(y, host(30), 30, 24)).toBe(151);
    expect(tipTop(197, host(30), 30, 24) + 24).toBe(190 - 15);
  });

  it("goes below a link that has no room above: the same clear line under it", () => {
    // rows 0, 1 and 2: a 24px hint one line up would start above the screen
    expect(tipTop(105, host(30), 30, 24)).toBe(100 + 2 * 15);
    expect(tipTop(125, host(30), 30, 24)).toBe(115 + 2 * 15);
    // row 3 (145..160): 145 - 15 - 24 = 106, inside the screen
    expect(tipTop(150, host(30), 30, 24)).toBe(106);
  });

  it("still gives an answer when the screen cannot be measured", () => {
    expect(tipTop(200, host(0), 0, 24)).toBe(200 - 24 - 16);
  });
});
