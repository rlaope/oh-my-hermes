import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Markdown } from "./Markdown";
import { withLinks } from "./LinkChip";
import { keepTermLinks } from "./remarkTermLinks";
import { termChipState, termLinkState } from "./TermLinkChip";
import { getSessions } from "../../sessions/sessions";

const html = (md: string) => renderToStaticMarkup(<Markdown text={md} />);

describe("the terminal link chip's state", () => {
  const now = 100_000;
  it("working while output flows or progress is reported, waiting at its prompt, news when it rang unseen", () => {
    expect(termLinkState({ status: "running" }, { lastOut: now - 500 }, undefined, now)).toBe("working");
    expect(termLinkState({ status: "running" }, { lastOut: now - 60_000, progress: true }, undefined, now)).toBe("working");
    expect(termLinkState({ status: "running" }, { lastOut: now - 60_000 }, undefined, now)).toBe("waiting");
    expect(termLinkState({ status: "starting" }, {}, undefined, now)).toBe("waiting");
    expect(termLinkState({ status: "running" }, { lastOut: now - 10 }, "bell", now)).toBe("news");
  });
  it("done when it ended with 0, ended otherwise (an error, a signal, could not start, paused after a restart)", () => {
    expect(termLinkState({ status: "exited", exitCode: 0 }, {}, undefined, now)).toBe("done");
    expect(termLinkState({ status: "exited", exitCode: 2 }, {}, undefined, now)).toBe("ended");
    expect(termLinkState({ status: "exited", exitCode: null }, {}, undefined, now)).toBe("ended");
    expect(termLinkState({ status: "failed" }, {}, undefined, now)).toBe("ended");
    expect(termLinkState({ status: "exited", exitCode: null, paused: true }, {}, undefined, now)).toBe("ended");
  });
  it("shows a ring nobody saw as news, on the chip and in the bots' status file alike", () => {
    expect(termChipState({ status: "running" }, { lastOut: now - 60_000 }, "bell", now)).toBe("news");
    expect(termLinkState({ status: "running" }, { lastOut: now - 60_000 }, "bell", now)).toBe("news");
    expect(termLinkState({ status: "running" }, { lastOut: now - 500 }, "bell", now)).toBe("news");
    expect(termChipState({ status: "running" }, { lastOut: now - 60_000 }, undefined, now)).toBe("waiting");
    expect(termChipState({ status: "running" }, { lastOut: now - 500 }, undefined, now)).toBe("working");
    expect(termChipState({ status: "exited", exitCode: 0 }, {}, "bell", now)).toBe("done");
  });
  it("a quiet done (progress reported done, unseen) is news too, and reported working again beats any stale news", () => {
    expect(termChipState({ status: "running" }, { lastOut: now - 60_000 }, "quiet", now)).toBe("news");
    expect(termLinkState({ status: "running" }, { lastOut: now - 60_000 }, "quiet", now)).toBe("news");
    // the review's stale case: a ring nobody saw, then the program reports working again
    expect(termChipState({ status: "running" }, { lastOut: now - 60_000, progress: true }, "bell", now)).toBe("working");
    expect(termLinkState({ status: "running" }, { lastOut: now - 60_000, progress: true }, "bell", now)).toBe("working");
    expect(termChipState({ status: "running" }, { lastOut: now - 60_000, progress: true }, "quiet", now)).toBe("working");
  });
});

describe("terminal links in messages", () => {
  it("a bare link in bot markdown is an omher chip; one not on this computer says so", () => {
    const out = html("Look at omher://terminal/abcdefgh23 please.");
    expect(out).toContain('data-testid="term-link-chip"');
    expect(out).toContain('data-state="gone"');
    expect(out).toContain("Terminal not on this computer");
    expect(out).not.toContain(">omher://terminal/abcdefgh23<");
  });

  it("a markdown link to one keeps its href (the default url transform would drop the scheme)", () => {
    expect(keepTermLinks("omher://terminal/abcdefgh23")).toBe("omher://terminal/abcdefgh23");
    expect(keepTermLinks("omher://evil/x")).toBe("");
    expect(keepTermLinks("javascript:alert(1)")).toBe("");
    expect(keepTermLinks("https://example.com/a")).toBe("https://example.com/a");
    expect(html("[the build](omher://terminal/abcdefgh23)")).toContain('data-testid="term-link-chip"');
  });

  it("in code it stays text", () => {
    const out = html("`omher://terminal/abcdefgh23`\n\n```\nomher://terminal/abcdefgh23\n```");
    expect(out).not.toContain("term-link-chip");
    expect(out).toContain("omher://terminal/abcdefgh23");
  });

  it("a session in TERMINALS: its title, CLI mark and state dot, and the link in the tooltip", () => {
    const ss = getSessions();
    const id = ss.startTerminal("claude", "/w/web-app")!;
    ss.rename(id, "checkout build");
    const link = ss.linkOf(id)!;
    const out = html(`see ${link}`);
    expect(out).toContain(`data-session="${id}"`);
    expect(out).toContain("checkout build");
    expect(out).toContain('data-testid="term-row-mark"');
    expect(out).toContain('data-agent="claude"');
    expect(out).toMatch(/data-state="(working|waiting)"/);
    expect(out).toContain(link);
  });

  it("plain text (a sent message) draws terminal links and web links in order", () => {
    const nodes = withLinks("a omher://terminal/abcdefgh23 b https://github.com/o/r/pull/1 c");
    const out = renderToStaticMarkup(<>{nodes}</>);
    expect(out.indexOf("term-link-chip")).toBeGreaterThan(-1);
    expect(out.indexOf("term-link-chip")).toBeLessThan(out.indexOf('data-testid="link-chip"'));
    expect(out).toContain("o/r#1");
  });
});
