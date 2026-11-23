import { afterEach, describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { Bot, PlatformState, PlatformsRead } from "../lib/protocol";
import { setLang, t, LANGS } from "../i18n";
import { PlatformChip, PlatformItem, PlatformsBody } from "./PlatformSection";
import { fixSteps, notConnected, platformName, restartGateway, rowWords, statusWords, whyWords } from "./platforms";

const BOT = { name: "demo-bot", display_name: "Demo" } as Bot;
const REMOTE = { name: "far:demo-bot", display_name: "Demo", host: { kind: "ssh", peer: "far", label: "Other", host: "h" } } as Bot;

const state = (over: Partial<PlatformState> = {}): PlatformState => ({
  platform: "discord",
  status: "disconnected",
  attention: true,
  since: "2026-11-23T09:00:00Z",
  logged: "2026-11-23T09:30:00Z",
  reason_kind: "discord_privileged_intents",
  unknown_why: "",
  reason: "Shard ID None is requesting privileged intents that have not been explicitly enabled in the developer portal.",
  guidance: "Hermes is requesting: - Message Content Intent - Server Members Intent (required for DISCORD_ALLOWED_ROLES)",
  fix: "Discord refused the bot's privileged gateway intents.",
  restart: "hermes -p default gateway restart",
  intents: ["Message Content", "Server Members"],
  ...over,
});
const read = (...platforms: PlatformState[]): PlatformsRead => ({ available: true, bots: { "demo-bot": { log: "read", platforms } } });
const item = (p: PlatformState, bot = "demo-bot") => renderToStaticMarkup(<PlatformItem p={p} bot={bot} />);
const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/&#x27;|&#39;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, " ");

afterEach(() => setLang("en"));

describe("which platforms the row speaks of", () => {
  it("only those known not to be connected, and none when OMH could not say", () => {
    const all = (["connected", "degraded", "connecting", "disabled", "failed", "disconnected", "reconnecting", "unknown"] as const).map(
      (status) => state({ platform: status, status }),
    );
    expect(notConnected(read(...all), "demo-bot").map((p) => p.status)).toEqual(["failed", "disconnected", "reconnecting"]);
    expect(notConnected({ available: false, bots: read(...all).bots }, "demo-bot")).toEqual([]);
    expect(notConnected(null, "demo-bot")).toEqual([]);
    expect(notConnected(read(...all), "other-bot")).toEqual([]);
  });

  it("names the platform as it names itself, in every language", () => {
    for (const l of LANGS) {
      setLang(l);
      expect(rowWords(state())).toContain("Discord");
      expect(rowWords(state({ platform: "whatsapp", status: "failed" }))).toContain("WhatsApp");
    }
    expect(platformName("home_assistant")).toBe("Home assistant");
  });
});

describe("the sidebar row", () => {
  it("says the state in words and a mark, never colour alone", () => {
    const html = renderToStaticMarkup(<PlatformChip bot="demo-bot" down={[state()]} />);
    expect(html).toContain('data-testid="platform-down-demo-bot"');
    expect(html).toContain('role="status"');
    expect(text(html)).toContain("! Discord disconnected");
    expect(html).toContain('class="bot-pf bad"');
  });

  it("nothing at all when every platform is connected or not known", () => {
    expect(renderToStaticMarkup(<PlatformChip bot="demo-bot" down={[]} />)).toBe("");
  });

  it("leads with the one that needs the person and counts the rest", () => {
    const calm = state({ platform: "slack", status: "reconnecting", attention: false, reason_kind: "transient" });
    const html = renderToStaticMarkup(<PlatformChip bot="demo-bot" down={[calm, state({ status: "failed" })]} />);
    expect(text(html)).toContain("Discord failed to connect +1");
    const alone = renderToStaticMarkup(<PlatformChip bot="demo-bot" down={[calm]} />);
    expect(text(alone)).toContain("Slack reconnecting");
    expect(alone).toContain('class="bot-pf"'); // Hermes retries it on its own: not drawn as a failure
  });
});

describe("the bot page's section", () => {
  it("the privileged-intents refusal: which intents, where, the allowlist alternative, Hermes' words and the restart to copy", () => {
    const html = item(state());
    const words = text(html);
    expect(words).toContain("Disconnected");
    expect(words).toContain("since");
    expect(words).toContain("Discord refused the bot's privileged gateway intents.");
    expect(words).toContain("Turn on Message Content Intent and Server Members Intent in the Discord Developer Portal");
    expect(words).toContain("Privileged Gateway Intents");
    expect(words).toContain("Or remove the role allowlist that needs Server Members Intent.");
    expect(words).toContain("requesting privileged intents"); // Hermes' own words
    expect(words).toContain("Server Members Intent (required for DISCORD_ALLOWED_ROLES)"); // Hermes' guidance
    expect(html).toContain('href="https://discord.com/developers/applications"');
    expect(html).toContain('<code data-testid="pf-restart">hermes -p default gateway restart</code>');
    expect(html).toContain('data-testid="pf-copy"');
    expect(words).toContain("This bot runs on the default gateway");
    // nothing that changes anything: no button but Copy
    expect([...html.matchAll(/<button[^>]*data-testid="([^"]+)"/g)].map((m) => m[1])).toEqual(["pf-copy"]);
  });

  it("without Hermes' guidance the intents are stated as Hermes' rule, not guessed", () => {
    const words = text(item(state({ status: "failed", intents: [], guidance: "" })));
    expect(words).toContain("Failed to connect");
    expect(words).toContain("Server Members Intent too when the bot has a role allowlist (DISCORD_ALLOWED_ROLES)");
  });

  it("a bot with its own gateway names no other gateway", () => {
    expect(restartGateway(state({ restart: "hermes -p demo-bot gateway restart" }), "demo-bot")).toBeNull();
    expect(text(item(state({ restart: "hermes -p demo-bot gateway restart" })))).not.toContain("runs on the");
  });

  it("a token Discord rejected: reset it, then restart", () => {
    const steps = fixSteps(state({ reason_kind: "discord_token_rejected", intents: [] }), "demo-bot");
    expect(steps.map((s) => s.kind)).toEqual(["text", "portal", "restart"]);
    expect(steps[2]).toMatchObject({ lead: "then" });
  });

  it("reconnecting on its own: says so, offers nothing to run", () => {
    const p = state({ status: "reconnecting", attention: false, reason_kind: "transient", restart: "hermes -p default gateway restart" });
    expect(fixSteps(p, "demo-bot")).toEqual([{ kind: "text", text: t("pf.fix.retries") }]);
    expect(item(p)).not.toContain("pf-restart");
  });

  it("connected and unknown: no fix; unknown says why and is never worded as connected or not", () => {
    const up = item(state({ status: "connected", attention: false, reason_kind: "", reason: "", since: "" }));
    expect(text(up)).toContain("Connected");
    expect(up).not.toContain("pf-fix");
    for (const why of ["earlier_run", "not_served", "ambiguous", "unknown_state"]) {
      const p = state({ status: "unknown", attention: false, unknown_why: why, since: "" });
      const html = item(p);
      expect(statusWords(p)).toBe("Not known");
      expect(text(html)).toContain(whyWords(p));
      expect(html).not.toContain("pf-fix");
      for (const word of ["Connected", "Disconnected", "Failed to connect", "since"]) expect(text(html)).not.toContain(word);
    }
  });

  it("says when OMH could not be asked, when nothing is configured, and that a remote bot is not read", () => {
    expect(renderToStaticMarkup(<PlatformsBody bot={BOT} read={{ available: false, bots: {} }} />)).toContain("pf-unavailable");
    expect(renderToStaticMarkup(<PlatformsBody bot={BOT} read={read()} />)).toContain("pf-none");
    const remote = renderToStaticMarkup(<PlatformsBody bot={REMOTE} read={read(state())} />);
    expect(text(remote)).toContain(t("pf.remote"));
    expect(remote).not.toContain("pf-discord");
    const listed = renderToStaticMarkup(<PlatformsBody bot={BOT} read={read(state(), state({ platform: "slack", status: "connected", attention: false }))} />);
    expect(listed).toContain('data-testid="pf-discord"');
    expect(listed).toContain('data-testid="pf-slack"');
  });

  it("every language has words for every state, reason and fix", () => {
    for (const l of LANGS) {
      setLang(l);
      const words = text(item(state()));
      expect(words).toContain("Discord Developer Portal");
      expect(words).toContain("hermes -p default gateway restart");
      expect(words).not.toMatch(/pf\.[a-z]/); // no key left showing
    }
  });
});
