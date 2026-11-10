import { describe, expect, it } from "vitest";
import { classifyLink, clock, findUrls, linksIn, parseT } from "./linkKinds";

// [url, service, kind, label, meta subset?]
type Case = [string, string, string, string, Record<string, string>?];

const CASES: Case[] = [
  // ---- GitHub
  ["https://github.com/rlaope/oh-my-hermes/pull/2657", "github", "pr", "rlaope/oh-my-hermes#2657", { owner: "rlaope", repo: "oh-my-hermes", number: "2657" }],
  ["https://github.com/rlaope/oh-my-hermes/pull/2657/files?diff=split", "github", "pr", "rlaope/oh-my-hermes#2657"],
  ["https://github.com/rlaope/oh-my-hermes/pull/2657#issuecomment-123", "github", "pr", "rlaope/oh-my-hermes#2657"],
  ["https://www.github.com/rlaope/oh-my-hermes/pull/12", "github", "pr", "rlaope/oh-my-hermes#12"],
  ["http://github.com/rlaope/oh-my-hermes/pull/12", "github", "pr", "rlaope/oh-my-hermes#12"],
  ["https://GitHub.com/rlaope/oh-my-hermes/pull/12", "github", "pr", "rlaope/oh-my-hermes#12"],
  ["https://m.github.com/rlaope/oh-my-hermes/pull/12", "github", "pr", "rlaope/oh-my-hermes#12"],
  ["https://github.com/rlaope/oh-my-hermes/issues/2604", "github", "issue", "#2604", { number: "2604" }],
  ["https://github.com/rlaope/oh-my-hermes/issues", "github", "repo", "rlaope/oh-my-hermes"],
  ["https://github.com/rlaope/oh-my-hermes/commit/c74e9646a1b2c3d4e5f60718293a4b5c6d7e8f90", "github", "commit", "rlaope/oh-my-hermes@c74e964", { sha: "c74e9646a1b2c3d4e5f60718293a4b5c6d7e8f90" }],
  ["https://github.com/rlaope/oh-my-hermes/commit/c74e964", "github", "commit", "rlaope/oh-my-hermes@c74e964"],
  ["https://github.com/rlaope/oh-my-hermes", "github", "repo", "rlaope/oh-my-hermes"],
  ["https://github.com/rlaope/oh-my-hermes/", "github", "repo", "rlaope/oh-my-hermes"],
  ["https://github.com/rlaope/oh-my-hermes.git", "github", "repo", "rlaope/oh-my-hermes.git"],
  ["https://github.com/rlaope", "github", "user", "@rlaope"],
  ["https://github.com/rlaope/oh-my-hermes/releases/tag/omher-v0.2.2", "github", "release", "rlaope/oh-my-hermes omher-v0.2.2", { tag: "omher-v0.2.2" }],
  ["https://github.com/rlaope/oh-my-hermes/releases", "github", "releases", "rlaope/oh-my-hermes releases"],
  ["https://github.com/rlaope/oh-my-hermes/actions/runs/42615558060/job/129150631784", "github", "run", "CI run", { run: "42615558060" }],
  ["https://github.com/rlaope/oh-my-hermes/actions/runs/42615558060/job/129150631784/attempts/3/logs", "github", "run", "CI run"],
  ["https://github.com/rlaope/oh-my-hermes/actions", "github", "actions", "rlaope/oh-my-hermes actions"],
  ["https://github.com/rlaope/oh-my-hermes/blob/main/apps/omher/src/lib/runs.ts#L41", "github", "file", "runs.ts:41", { path: "apps/omher/src/lib/runs.ts", line: "41", ref: "main" }],
  ["https://github.com/rlaope/oh-my-hermes/blob/main/apps/omher/src/lib/runs.ts#L41-L58", "github", "file", "runs.ts:41-58"],
  ["https://github.com/rlaope/oh-my-hermes/blob/c74e964/README.md", "github", "file", "README.md"],
  ["https://github.com/rlaope/oh-my-hermes/tree/main/apps/omher", "github", "folder", "omher/"],
  ["https://gist.github.com/rlaope/0f1e2d3c4b5a6978", "github", "gist", "gist · rlaope", { id: "0f1e2d3c4b5a6978" }],
  ["https://github.com/rlaope/oh-my-hermes/compare/main...feat/omher-link-chips", "github", "compare", "compare main...feat/omher-link-chips"],
  ["https://github.com/rlaope/oh-my-hermes/discussions/88", "github", "discussion", "rlaope/oh-my-hermes discussion #88"],
  ["https://github.com/settings/tokens", "github", "page", "GitHub"],
  ["https://github.com/", "github", "page", "GitHub"],
  // ---- Slack
  ["https://sionicai.slack.com/archives/C0BLC924P1P/p1794195216893139", "slack", "message", "Slack message", { channel: "C0BLC924P1P", ts: "1794195216.893139", workspace: "sionicai" }],
  ["https://sionicai.slack.com/archives/C0BLC924P1P/p1794195216893139?thread_ts=1794195216.893139&cid=C0BLC924P1P", "slack", "thread", "Slack · thread", { thread: "1794195216.893139" }],
  ["https://sionicai.slack.com/archives/C0BLC924P1P", "slack", "channel", "Slack channel", { channel: "C0BLC924P1P" }],
  ["https://app.slack.com/client/T058B1MTT4Y/C0BLC924P1P", "slack", "channel", "Slack channel", { channel: "C0BLC924P1P" }],
  ["https://app.slack.com/client/T058B1MTT4Y/C0BLC924P1P/thread/C0BLC924P1P-1794195216.893139", "slack", "thread", "Slack · thread", { thread: "1794195216.893139" }],
  ["https://slack.com/app_redirect?channel=C0BLC924P1P&team=T058B1MTT4Y", "slack", "channel", "Slack channel", { channel: "C0BLC924P1P" }],
  ["https://sionicai.slack.com/", "slack", "workspace", "Slack · sionicai"],
  // ---- Discord
  ["https://discord.com/channels/1544259130674515988/1544259371528232980", "discord", "channel", "Discord channel", { guild: "1544259130674515988", channel: "1544259371528232980" }],
  ["https://discord.com/channels/1544259130674515988/1544259371528232980/1566453709896941710", "discord", "message", "Discord message", { message: "1566453709896941710" }],
  ["https://canary.discord.com/channels/1/2/3", "discord", "message", "Discord message"],
  ["https://ptb.discord.com/channels/1/2", "discord", "channel", "Discord channel"],
  ["https://discordapp.com/channels/1/2", "discord", "channel", "Discord channel"],
  ["https://discord.com/channels/1544259130674515988", "discord", "server", "Discord server"],
  ["https://discord.com/channels/@me/123", "discord", "channel", "Discord channel"],
  ["https://discord.gg/omh", "discord", "invite", "Discord invite · omh", { invite: "omh" }],
  ["https://discord.com/invite/omh", "discord", "invite", "Discord invite · omh"],
  // ---- Google
  ["https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit", "googledocs", "document", "Google Docs", { id: "1AbCdEfGhIjKlMnOpQrStUvWxYz" }],
  ["https://docs.google.com/document/u/1/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit?usp=sharing", "googledocs", "document", "Google Docs", { id: "1AbCdEfGhIjKlMnOpQrStUvWxYz" }],
  ["https://docs.google.com/spreadsheets/d/1ZyX/edit#gid=0", "googlesheets", "spreadsheets", "Google Sheets", { id: "1ZyX" }],
  ["https://docs.google.com/spreadsheets/u/1/d/1ZyX/edit#gid=0", "googlesheets", "spreadsheets", "Google Sheets", { id: "1ZyX" }],
  ["https://docs.google.com/presentation/d/1SlIdEs/edit", "googleslides", "presentation", "Google Slides"],
  ["https://docs.google.com/forms/d/e/1FAIpQL/viewform", "googleforms", "forms", "Google Forms", { id: "1FAIpQL" }],
  ["https://forms.gle/abc123", "googleforms", "forms", "Google Forms"],
  ["https://drive.google.com/file/d/1FiLeId/view?usp=drive_link", "googledrive", "file", "Drive file", { id: "1FiLeId" }],
  ["https://drive.google.com/drive/folders/1FoLdErIdXyZ", "googledrive", "folder", "Drive folder", { id: "1FoLdErIdXyZ" }],
  ["https://drive.google.com/drive/u/1/folders/1FoLdEr", "googledrive", "folder", "Drive folder"],
  ["https://drive.google.com/open?id=1FiLeId", "googledrive", "file", "Drive file"],
  ["https://calendar.google.com/calendar/event?eid=ZXZlbnQxMjM", "googlecalendar", "event", "Calendar event", { eid: "ZXZlbnQxMjM" }],
  ["https://calendar.google.com/calendar/u/0/r/eventedit/abc", "googlecalendar", "event", "Calendar event"],
  ["https://calendar.google.com/calendar/u/0/r", "googlecalendar", "page", "Google Calendar"],
  ["https://meet.google.com/abc-defg-hij", "googlemeet", "meeting", "Meet · abc-defg-hij", { code: "abc-defg-hij" }],
  ["https://meet.google.com/abc-defg-hij?authuser=1", "googlemeet", "meeting", "Meet · abc-defg-hij"],
  ["https://mail.google.com/mail/u/0/#inbox/FMfcgzQXJWDsKmzvNtqgPpLsZ", "gmail", "thread", "Gmail thread"],
  ["https://mail.google.com/mail/u/0/#inbox", "gmail", "page", "Gmail"],
  ["https://www.google.com/maps/place/Gangnam+Station/@37.49,127.02,17z", "googlemaps", "place", "Maps · Gangnam Station"],
  ["https://maps.app.goo.gl/AbCdEf", "googlemaps", "place", "Google Maps"],
  ["https://www.google.com/search?q=hermes+agent", "google", "search", "Google · hermes agent", { q: "hermes agent" }],
  ["https://www.google.co.kr/search?q=omher", "google", "search", "Google · omher"],
  // ---- X / Twitter
  ["https://x.com/NousResearch/status/1854012345678901234", "x", "post", "@NousResearch · post", { user: "NousResearch", post: "1854012345678901234" }],
  ["https://twitter.com/NousResearch/status/1854012345678901234?s=20", "x", "post", "@NousResearch · post"],
  ["https://mobile.twitter.com/NousResearch/status/1854012345678901234", "x", "post", "@NousResearch · post"],
  ["https://x.com/i/web/status/1854012345678901234", "x", "post", "X post"],
  ["https://x.com/NousResearch", "x", "profile", "@NousResearch"],
  ["https://twitter.com/home", "x", "page", "X"],
  // ---- LinkedIn
  ["https://www.linkedin.com/in/khope", "linkedin", "profile", "in/khope", { profile: "khope" }],
  ["https://kr.linkedin.com/in/khope/", "linkedin", "profile", "in/khope"],
  ["https://www.linkedin.com/company/sionic-ai/", "linkedin", "company", "LinkedIn · sionic-ai"],
  ["https://www.linkedin.com/jobs/view/4012345678/", "linkedin", "job", "LinkedIn job", { job: "4012345678" }],
  ["https://www.linkedin.com/posts/khope_omher-activity-7260000000000000000-AbCd", "linkedin", "post", "LinkedIn post"],
  ["https://www.linkedin.com/feed/update/urn:li:activity:7260000000000000000/", "linkedin", "post", "LinkedIn post"],
  // ---- YouTube
  ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube", "video", "YouTube · video", { video: "dQw4w9WgXcQ" }],
  ["https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=83s", "youtube", "video", "YouTube · video · 1:23", { t: "83" }],
  ["https://m.youtube.com/watch?v=dQw4w9WgXcQ&feature=share", "youtube", "video", "YouTube · video"],
  ["https://youtu.be/dQw4w9WgXcQ?t=83", "youtube", "video", "YouTube · video · 1:23"],
  ["https://youtu.be/dQw4w9WgXcQ?si=AbCd&t=1h2m3s", "youtube", "video", "YouTube · video · 1:02:03"],
  ["https://www.youtube.com/shorts/AbCdEfGhIjK", "youtube", "short", "YouTube · short"],
  ["https://www.youtube.com/playlist?list=PL1234567890", "youtube", "playlist", "YouTube · playlist", { list: "PL1234567890" }],
  ["https://www.youtube.com/@NousResearch", "youtube", "channel", "@NousResearch"],
  ["https://www.youtube.com/channel/UC1234567890", "youtube", "channel", "YouTube channel"],
  ["https://www.youtube.com/embed/dQw4w9WgXcQ?start=30", "youtube", "video", "YouTube · video · 0:30"],
  ["https://music.youtube.com/watch?v=dQw4w9WgXcQ", "youtube", "video", "YouTube · video"],
  // ---- Notion, Linear, Figma, npm
  ["https://www.notion.so/Release-Notes-0f1e2d3c4b5a69788796a5b4c3d2e1f0", "notion", "page", "Notion · Release Notes"],
  ["https://sionic.notion.site/Hiring-0f1e2d3c4b5a69788796a5b4c3d2e1f0", "notion", "page", "Notion · Hiring"],
  ["https://linear.app/sionic/issue/OG-123/retry-budget", "linear", "issue", "OG-123", { issue: "OG-123", team: "sionic" }],
  ["https://www.figma.com/design/AbC123xYz/omher-chat?node-id=1-2", "figma", "design", "Figma · omher chat", { key: "AbC123xYz" }],
  ["https://www.npmjs.com/package/@tauri-apps/api", "npm", "package", "npm · @tauri-apps/api", { package: "@tauri-apps/api" }],
  ["https://www.npmjs.com/package/vite", "npm", "package", "npm · vite"],
  // ---- lookalikes and anything else: a plain web link named by its real host
  ["https://github.com.evil.io/rlaope/oh-my-hermes/pull/1", "web", "web", "github.com.evil.io/rlaope/oh-my-hermes/pull/1"],
  ["https://evilgithub.com/rlaope/x/pull/1", "web", "web", "evilgithub.com/rlaope/x/pull/1"],
  ["https://slack.com.attacker.net/archives/C1/p1794195216893139", "web", "web", "slack.com.attacker.net/archives/C1/p1794195216893…"],
  ["https://notslack.com/archives/C1", "web", "web", "notslack.com/archives/C1"],
  ["https://discord.com.evil.io/channels/1/2", "web", "web", "discord.com.evil.io/channels/1/2"],
  ["https://docs.google.com.evil.io/document/d/1", "web", "web", "docs.google.com.evil.io/document/d/1"],
  ["https://youtube.com.example.org/watch?v=dQw4w9WgXcQ", "web", "web", "youtube.com.example.org/watch"],
  ["https://x.com.evil.io/NousResearch", "web", "web", "x.com.evil.io/NousResearch"],
  ["https://github.com@evil.io/rlaope/x/pull/1", "web", "web", "evil.io/rlaope/x/pull/1"],
  ["https://www.example.com/", "web", "web", "example.com"],
  ["https://omher.app/docs/install", "web", "web", "omher.app/docs/install"],
];

describe("classifyLink", () => {
  it("has at least 60 cases", () => expect(CASES.length).toBeGreaterThanOrEqual(60));
  it.each(CASES)("%s", (url, service, kind, label, meta) => {
    const got = classifyLink(url)!;
    expect(got).not.toBeNull();
    expect([got.service, got.kind, got.label]).toEqual([service, kind, label]);
    if (meta) expect(got.meta).toMatchObject(meta);
  });
  it("is null for anything that is not http(s)", () => {
    for (const u of ["javascript:alert(1)", "mailto:a@b.c", "file:///etc/passwd", "slack://channel?id=C1", "not a url", ""]) {
      expect(classifyLink(u)).toBeNull();
    }
  });
});

describe("times and URL finding", () => {
  it("reads t= forms and prints a clock", () => {
    expect([parseT("83"), parseT("83s"), parseT("1m23s"), parseT("1h2m3s"), parseT("x"), parseT(null)]).toEqual([83, 83, 83, 3723, null, null]);
    expect([clock(83), clock(3723), clock(5)]).toEqual(["1:23", "1:02:03", "0:05"]);
  });
  it("leaves sentence punctuation out of a bare URL and keeps balanced brackets", () => {
    expect(findUrls("see https://x.com/a/status/1. and (https://github.com/o/r).").map((u) => u.url)).toEqual([
      "https://x.com/a/status/1",
      "https://github.com/o/r",
    ]);
    expect(findUrls("https://en.wikipedia.org/wiki/Foo_(bar)").map((u) => u.url)).toEqual(["https://en.wikipedia.org/wiki/Foo_(bar)"]);
  });
  it("lists a handoff's links once, from bare and markdown links, skipping code", () => {
    const md = "PR [#12](https://github.com/o/r/pull/12) and https://github.com/o/r/pull/12 again, `https://in.code/x`\n```\nhttps://in.fence/y\n```\nhttps://meet.google.com/abc-defg-hij";
    expect(linksIn(md)).toEqual(["https://github.com/o/r/pull/12", "https://meet.google.com/abc-defg-hij"]);
  });
});
