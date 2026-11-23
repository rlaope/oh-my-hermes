import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Markdown } from "./Markdown";
import { LinkChip, withLinks } from "./LinkChip";
import { keepTermLinks } from "./remarkTermLinks";

const html = (md: string) => renderToStaticMarkup(<Markdown text={md} />);
const NOTE = "obsidian://open?vault=Work&file=Projects%2FLaunch%20Plan.md";

// omher opens only http(s) links and messenger threads (rule 22): an obsidian:// link is named, never a link.
describe("obsidian:// links", () => {
  it("a bare one in bot markdown is a chip with the note's name, the URL in the tooltip, and no href", () => {
    const out = html(`Saved to ${NOTE}.`);
    expect(out).toContain('data-testid="link-chip"');
    expect(out).toContain('data-service="obsidian"');
    expect(out).toContain('data-kind="note"');
    expect(out).toContain("Obsidian · Launch Plan");
    expect(out).toContain('data-brand="obsidian"');
    expect(out).toContain(`title="${NOTE.replace(/&/g, "&amp;")}"`);
    expect(out).not.toContain("<a");
    expect(out).not.toContain("href=");
    expect(out).toMatch(/<\/span>\.<\/p>$/); // the sentence's period stays text
  });

  it("a markdown link to one keeps its own text, still without an href", () => {
    const out = html(`See [the launch plan](${NOTE}) and <obsidian://search?vault=Work&query=retry>.`);
    expect(out).toContain("the launch plan");
    expect(out).toContain("Obsidian search · retry");
    expect(out).not.toContain("href=");
  });

  it("in code it stays text, and as an image source it is dropped", () => {
    const code = html("`obsidian://open?vault=Work&file=A`\n\n```\nobsidian://open?vault=Work&file=B\n```");
    expect(code).not.toContain("link-chip");
    expect(code).toContain("obsidian://open?vault=Work&amp;file=A");
    expect(html("![x](obsidian://open?vault=Work&file=A.png)")).not.toContain("obsidian://");
  });

  it("never relies on the url transform, which still drops the scheme", () => {
    expect(keepTermLinks(NOTE)).toBe("");
    expect(html(`[x](${NOTE}) **bold obsidian://vault/Work/Ideas**`)).not.toContain("<a");
  });

  it("leaves the text of a web link alone", () => {
    const out = html("[see obsidian://vault/Work/Ideas](https://example.com/a)");
    expect(out).toContain('href="https://example.com/a"');
    expect(out).not.toContain('data-service="obsidian"');
  });

  it("a sent message and the chip itself draw it as text", () => {
    const sent = renderToStaticMarkup(<>{withLinks(`note ${NOTE} and https://gitlab.com/acme/widgets/-/merge_requests/42`)}</>);
    expect(sent).toContain("Obsidian · Launch Plan");
    expect(sent).toContain("acme/widgets!42");
    expect(sent.match(/<a /g)).toHaveLength(1); // the GitLab chip only
    expect(renderToStaticMarkup(<LinkChip url="obsidian://vault/Work/Ideas" />)).toMatch(/^<span class="lk lk-static"/);
  });
});
