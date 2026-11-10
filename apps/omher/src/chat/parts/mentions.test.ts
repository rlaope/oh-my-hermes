import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { botResolver, findMentions } from "./mentions";
import { codeRanges } from "./skillTokens";
import { Markdown } from "./Markdown";
import { MentionContext, type Mentions } from "./Mention";

const BOTS = [
  { name: "kami", display_name: "Kami" },
  { name: "friren", display_name: "Friren" },
  { name: "default", display_name: "Hermes", is_default: true },
  { name: "omh-tui", display_name: "OMH TUI" },
];
const resolve = botResolver(BOTS);
const bots = (text: string) => findMentions(text, resolve, codeRanges(text)).map((m) => m.bot);
const spans = (text: string) => findMentions(text, resolve, codeRanges(text)).map((m) => text.slice(m.start, m.end));

describe("botResolver", () => {
  it("resolves the slug, hermes for the default profile, and the display name; case-insensitive", () => {
    expect(resolve("kami")).toBe("kami");
    expect(resolve("KAMI")).toBe("kami");
    expect(resolve("hermes")).toBe("default");
    expect(resolve("default")).toBe("default");
    expect(resolve("omh-tui")).toBe("omh-tui");
    expect(resolve("foo")).toBeNull();
  });

  it("lets a slug win over another bot's display name", () => {
    const r = botResolver([
      { name: "a", display_name: "Kami" },
      { name: "kami", display_name: "Other" },
    ]);
    expect(r("kami")).toBe("kami");
  });
});

describe("findMentions", () => {
  it("finds known names, with their ranges, and leaves unknown ones", () => {
    expect(findMentions("ask @friren", resolve)).toEqual([{ bot: "friren", start: 4, end: 11 }]);
    expect(bots("@hermes and @omh-tui and @kami")).toEqual(["default", "omh-tui", "kami"]);
    expect(bots("ask @foo or @bar")).toEqual([]);
  });

  it("stops at punctuation and at Korean particles after the name", () => {
    expect(spans("@hermes, @kami. @friren! (@omh-tui) @hermes: check")).toEqual(["@hermes", "@kami", "@friren", "@omh-tui", "@hermes"]);
    expect(spans("저는 @hermes예요. @omh-tui는 다른 애. @kami도")).toEqual(["@hermes", "@omh-tui", "@kami"]);
    expect(spans("ping @hermes-")).toEqual(["@hermes"]);
  });

  it("needs a boundary before the @: no emails, paths or handles inside words", () => {
    expect(bots("mail kami@hermes.dev or a@kami.com")).toEqual([]);
    expect(bots("x@kami y_@kami 1@kami")).toEqual([]);
    expect(bots("see /w/@kami and @@kami")).toEqual([]);
  });

  it("skips @file: refs, packages and domains", () => {
    expect(bots("@file:src/a.ts @kami:x @kami/pkg @kami.dev")).toEqual([]);
    expect(bots("@kami.")).toEqual(["kami"]);
  });

  it("never matches inside inline code or a fenced block", () => {
    expect(bots("run `@kami` now")).toEqual([]);
    expect(bots("```\n@kami\n```\nthen @friren")).toEqual(["friren"]);
  });
});

describe("Markdown with mentions", () => {
  const ctx: Mentions = { resolve, nameOf: (b) => b, current: "kami", open: () => {} };
  const html = (text: string, value: Mentions | null = ctx) =>
    renderToStaticMarkup(createElement(MentionContext.Provider, { value }, createElement(Markdown, { text })));

  it("draws known mentions, skips code, links and unknown names", () => {
    const out = html("hi @friren, see `@hermes` and [@omh-tui](https://x.y) or @foo");
    expect(out.match(/data-testid="mention"/g)?.length).toBe(1);
    expect(out).toContain('data-bot="friren"');
    expect(out).toContain("<code>@hermes</code>");
    expect(out).toContain("@foo");
  });

  it("draws the open chat's own bot as an inert mention", () => {
    const out = html("me @kami");
    expect(out).toContain('class="mention self"');
    expect(out).not.toContain("tabindex");
  });

  it("is plain text without a provider", () => {
    expect(html("hi @friren", null)).not.toContain("mention");
  });
});
