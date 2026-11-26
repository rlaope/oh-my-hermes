// Short labels never break inside a word, in every UI language (en, ko, ja, zh). A bot card's status read "연결" on
// one line and "됨" on the next beside the `default` chip: the Korean rule's `overflow-wrap: anywhere` let the status
// shrink to one syllable wide, and ja/zh break between any two characters. At every card width the grid gives, from
// the 900px minimum window up: each card's status word, profile chip and "In list" / "Add to list" label sit on one
// line, the corner label clears the name and the status line, and no short label on the bots page, a bot's page, the
// agents, plugins or apps pages reads on two lines (the bot page's stat captions included). Only Korean keeps words
// whole (keep-all): a Japanese or Chinese reply breaks between characters as those languages do, so a Latin word in
// it moves to the next line whole instead of being cut where a sentence-long "word" hit the edge, and a long URL in it
// still wraps inside the bubble. A Korean reply keeps its words whole in any UI language (the bubble says lang="ko").
// Shots with OMHER_SHOTS=<dir> (OMHER_SHOT_TAG=after by default).
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";
const LANGS = ["en", "ko", "ja", "zh"] as const;
// "build-box:mini" is a bot on another computer (SSH), its card's status beside the SSH marker instead of a chip
const BOTS = ["kami", "friren", "default", "omh-tui", "build-box:mini"];

const CJK_REPLY = {
  ja: "今日はKubernetesの設定をGrafanaで確認してからPrometheusのアラートをTerraformで直し、そのあとElasticsearchとPostgreSQLのバックアップをKubernetesのCronJobで毎晩回すようにして、最後にCloudflareとDatadogのダッシュボードもまとめて更新しました。詳しくは https://example.com/runbooks/kubernetes/cronjob-backup-and-restore-0123456789abcdef0123456789abcdef を見てください。",
  zh: "今天先在Grafana里检查了Kubernetes的配置，再用Terraform修好了Prometheus的告警，然后让Kubernetes的CronJob每晚备份Elasticsearch和PostgreSQL，最后把Cloudflare和Datadog的仪表盘也一起更新了。详情请看 https://example.com/runbooks/kubernetes/cronjob-backup-and-restore-0123456789abcdef0123456789abcdef 。",
} as const;

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
      oneLine(`${name} SSH marker`, card.querySelector(".bc-id .ssh-mark"));
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
    // a remote bot whose SSH marker has a long label, offline too: the marker gives way, never the status word
    await mock("peers.attach", { peer: "build-box", label: "Build server in the hall closet", host: "you@build-box.local", url: `ws://127.0.0.1:5999/?token=${"0".repeat(32)}` });
    await mock("mock.botStatus", { bot: "build-box:mini", status: "offline" });
    await page.getByTestId("nav-settings").click();
    await page.getByTestId("settings-nav-bots").click();
    await expect(page.getByTestId("bot-card-default")).toBeVisible();
    await expect(page.getByTestId("bot-addlist-friren")).toBeVisible();
    for (const b of ["omh-tui", "build-box:mini"])
      await expect(page.getByTestId(`bot-status-${b}`)).toHaveText({ en: "Not connected", ko: "연결 안 됨", ja: "未接続", zh: "未连接" }[lang]);
    await expect(page.getByTestId("card-ssh-build-box:mini")).toBeVisible();
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

for (const lang of ["ja", "zh"] as const) {
  test(`${lang}: a reply breaks between characters, so a Latin word in it is never cut and a long URL still wraps`, async ({ page }) => {
    await open(page, lang);
    await mock("mock.emit", { events: [{ event: "message", bot: "kami", id: `tw-${lang}`, text: CJK_REPLY[lang] }] });
    const bubble = page.getByTestId("bubble-bot").last().locator(".b");
    await expect(bubble).toContainText("Kubernetes");
    for (const width of [900, 1000, 1100, 1280]) {
      await page.setViewportSize({ width, height: 820 });
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r(null))));
      const got = await bubble.evaluate((b) => {
        const textRight = (root: Element) => {
          let right = -Infinity;
          const rg = document.createRange();
          const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
          for (let t = w.nextNode(); t; t = w.nextNode()) {
            rg.selectNodeContents(t);
            for (const r of rg.getClientRects()) if (r.width > 0) right = Math.max(right, r.right);
          }
          return right;
        };
        const range = document.createRange();
        const lineTops = new Set<number>();
        const cut: string[] = [];
        const walker = document.createTreeWalker(b, NodeFilter.SHOW_TEXT);
        for (let n = walker.nextNode(); n; n = walker.nextNode()) {
          const text = n.textContent ?? "";
          const top = (i: number) => {
            range.setStart(n!, i);
            range.setEnd(n!, i + 1);
            const r = [...range.getClientRects()].find((x) => x.width > 0);
            return r ? Math.round((r.top + r.height / 2) / 4) : null;
          };
          for (let i = 0; i < text.length; i++) {
            const t = top(i);
            if (t !== null) lineTops.add(t);
          }
          // every Latin word that is not part of the URL sits on one line
          for (const m of text.matchAll(/(?<![\/.\w-])[A-Za-z]{4,}(?![\/.\w-])/g)) {
            const tops = new Set([...m[0]].map((_, k) => top(m.index! + k)).filter((x) => x !== null));
            if (tops.size > 1) cut.push(m[0]);
          }
        }
        // the text's right edge against the bubble's content edge (the hover copy button sits outside on purpose)
        const cs = getComputedStyle(b);
        const inner = b.getBoundingClientRect().right - parseFloat(cs.paddingRight);
        const over = textRight(b) - inner;
        return { wordBreak: cs.wordBreak, lines: lineTops.size, cut, over };
      });
      if (width === 900) await shot(page, `reply-${lang}-900`);
      expect(got.lines, `${lang} at ${width}px: the reply wraps`).toBeGreaterThan(2);
      expect(got.cut, `${lang} at ${width}px: Latin words cut across lines`).toEqual([]);
      expect(got.over, `${lang} at ${width}px: text past the bubble`).toBeLessThanOrEqual(1);
      expect(got.wordBreak, `${lang} at ${width}px`).toBe("normal");
    }
  });
}

for (const ui of ["ko", "en", "ja"] as const) {
  test(`${ui} UI: a Korean reply keeps its words whole (keep-all) and a long URL still wraps`, async ({ page }) => {
    await open(page, ui);
    const text = "오늘은 Grafana에서 Kubernetes 설정을 확인하고 Terraform으로 Prometheus 알림을 고친 다음, 매일 밤 CronJob이 Elasticsearch와 PostgreSQL을 백업하도록 바꿨습니다. 자세한 내용은 https://example.com/runbooks/kubernetes/cronjob-backup-and-restore-0123456789abcdef0123456789abcdef 를 보세요.";
    await mock("mock.emit", { events: [{ event: "message", bot: "kami", id: "tw-ko", text }] });
    const bubble = page.getByTestId("bubble-bot").last().locator(".b");
    await expect(bubble).toContainText("백업하도록");
    const got = await bubble.evaluate((b) => {
      const textRight = (root: Element) => {
        let right = -Infinity;
        const rg = document.createRange();
        const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        for (let t = w.nextNode(); t; t = w.nextNode()) {
          rg.selectNodeContents(t);
          for (const r of rg.getClientRects()) if (r.width > 0) right = Math.max(right, r.right);
        }
        return right;
      };
      const range = document.createRange();
      const cut: string[] = [];
      const walker = document.createTreeWalker(b, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const text = n.textContent ?? "";
        for (const m of text.matchAll(/[\uac00-\ud7a3A-Za-z]+/g)) {
          const tops = new Set(
            [...m[0]].map((_, k) => {
              range.setStart(n!, m.index! + k);
              range.setEnd(n!, m.index! + k + 1);
              const r = [...range.getClientRects()].find((x) => x.width > 0);
              return r ? Math.round((r.top + r.height / 2) / 4) : null;
            }).filter((x) => x !== null),
          );
          if (tops.size > 1 && !/^(https|example|com|runbooks|kubernetes|cronjob|backup|and|restore)$/.test(m[0])) cut.push(m[0]);
        }
      }
      const cs = getComputedStyle(b);
      const inner = b.getBoundingClientRect().right - parseFloat(cs.paddingRight);
      const over = textRight(b) - inner;
      return { wordBreak: cs.wordBreak, cut, over };
    });
    expect(got.cut).toEqual([]);
    expect(got.over).toBeLessThanOrEqual(1);
    expect(got.wordBreak).toBe("keep-all");
    if (ui !== "ko") await shot(page, `reply-ko-in-${ui}-900`);
  });
}
