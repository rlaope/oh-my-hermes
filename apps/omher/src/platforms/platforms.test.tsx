import { afterEach, describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { Bot, PlatformState, PlatformsRead } from "../lib/protocol";
import { setLang, t, LANGS } from "../i18n";
import { PlatformChip, PlatformItem, PlatformsBody } from "./PlatformSection";
import { ROW_RECONNECT_MS, botRead, fixSteps, notConnected, platformName, restartGateway, rowDown, rowWords, statusWords, whyWords } from "./platforms";

const BOT = { name: "demo-bot", display_name: "Demo" } as Bot;
const REMOTE = { name: "far:demo-bot", display_name: "Demo", host: { kind: "ssh", peer: "far", label: "Other", host: "h" } } as Bot;

const state = (over: Partial<PlatformState> = {}): PlatformState => ({
  platform: "discord",
  status: "disconnected",
  attention: true,
  since: "2020-01-02T03:04:05Z",
  logged: "2020-01-02T03:34:05Z",
  reason_kind: "discord_privileged_intents",
  unknown_why: "",
  reason: "Shard ID None is requesting privileged intents that have not been explicitly enabled in the developer portal.",
  guidance: "Hermes is requesting: - Message Content Intent - Server Members Intent (required for DISCORD_ALLOWED_ROLES)",
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

  it("keeps Hermes' routine reconnects off the row: only past ten minutes, or when Hermes flags it", () => {
    const at = Date.parse("2020-01-02T03:04:05Z");
    const re = (since: string, attention = false) => state({ status: "reconnecting", attention, since, reason_kind: "transient" });
    const shown = (p: PlatformState) => rowDown(read(p), "demo-bot", at + ROW_RECONNECT_MS).length;
    expect(ROW_RECONNECT_MS).toBe(600_000);
    expect(shown(re("2020-01-02T03:04:05Z"))).toBe(1); // exactly ten minutes
    expect(shown(re("2020-01-02T03:05:05Z"))).toBe(0); // nine
    expect(shown(re("2020-01-02T03:13:05Z", true))).toBe(1); // flagged
    expect(shown(re(""))).toBe(0);
    expect(shown(state())).toBe(1); // disconnected: at once
    expect(notConnected(read(re("2020-01-02T03:13:05Z")), "demo-bot")).toHaveLength(1); // the page still lists it
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

  it("says when OMH could not be asked and when nothing is configured", () => {
    expect(renderToStaticMarkup(<PlatformsBody bot={BOT} read={{ available: false, bots: {} }} />)).toContain("pf-unavailable");
    expect(renderToStaticMarkup(<PlatformsBody bot={BOT} read={read()} />)).toContain("pf-none");
    // not "no platform" when it cannot know: the bot is not in the answer, or its logs could not be read
    const missing = renderToStaticMarkup(<PlatformsBody bot={BOT} read={{ available: true, bots: {} }} />);
    expect(text(missing)).toContain(t("pf.notReported"));
    expect(missing).not.toContain("pf-none");
    for (const log of ["unreadable", "unrecognized", "unknown"] as const) {
      const html = renderToStaticMarkup(<PlatformsBody bot={BOT} read={{ available: true, bots: { "demo-bot": { log, platforms: [] } } }} />);
      expect(text(html)).toContain(t("pf.logUnread"));
      expect(html).not.toContain("pf-none");
    }
    const missingLog = renderToStaticMarkup(<PlatformsBody bot={BOT} read={{ available: true, bots: { "demo-bot": { log: "missing", platforms: [] } } }} />);
    expect(missingLog).toContain("pf-none");
    // this computer's answer never speaks for a bot on another one, even under the same bare name
    const remote = renderToStaticMarkup(<PlatformsBody bot={REMOTE} read={read(state())} />);
    expect(remote).toContain('data-why="unasked"');
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

describe("a bot on another computer (rule 45)", () => {
  const peerRead = (there: PlatformsRead["peers"], local: PlatformState[] = []): PlatformsRead => ({ ...read(...local), peers: there });
  const up = (...platforms: PlatformState[]) => ({ far: { available: true, why: "" as const, bots: { "demo-bot": { log: "read" as const, platforms } } } });

  it("reads what that computer's own bridge said, under the bare name, never this computer's row", () => {
    const r = peerRead(up(state()));
    expect(notConnected(r, "far:demo-bot").map((p) => p.status)).toEqual(["disconnected"]);
    expect(notConnected(r, "demo-bot")).toEqual([]); // the local bot of the same name is not the peer's
    expect(botRead(r, "far:demo-bot")).toMatchObject({ available: true, peer: "far", bare: "demo-bot", why: "" });
    expect(notConnected(peerRead(up(state())), "near:demo-bot")).toEqual([]); // another peer
  });

  it("the same ten-minute threshold on the row", () => {
    const at = Date.parse("2020-01-02T03:04:05Z");
    const re = state({ status: "reconnecting", attention: false, reason_kind: "transient" });
    expect(rowDown(peerRead(up(re)), "far:demo-bot", at + ROW_RECONNECT_MS - 1)).toHaveLength(0);
    expect(rowDown(peerRead(up(re)), "far:demo-bot", at + ROW_RECONNECT_MS)).toHaveLength(1);
  });

  it("offline, an answer it could not use, or not asked yet: cannot tell, never connected or not", () => {
    const cases: [PlatformsRead, string][] = [
      [peerRead({ far: { available: false, why: "offline", bots: {} } }), "offline"],
      [peerRead({ far: { available: false, why: "unread", bots: {} } }), "unread"],
      [peerRead({}), "unasked"],
      [read(state()), "unasked"], // a bridge older than rule 45: no `peers` at all
    ];
    for (const [r, why] of cases) {
      expect(notConnected(r, "far:demo-bot")).toEqual([]);
      const html = renderToStaticMarkup(<PlatformsBody bot={REMOTE} read={r} />);
      expect(html).toContain(`data-why="${why}"`);
      for (const word of ["Connected", "Disconnected", "pf-none", "pf-discord"]) expect(text(html)).not.toContain(word);
      expect(text(html)).toContain("Other");
    }
    // `available: false` with rows in it (a peer that says both) shows none of them
    const both = peerRead({ far: { available: false, why: "unread", bots: up(state()).far.bots } });
    expect(notConnected(both, "far:demo-bot")).toEqual([]);
  });

  it("lists its platforms, says where it was read and where to run the restart", () => {
    const html = renderToStaticMarkup(<PlatformsBody bot={REMOTE} read={peerRead(up(state()))} />);
    expect(html).toContain('data-testid="pf-discord"');
    expect(text(html)).toContain(t("pf.sourcePeer", { label: "Other" }));
    expect(text(html)).toContain(t("pf.fix.onPeer", { label: "Other" }));
    expect(text(html)).not.toContain(t("pf.source"));
    // the restart names the bot's own profile there: no "another gateway" note for its own name
    const own = renderToStaticMarkup(<PlatformsBody bot={REMOTE} read={peerRead(up(state({ restart: "hermes -p demo-bot gateway restart" })))} />);
    expect(text(own)).not.toContain(t("pf.fix.host", { gateway: "demo-bot" }));
    // a local bot's restart has no "run it on" note
    expect(text(item(state()))).not.toContain("Other");
  });

  it("every language words every peer case", () => {
    for (const l of LANGS) {
      setLang(l);
      for (const why of ["offline", "unread"] as const) {
        const words = text(renderToStaticMarkup(<PlatformsBody bot={REMOTE} read={peerRead({ far: { available: false, why, bots: {} } })} />));
        expect(words).toContain("Other");
        expect(words).not.toMatch(/pf\.[a-z]/);
      }
      const words = text(renderToStaticMarkup(<PlatformsBody bot={REMOTE} read={peerRead(up(state()))} />));
      expect(words).toContain("Other");
      expect(words).not.toMatch(/pf\.[a-z]/);
    }
  });
});
