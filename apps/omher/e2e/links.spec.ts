// Link chips: a bare URL in a message becomes the service's mark plus a short label (Slack threads named by
// their channel when the bot knows it), a link with its own text keeps it after the mark, a lookalike host
// stays a plain link, clicks go through the opener, and a chip never makes its line taller.
import { expect, test, type Page } from "@playwright/test";
import LINKS from "./fixtures/links.json" with { type: "json" };

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "lk1") res(msg);
    };
    ws.send(JSON.stringify({ id: "lk1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

/** Records what the app asked the opener to open (window.open in the browser build). */
async function catchOpens(page: Page): Promise<string[]> {
  const opened: string[] = [];
  await page.exposeFunction("__omherOpened", (u: string) => opened.push(u));
  await page.addInitScript(() => {
    window.open = ((u: string) => {
      (window as unknown as { __omherOpened: (u: string) => void }).__omherOpened(String(u));
      return null;
    }) as typeof window.open;
  });
  return opened;
}

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

const slackBubble = (page: Page) => page.getByTestId("bubble-bot").filter({ hasText: "항목별 Slack 스레드 링크입니다." });
const servicesBubble = (page: Page) => page.getByTestId("bubble-bot").filter({ hasText: "Links from today's work:" });

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("six bare Slack thread URLs become Slack chips named by their channel, the URL in the tooltip", async ({ page }) => {
  await open(page);
  const b = slackBubble(page);
  await b.scrollIntoViewIfNeeded();
  const chips = b.getByTestId("link-chip");
  await expect(chips).toHaveCount(7);
  // channels the bot knows get their name; the one it does not know keeps the fallback
  await expect(chips.locator(".lk-t")).toHaveText(["#docs-agent", "#product-docs", "Slack message", "#product-docs", "#product-docs", "#lab", "#lab"]);
  for (const c of await chips.all()) {
    await expect(c).toHaveAttribute("data-service", "slack");
    await expect(c.locator("svg.src-ic-slack")).toHaveCount(1); // the same Slack mark as the header's other places
    expect(await c.getAttribute("title")).toMatch(/^https:\/\/example\.slack\.com\/archives\/C[0-9A-Z]+\/p\d{16}$/);
  }
  await expect(b).not.toContainText("https://example.slack.com"); // no raw URL left in the text
  // each chip stays on its item's line: one line box, its mark left of the label and on the label's middle
  const geo = await chips.evaluateAll((els) =>
    els.map((a) => {
      const rects = a.getClientRects();
      const ic = a.querySelector("svg")!.getBoundingClientRect();
      const t = a.querySelector(".lk-t")!.getBoundingClientRect();
      const li = a.closest("li")!;
      const first = document.createRange();
      first.selectNodeContents(li);
      return { lines: rects.length, markLeft: ic.right <= t.left + 0.5, mid: Math.abs(ic.top + ic.height / 2 - (t.top + t.height / 2)), icon: ic.width, liTop: li.getBoundingClientRect().top, top: t.top };
    }),
  );
  for (const g of geo) {
    expect(g.lines).toBe(1);
    expect(g.markLeft).toBe(true);
    expect(g.mid).toBeLessThanOrEqual(3);
    expect(g.icon).toBeGreaterThanOrEqual(12);
    expect(g.icon).toBeLessThanOrEqual(13);
  }
  // items 1 and 2 had their URL pushed onto a line of its own; the chip now fits on the item's first line
  expect(geo[0].top - geo[0].liTop).toBeLessThan(10);
  expect(geo[1].top - geo[1].liTop).toBeLessThan(10);
});

test("chips per service: mark, kind and label; a lookalike host stays a plain link", async ({ page }) => {
  await open(page);
  const b = servicesBubble(page);
  await b.scrollIntoViewIfNeeded();
  const rows = await b.getByTestId("link-chip").evaluateAll((els) =>
    els.map((a) => [a.getAttribute("data-service"), a.getAttribute("data-kind"), a.querySelector(".lk-t")!.textContent, a.querySelector("svg")!.getAttribute("data-brand") ?? a.querySelector("svg")!.getAttribute("data-src")]),
  );
  expect(rows).toEqual([
    ["github", "pr", "rlaope/oh-my-hermes#2657", "github"],
    ["github", "issue", "#2604", "github"],
    ["github", "commit", "rlaope/oh-my-hermes@c74e964", "github"],
    ["github", "run", "CI run", "github"],
    ["github", "file", "runs.ts:41", "github"],
    ["github", "repo", "rlaope/oh-my-hermes", "github"],
    ["github", "release", "rlaope/oh-my-hermes omher-v0.2.2", "github"],
    ["slack", "thread", "#docs-agent · thread", "slack"],
    ["discord", "message", "#cron", "discord"],
    ["googledocs", "document", "Google Docs", "googledocs"],
    ["googlesheets", "spreadsheets", "Google Sheets", "googlesheets"],
    ["googleslides", "presentation", "Google Slides", "googleslides"],
    ["googledrive", "folder", "Drive folder", "googledrive"],
    ["googlemeet", "meeting", "Meet · abc-defg-hij", "googlemeet"],
    ["googlecalendar", "event", "Calendar event", "googlecalendar"],
    ["x", "post", "@NousResearch · post", "x"],
    ["linkedin", "profile", "in/demo", "linkedin"],
    ["youtube", "video", "YouTube · video · 1:23", "youtube"],
    ["notion", "page", "Notion · Release Notes", "notion"],
    ["linear", "issue", "OG-123", "linear"],
    ["figma", "design", "Figma · omher chat", "figma"],
    ["npm", "package", "npm · @tauri-apps/api", "npm"],
  ]);
  const plain = b.getByTestId("link-plain");
  await expect(plain).toHaveCount(1);
  await expect(plain).toHaveText("github.com.evil.io/rlaope/oh-my-hermes/pull/1");
  await expect(plain.locator("svg")).toHaveCount(0);
  await expect(plain).toHaveAttribute("title", "https://github.com.evil.io/rlaope/oh-my-hermes/pull/1");
  // a brand colour stays on the mark: every label is the same muted text colour
  const colors = await b.getByTestId("link-chip").evaluateAll((els) => [...new Set(els.map((a) => getComputedStyle(a.querySelector(".lk-t")!).color))]);
  expect(colors).toHaveLength(1);
  // a mark drawn in the text colour (GitHub, X, Notion, LinkedIn) is ink, not the muted label colour
  const marks = await b.locator('[data-testid=link-chip] svg.brand-ic-x, [data-testid=link-chip] svg.brand-ic-notion').evaluateAll((els) =>
    els.map((e) => [getComputedStyle(e).color]),
  );
  expect(marks).toHaveLength(2);
  for (const [mark] of marks) expect(mark).not.toBe(colors[0]);
  // the user's own message: its two URLs are chips too
  const mine = page.getByTestId("bubble-user").filter({ hasText: "Can you check" });
  await expect(mine.getByTestId("link-chip").locator(".lk-t")).toHaveText(["rlaope/oh-my-hermes#2657", "#docs-agent"]);
});

test("work-tool chips: Jira, Confluence, Sentry, Asana, Todoist, ClickUp, GitLab, and an Obsidian note that opens nothing", async ({ page }) => {
  const opened = await catchOpens(page);
  await open(page);
  const text = [
    "Tools today:",
    "- Ticket https://acme.atlassian.net/browse/ACME-123 on https://acme.atlassian.net/jira/software/projects/ACME/boards/42",
    "- Spec https://acme.atlassian.net/wiki/spaces/ENG/pages/123456/Release+Checklist",
    "- Crash https://acme.sentry.io/issues/4512345678/",
    "- Tasks https://app.asana.com/0/1205000000000001/1205000000000002, https://app.todoist.com/app/task/write-release-notes-6Xv2Q9pFg3J8mRcW and https://app.clickup.com/t/9012345678/DEV-123",
    "- Review https://gitlab.com/acme/platform/billing/api/-/merge_requests/7 after https://gitlab.com/acme/widgets/-/pipelines/1234567890",
    "- Notes obsidian://open?vault=Work&file=Projects%2FLaunch%20Plan.md",
    "- Not GitLab: https://gitlab.com.evil.io/acme/widgets/-/issues/1",
  ].join("\n");
  await mock("mock.emit", { events: [{ event: "message", bot: "kami", id: "lk-tools", text }] });
  const b = page.getByTestId("bubble-bot").filter({ hasText: "Tools today:" });
  await b.scrollIntoViewIfNeeded();
  const rows = await b.getByTestId("link-chip").evaluateAll((els) =>
    els.map((a) => [a.tagName, a.getAttribute("data-service"), a.getAttribute("data-kind"), a.querySelector(".lk-t")!.textContent, a.querySelector("svg")!.getAttribute("data-brand")]),
  );
  expect(rows).toEqual([
    ["A", "jira", "issue", "ACME-123", "jira"],
    ["A", "jira", "board", "Jira board · ACME", "jira"],
    ["A", "confluence", "page", "Confluence · Release Checklist", "confluence"],
    ["A", "sentry", "issue", "Sentry issue · 4512345678", "sentry"],
    ["A", "asana", "task", "Asana task", "asana"],
    ["A", "todoist", "task", "Todoist · write release notes", "todoist"],
    ["A", "clickup", "task", "DEV-123", "clickup"],
    ["A", "gitlab", "mr", "acme/…/api!7", "gitlab"],
    ["A", "gitlab", "pipeline", "GitLab pipeline · 1234567890", "gitlab"],
    ["SPAN", "obsidian", "note", "Obsidian · Launch Plan", "obsidian"],
  ]);
  // each new mark is drawn (a path with a shape), 12px like the others
  const sizes = await b.locator("[data-testid=link-chip] svg.brand-ic").evaluateAll((els) => els.map((e) => [e.getBoundingClientRect().width, (e.querySelector("path")?.getAttribute("d") ?? "").length > 100]));
  expect(sizes).toHaveLength(10);
  for (const [w, drawn] of sizes) {
    expect(w).toBeGreaterThanOrEqual(12);
    expect(w).toBeLessThanOrEqual(13);
    expect(drawn).toBe(true);
  }
  // near-black brand colours (Confluence, Sentry) are drawn in the ink colour, like GitHub's
  const ink = await b.locator("svg.brand-ic-confluence path, svg.brand-ic-sentry path").evaluateAll((els) => els.map((e) => e.getAttribute("fill")));
  expect(ink).toEqual(["currentColor", "currentColor"]);
  // the Obsidian note is text: no href, the URL in its tooltip, and a click opens nothing
  const note = b.locator('[data-testid=link-chip][data-service="obsidian"]');
  await expect(note).toHaveAttribute("title", "obsidian://open?vault=Work&file=Projects%2FLaunch%20Plan.md");
  expect(await note.getAttribute("href")).toBeNull();
  await note.click();
  await b.locator('[data-testid=link-chip][data-service="jira"]').first().click();
  await expect.poll(() => opened).toEqual(["https://acme.atlassian.net/browse/ACME-123"]);
  // a lookalike stays a plain link named by its real host
  await expect(b.getByTestId("link-plain")).toHaveText("gitlab.com.evil.io/acme/widgets/-/issues/1");
  // the address is not shown as text, only read out to assistive tech (visually hidden)
  await expect(note.locator(".vh")).toHaveText("obsidian://open?vault=Work&file=Projects%2FLaunch%20Plan.md");
  expect(await note.locator(".vh").evaluate((e) => e.getBoundingClientRect().width)).toBeLessThanOrEqual(1);
  await expect(b.locator("a[href^='obsidian'], a[href^='OBSIDIAN']")).toHaveCount(0);
});

test("labels are readable at rest and ink on hover; no pill fill at rest", async ({ page }) => {
  await open(page);
  const chip = slackBubble(page).getByTestId("link-chip").first();
  await chip.scrollIntoViewIfNeeded();
  const lum = (c: string) => {
    const [r, g, b] = c.match(/[\d.]+/g)!.slice(0, 3).map((v) => {
      const s = Number(v) / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a: string, b: string) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };
  for (const theme of ["dark", "light"] as const) {
    await page.evaluate(async (t) => {
      const m = await import(/* @vite-ignore */ "/src/state/store.ts");
      m.getStore().actions.setTheme(t);
    }, theme);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await page.mouse.move(1, 1);
    // the colour and the hover fill ease out over 0.12s; a loaded runner can still be mid-fade after a fixed wait
    await expect
      .poll(() => chip.evaluate((a) => getComputedStyle(a).backgroundColor), { timeout: 5000 })
      .toMatch(/^(transparent|rgba\(0, 0, 0, 0\))$/);
    await page.waitForTimeout(300); // the text colour has settled too
    const rest = await chip.evaluate((a) => {
      const bub = a.closest(".b")!;
      return { color: getComputedStyle(a).color, bg: getComputedStyle(a).backgroundColor, bubble: getComputedStyle(bub).backgroundColor, ink: getComputedStyle(bub).color, border: getComputedStyle(a).borderTopWidth };
    });
    expect(rest.bg).toMatch(/^(transparent|rgba\(0, 0, 0, 0\))$/);
    expect(rest.border).toBe("0px");
    expect(ratio(rest.color, rest.bubble), `${theme} ${JSON.stringify(rest)}`).toBeGreaterThanOrEqual(4.5);
    await chip.hover();
    await expect.poll(() => chip.evaluate((a) => getComputedStyle(a).color)).not.toBe(rest.color);
  }
  await page.evaluate(() => localStorage.removeItem("omher.theme"));
});

test("a chip opens its URL through the opener, once, and a lookalike link is not routed as a service", async ({ page }) => {
  const opened = await catchOpens(page);
  await open(page);
  const chip = slackBubble(page).getByTestId("link-chip").first();
  await chip.scrollIntoViewIfNeeded();
  await chip.click();
  await expect.poll(() => opened).toEqual(["https://example.slack.com/archives/C0000000001/p1700000000000001"]);
  const yt = servicesBubble(page).locator('[data-testid=link-chip][data-service="youtube"]');
  await yt.click();
  await expect.poll(() => opened.length).toBe(2);
  expect(opened[1]).toBe("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=83s");
  const plain = servicesBubble(page).getByTestId("link-plain");
  await expect(plain).toHaveAttribute("data-service", "web");
  await expect(plain).toHaveAttribute("href", "https://github.com.evil.io/rlaope/oh-my-hermes/pull/1");
});

test("chips do not change the bubble's line height", async ({ page }) => {
  await open(page);
  const text = "one https://github.com/rlaope/oh-my-hermes/pull/2657 two https://meet.google.com/abc-defg-hij three https://youtu.be/dQw4w9WgXcQ?t=83";
  await mock("mock.emit", { events: [{ event: "message", bot: "kami", id: "lk-h1", text: "one two three, a line with no links" }, { event: "message", bot: "kami", id: "lk-h2", text }] });
  const [plain, chipped] = [page.getByTestId("bubble-bot").filter({ hasText: "a line with no links" }), page.getByTestId("bubble-bot").filter({ has: page.getByTestId("link-chip") }).filter({ hasText: /^one / })];
  await expect(chipped.getByTestId("link-chip")).toHaveCount(3);
  const h = (l: typeof plain) => l.locator(".b p").evaluate((p) => p.getBoundingClientRect().height);
  expect(await h(chipped)).toBe(await h(plain));
});

test("a long label ends in an ellipsis and keeps the whole URL in its tooltip", async ({ page }) => {
  await open(page);
  const url = "https://github.com/a-really-long-organisation-name/an-even-longer-repository-name-for-tests/pull/123456";
  await mock("mock.emit", { events: [{ event: "message", bot: "kami", id: "lk-long", text: `see ${url}` }] });
  const chip = page.getByTestId("bubble-bot").filter({ hasText: "see" }).last().getByTestId("link-chip");
  await expect(chip).toHaveAttribute("title", url);
  const t = await chip.locator(".lk-t").evaluate((e) => ({ over: e.scrollWidth > e.clientWidth, ellipsis: getComputedStyle(e).textOverflow }));
  expect(t).toEqual({ over: true, ellipsis: "ellipsis" });
});

test("a markdown link with its own text keeps that text, with the mark before it", async ({ page }) => {
  await open(page);
  await mock("mock.emit", { events: [{ event: "message", bot: "kami", id: "lk-md", text: "Read [the retry PR](https://github.com/rlaope/oh-my-hermes/pull/2657) first." }] });
  const a = page.getByTestId("bubble-bot").filter({ hasText: "Read the retry PR first." }).getByTestId("link-text");
  await expect(a).toHaveText("the retry PR");
  await expect(a.locator("svg[data-brand=github]")).toHaveCount(1);
  await expect(a).toHaveAttribute("title", "https://github.com/rlaope/oh-my-hermes/pull/2657");
});

test("the plan node drawer lists the handoff's links as a Links block of chips", async ({ page }) => {
  await open(page);
  await page.getByTestId("places").click();
  await page.getByTestId("panel-tab-runs").click();
  const t = page.getByTestId("run-list-toggle");
  await expect(t).toBeVisible();
  if ((await t.getAttribute("aria-expanded")) === "false") await t.click();
  await page.locator('[data-testid="run-row"][title*="Codex coexistence fixes"]').click();
  await page.getByTestId("run-graph-box").locator('[data-testid="run-node"][data-node="t2-status-update"]').click();
  const drawer = page.getByTestId("run-drawer");
  const block = drawer.getByTestId("run-links");
  await expect(block).toBeVisible();
  await expect(block.locator(".lk-bt")).toHaveText("Links");
  // a long list shows its first 10, then "Show all N"
  await expect(block.locator("a")).toHaveCount(10);
  await block.getByTestId("run-links-more").click();
  await expect(block.getByTestId("run-links-more")).toHaveCount(0);
  const services = await block.locator("a").evaluateAll((els) => els.map((a) => a.getAttribute("data-service")));
  expect(services).toContain("github");
  for (const s of ["slack", "discord", "googledocs", "googlemeet", "x", "linkedin", "youtube", "notion", "linear", "figma", "npm", "web"]) expect(services).toContain(s);
  expect(new Set(await block.locator("a").evaluateAll((els) => els.map((a) => a.getAttribute("href")))).size).toBe(services.length); // each once
  expect(services.length).toBe(23);
  // a node with no links has no block
  await page.getByTestId("run-graph-box").locator('[data-testid="run-node"][data-node="t1-discovery"]').click();
  await expect(drawer.getByTestId("run-links")).toHaveCount(0);
});

test("the seed carries the owner's six-link answer verbatim", () => {
  expect(LINKS.owner.match(/https:\/\/example\.slack\.com\/archives\//g)).toHaveLength(7);
});
