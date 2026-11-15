import { afterEach, describe, expect, it } from "vitest";
import type { Automation } from "../lib/protocol";
import { setLang } from "../i18n";
import { statusOf } from "./Automations";
import { notUsefulQuote, reasonWords, watchOf, watchSentence, whereOf, type WatchInfo } from "./watch";

const W: WatchInfo = {
  name: "og-outage",
  platform: "slack",
  channels: ["#og", "#ops"],
  what: "posts about an outage",
  interval: "every 5m",
  last_check: 1_800_000_000,
  last_alert: null,
  state: "ok",
  reason: null,
};
const job = (watch: WatchInfo | null, over: Partial<Automation> = {}): Automation =>
  ({
    bot: "kami", id: "w1", name: "og-outage", schedule: "every 5m", next_run_at: null, last_run_at: 1_800_000_000,
    last_status: "ok", enabled: true, paused: false, prompt: "", script: "channel_watch_og-outage.py", deliver: "bot-chat:kami",
    origin: null, created_at: null, last_error: null, repeat: { times: null, completed: 1 }, watch, ...over,
  }) as Automation;

afterEach(() => setLang("en"));

describe("channel watch rows", () => {
  it("reads the watch facts only from a collector job", () => {
    expect(watchOf(job(W))?.name).toBe("og-outage");
    expect(watchOf(job(null))).toBeNull();
    expect(whereOf(W)).toBe("Slack #og, #ops");
    expect(whereOf({ ...W, platform: null, channels: [] })).toBe("");
  });

  it("never shows a watch the bot can't read as done, even when the run itself said ok", () => {
    const bad = { ...W, state: "not_readable" as const, reason: { code: "not_in_channel", channel: "C0123" } };
    expect(statusOf(job(W))).toBe("ok");
    expect(statusOf(job(bad))).toBe("failed");
    expect(statusOf(job(bad, { paused: true }))).toBe("paused");
  });

  it("says why it can't read the channel, by the collector's reason", () => {
    const r = (code: string, channel: string | null = null) => reasonWords({ ...W, state: "not_readable", reason: { code, channel } });
    expect(r("not_in_channel", "C0123")).toContain("C0123");
    expect(r("missing_access")).toContain("#og, #ops");
    expect(r("invalid_auth")).toContain("Slack bot token was rejected");
    expect(r("missing_scope")).toContain("channels:history");
    expect(r("no_token")).toContain("No Slack bot token");
    expect(r("config")).toContain("settings file");
    expect(r("exit_1")).toBe(r("failed"));
    setLang("ko");
    expect(r("not_in_channel", "C0123")).toContain("C0123");
    expect(r("not_in_channel", "C0123")).not.toMatch(/[A-Za-z]{4,}/);
  });

  it("fills one sentence for the bot in each language", () => {
    const p = { platform: "discord" as const, channel: " #deploys ", what: "someone asks for a deploy.", minutes: 15 };
    expect(watchSentence(p)).toBe("Watch Discord #deploys and tell me first when a post is about: someone asks for a deploy. Check every 15 min.");
    setLang("ko");
    expect(watchSentence({ ...p, what: "배포 요청" })).toBe("Discord #deploys 채널을 지켜보다가 배포 요청 관련 글이 올라오면 나한테 먼저 알려 줘. 15분마다 확인해 줘.");
    for (const l of ["ja", "zh"] as const) {
      setLang(l);
      const s = watchSentence(p);
      expect(s).toContain("#deploys");
      expect(s).not.toContain("{");
    }
  });
});

describe("Not useful quote", () => {
  it("quotes the item verbatim: markdown marks, __init__ and backticks stay; only whitespace is collapsed", () => {
    expect(notUsefulQuote("og down: `__init__` failed in #og\n**see** the thread")).toBe(
      "og down: `__init__` failed in #og **see** the thread",
    );
  });
  it("caps a long item at 300 characters with an ellipsis", () => {
    const q = notUsefulQuote("x".repeat(400));
    expect(q).toHaveLength(300);
    expect(q.endsWith("…")).toBe(true);
  });
});
