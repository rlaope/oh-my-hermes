import { describe, expect, it, vi } from "vitest";
import { activateLink, linkModifier, webLinkTarget } from "./engine-links";

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
