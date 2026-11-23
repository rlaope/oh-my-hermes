import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Markdown } from "./Markdown";
import { LinkChip, withLinks } from "./LinkChip";
import { keepTermLinks } from "./remarkTermLinks";
import { MentionContext, type Mentions } from "./Mention";

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

  it("keeps one whole address where GFM split its query into links, strikethrough or emphasis", () => {
    const cases: [string, string][] = [
      ["obsidian://open?vault=x&file=https://evil.example/a", "Obsidian · a"],
      ["obsidian://open?vault=me@example.com", "Obsidian vault · me@example.com"],
      ["obsidian://open?vault=x&file=www.example.com", "Obsidian · www.example.com"],
      ["obsidian://open?vault=a~b~c&file=*x*y", "Obsidian · *x*y"],
    ];
    for (const [url, label] of cases) {
      const out = html(`see ${url}, then more`);
      expect(out, url).toContain(label);
      expect(out, url).toContain(`title="${url.replace(/&/g, "&amp;")}"`);
      expect(out, url).not.toMatch(/<a |<del>|<em>|href=/);
      expect(out, url).toMatch(/<\/span>, then more<\/p>$/);
      expect(out.match(/data-testid="link-chip"/g), url).toHaveLength(1);
    }
    // a web link after a space is its own chip again
    const two = html("obsidian://open?vault=x&file=a https://example.com/b");
    expect(two).toContain('href="https://example.com/b"');
    expect(two).toContain('title="obsidian://open?vault=x&amp;file=a"');
  });

  it("a reference-style link and an upper-case scheme are chips too, never an href", () => {
    const ref = html("Read [the note][n] and [it][n].\n\n[n]: obsidian://open?vault=Work&file=Ideas.md");
    expect(ref.match(/data-service="obsidian"/g)).toHaveLength(2);
    expect(ref).toContain("the note");
    expect(ref).not.toMatch(/<a |href=/);
    const upper = html("see OBSIDIAN://open?vault=Work&file=Ideas now");
    expect(upper).toContain("Obsidian · Ideas");
    expect(upper).not.toContain("<a");
  });

  it("names its address to assistive tech, not only in the tooltip", () => {
    expect(html(`see ${NOTE}`)).toContain(`<span class="vh">${NOTE.replace(/&/g, "&amp;")}</span>`);
  });

  it("a mention inside its text stays text: the chip opens nothing", () => {
    const m: Mentions = { resolve: (n) => (n === "kami" ? "kami" : null), nameOf: (b) => b, current: null, open: () => {} };
    const render = (md: string) => renderToStaticMarkup(<MentionContext.Provider value={m}><Markdown text={md} /></MentionContext.Provider>);
    expect(render("ask @kami")).toContain('data-testid="mention"');
    const out = render(`[ask @kami](${NOTE})`);
    expect(out).toContain('data-service="obsidian"');
    expect(out).not.toContain('data-testid="mention"');
  });

  it("a second address after a folded one in the same text is a chip too", () => {
    const cases: [string, string[]][] = [
      ["obsidian://open?vault=x&file=*a*b obsidian://open?vault=y z", ["obsidian://open?vault=x&amp;file=*a*b", "obsidian://open?vault=y"]],
      ["obsidian://open?vault=x&file=*a*b obsidian://open?vault=y&file=www.f.com z", ["obsidian://open?vault=x&amp;file=*a*b", "obsidian://open?vault=y&amp;file=www.f.com"]],
      ["obsidian://open?vault=x&file=~a~b, then obsidian://open?vault=y", ["obsidian://open?vault=x&amp;file=~a~b", "obsidian://open?vault=y"]],
    ];
    for (const [md, titles] of cases) {
      const out = html(md);
      expect([...out.matchAll(/data-service="obsidian"[^>]*title="([^"]*)"/g)].map((m) => m[1]), md).toEqual(titles);
      expect(out, md).not.toMatch(/<a |<del>|<em>|href=/);
    }
  });

  it("an explicit markdown link written right after an address stays the author's link", () => {
    const out = html("obsidian://open?vault=a[click](https://example.com/z) after");
    expect(out).toContain('title="obsidian://open?vault=a"');
    expect(out).toMatch(/<a href="https:\/\/example.com\/z"[^>]*>click<\/a> after<\/p>$/);
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
