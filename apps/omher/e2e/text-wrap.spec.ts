// Short labels never break inside a word, in every UI language (en, ko, ja, zh). A bot card's status read "연결" on
// one line and "됨" on the next beside the `default` chip: the Korean rule's `overflow-wrap: anywhere` let the status
// shrink to one syllable wide, and ja/zh break between any two characters. At every card width the grid gives, from
// the 900px minimum window up: each card's status word, profile chip and "In list" / "Add to list" label sit on one
// line, the corner label clears the name and the status line, and no short label on the bots page, a bot's page, the
// agents, plugins or apps pages reads on two lines (the bot page's stat captions included).
// Shots with OMHER_SHOTS=<dir> (OMHER_SHOT_TAG=after by default).
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";
const LANGS = ["en", "ko", "ja", "zh"] as const;
const BOTS = ["kami", "friren", "default", "omh-tui"];

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "tw1", op, ...params }));
  });
  ws.close();
}

test.use({ colorScheme: "dark" });

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function open(page: Page, lang: string) {
  await page.addInitScript((l) => {
    localStorage.setItem("omher.lang", l);
    // Friren off the sidebar list: its card shows "Add to list", the longer of the two corner labels
    localStorage.setItem("omher.roster", JSON.stringify(["kami", "default", "omh-tui"]));
  }, lang);
  await page.setViewportSize({ width: 900, height: 820 });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, `${TAG}-${name}.png`) });
}

/** Short labels (14 characters or fewer, alone in their element) whose characters sit on more than one line. */
async function twoLineLabels(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    const range = document.createRange();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const text = (n.textContent ?? "").trim();
      const el = n.parentElement;
      if (!text || text.length > 14 || !el || (el.textContent ?? "").trim().length > 16 || !el.getClientRects().length) continue;
      if (el.closest(".md, pre, textarea, .xterm, .msg .b")) continue;
      const lines = new Set<number>();
      const raw = n.textContent ?? "";
      for (let i = 0; i < raw.length; i++) {
        if (/\s/.test(raw[i])) continue;
        range.setStart(n, i);
        range.setEnd(n, i + 1);
        const r = [...range.getClientRects()].find((x) => x.width > 0);
        if (r) lines.add(Math.round((r.top + r.height / 2) / 4));
      }
      if (lines.size > 1) out.push(`${el.tagName.toLowerCase()}.${[...el.classList].join(".")} "${text}"`);
    }
    return out;
  });
}

/** Each card: its status, chip and corner label are one line each, and the corner label overlaps neither the name nor
 *  the status line. */
async function cardProblems(page: Page): Promise<string[]> {
  return page.evaluate((names) => {
    const out: string[] = [];
    const lineOf = (el: Element) => parseFloat(getComputedStyle(el).lineHeight) || parseFloat(getComputedStyle(el).fontSize) * 1.5;
    const oneLine = (what: string, el: Element | null) => {
      if (!el) return;
      const rects = el.getClientRects();
      const h = el.getBoundingClientRect().height;
      if (rects.length !== 1 || h > lineOf(el) * 1.4) out.push(`${what} "${el.textContent}" on ${rects.length} boxes, ${Math.round(h)}px tall`);
    };
    const meets = (a: DOMRect, b: DOMRect) => a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
    for (const name of names) {
      const card = document.querySelector(`[data-testid="bot-card-${name}"]`);
      if (!card) {
        out.push(`no card ${name}`);
        continue;
      }
      const w = card.parentElement!;
      const status = card.querySelector(`[data-testid="bot-status-${name}"]`);
      const corner = w.querySelector(".bc-list");
      oneLine(`${name} status`, status);
      oneLine(`${name} chip`, card.querySelector(".bc-id code"));
      oneLine(`${name} corner`, corner);
      if (status && status.scrollWidth > status.clientWidth + 1) out.push(`${name} status cut: "${status.textContent}"`);
      if (corner) {
        const c = corner.getBoundingClientRect();
        const nameBox = card.querySelector(".bc-id b")!.getBoundingClientRect();
        const row = card.querySelector(".bc-id > span")!.getBoundingClientRect();
        if (meets(c, nameBox)) out.push(`${name} corner label over the name`);
        if (meets(c, row)) out.push(`${name} corner label over the status line`);
      }
    }
    return out;
  }, BOTS);
}

for (const lang of LANGS) {
  test(`${lang}: every bot card keeps its status, chip and list label on one line at every card width`, async ({ page }) => {
    await open(page, lang);
    // the longest status in every language ("Not connected", "연결 안 됨") on the card with a profile chip
    await mock("mock.botStatus", { bot: "omh-tui", status: "offline" });
    await page.getByTestId("nav-settings").click();
    await page.getByTestId("settings-nav-bots").click();
    await expect(page.getByTestId("bot-card-default")).toBeVisible();
    await expect(page.getByTestId("bot-addlist-friren")).toBeVisible();
    await expect(page.getByTestId("bot-status-omh-tui")).toHaveText(
      { en: "Not connected", ko: "연결 안 됨", ja: "未接続", zh: "未连接" }[lang],
    );
    // 900..1400 walks the grid through 1, 2 and 3 columns, each from its narrowest card (220px) up
    for (let width = 900; width <= 1400; width += 25) {
      await page.setViewportSize({ width, height: 820 });
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r(null))));
      if (width === 950 || width === 1200) await shot(page, `bots-${lang}-${width}`);
      expect(await cardProblems(page), `${lang} at ${width}px`).toEqual([]);
      expect(await twoLineLabels(page), `${lang} at ${width}px`).toEqual([]);
    }
  });

  test(`${lang}: no short label reads on two lines on a bot's page and the agents, plugins and apps pages`, async ({ page }) => {
    await open(page, lang);
    await page.getByTestId("nav-settings").click();
    for (const id of ["bot-kami", "bot-default", "agents", "accounts"]) {
      await page.getByTestId(`settings-nav-${id}`).click();
      await expect(page.getByTestId(`settings-page-${id}`)).toBeVisible();
      if (id === "bot-kami") await expect(page.getByTestId("bot-facts").locator(".be-stats")).toBeVisible();
      for (const width of [900, 1280]) {
        await page.setViewportSize({ width, height: 820 });
        await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r(null))));
        if (width === 900 && id === "bot-kami") await shot(page, `bot-page-${lang}-900`);
        expect(await twoLineLabels(page), `${lang} ${id} at ${width}px`).toEqual([]);
      }
      await page.setViewportSize({ width: 900, height: 820 });
    }
    for (const nav of ["plugins", "apps"]) {
      await page.getByTestId(`nav-${nav}`).click();
      await expect(page.locator(".pg").first()).toBeVisible();
      for (const width of [900, 1280]) {
        await page.setViewportSize({ width, height: 820 });
        await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r(null))));
        expect(await twoLineLabels(page), `${lang} ${nav} at ${width}px`).toEqual([]);
      }
      await page.setViewportSize({ width: 900, height: 820 });
    }
  });
}
