// 0.2.6 follow-ups, the session and chat polish (one test per item, each failing before its fix):
// 1. a running subagent card says how many are done, never more running than are;
// 2. a subagent waiting on the person's approval reads "waiting" (amber), and running again once answered;
// 3. the activity line above the card and that subagent's row show one clock;
// 4. a session whose agent never answered in chat mode says why once, with Restart beside it;
// 5. a bot's chat header keeps the model name whole from 900px up, panel open and closed, in every language; the
//    places chip gives way first, down to its marks;
// 6. the SESSIONS + menu shows a fade where its list is cut (none at the end) and keeps a few px from the row above;
// 7. a session's / menu: skills told apart at a glance, descriptions as wide as the chat column, names plain text.
// Shots: OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function setup(page: Page, theme: "dark" | "light", globals: Record<string, unknown> = {}, lang = "en") {
  await page.addInitScript(
    ([t, g, l]) => {
      const w = window as unknown as Record<string, unknown>;
      localStorage.setItem("omher.theme", t as string);
      localStorage.setItem("omher.lang", l as string);
      localStorage.removeItem("omher.sessions.recent");
      Object.assign(w, g);
      w.__omherPickFolder = "/Users/you/code/web-app";
    },
    [theme, globals, lang] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function start(page: Page, agent: string, first: string) {
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
}

async function shot(page: Page, item: string, theme: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(SHOTS, `polish-026-${item}-${TAG}-${theme}.png`), animations: "disabled", caret: "initial" });
}

const secs = (s: string) => {
  const m = /(\d+)s\s*$/.exec(s.trim());
  if (!m) throw new Error(`no seconds in: ${s}`);
  return Number(m[1]);
};

for (const theme of ["dark", "light"] as const) {
  test(`1. a running subagent card says how many are done, never more running than are (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await start(page, "claude", "/subagents hold");
    const card = page.getByTestId("fanout-card");
    const rows = card.getByTestId("subagent-row");
    await expect(rows.nth(0)).toHaveAttribute("data-state", "done");
    await expect(rows.nth(1)).toHaveAttribute("data-state", "running");
    await page.mouse.move(5, 5);
    await shot(page, "1-card", theme);
    // one of two has finished: the line says so, the way Plans does, and does not claim two are running
    await expect(card.getByTestId("fanout-summary")).toHaveText(/^Running · 1 of 2 done · \d+s$/);
    // Stop: the card folds to what ran
    await page.getByTestId("composer").focus();
    await page.keyboard.press("Escape");
    await expect(card).toHaveAttribute("data-state", "done");
    await expect(card.getByTestId("fanout-summary")).toHaveText(/^Ran 2 subagents · \d+s/);
  });

  test(`2. a subagent waiting on the person's approval reads waiting, then running again (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await start(page, "claude", "/subask");
    await expect(page.getByTestId("card-subagent")).toBeVisible();
    const row = page.getByTestId("fanout-card").getByTestId("subagent-row");
    await page.mouse.move(5, 5);
    await shot(page, "2-waiting", theme);
    await expect(row).toHaveAttribute("data-state", "waiting");
    const st = row.getByTestId("subagent-state");
    await expect(st).toHaveText("waiting");
    // the sidebar's amber for a waiting session
    const [rowColor, sideColor] = await Promise.all([
      st.evaluate((e) => getComputedStyle(e).color),
      page.locator('[data-testid^="session-"] .bot-t.wait').first().evaluate((e) => getComputedStyle(e).color),
    ]);
    expect(rowColor).toBe(sideColor);
    // answered: no longer waiting (it runs, then hands back)
    await page.getByTestId("card-approval").locator(".card-btn", { hasText: "Allow once" }).click();
    await expect(row).not.toHaveAttribute("data-state", "waiting");
    await expect(row).toHaveAttribute("data-state", "done");
  });

  test(`3. the activity line and the subagent's row show one clock (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await page.clock.install();
    await start(page, "claude", "/subagents hold");
    // the first subagent hands back and the line names the second ("Asking `Count lines of b.txt`"), which started
    // 170ms after the turn: the turn's count and the row's then differ for 170ms of every second
    const act = page.getByTestId("activity").last();
    await expect(act.getByTestId("activity-text")).toContainText("Count lines of b.txt");
    const line = act.getByTestId("activity-elapsed");
    const row = page.getByTestId("fanout-card").getByTestId("subagent-row").nth(1).getByTestId("subagent-time");
    await expect(row).toBeVisible();
    await page.mouse.move(5, 5);
    await shot(page, "3-clock", theme);
    // stop the clock, then step it 100ms at a time through three seconds: at every step both read one number
    await page.clock.pauseAt((await page.evaluate(() => Date.now())) + 20);
    for (let i = 0; i < 30; i++) {
      await page.clock.runFor(100);
      await expect.poll(async () => secs(await line.innerText()) - secs(await row.innerText()), { message: `line vs row, step ${i}`, timeout: 2000 }).toBe(0);
    }
  });

  test(`4. an agent that never answered in chat mode says why once, Restart beside it (${theme})`, async ({ page }) => {
    await setup(page, theme, { __omherMockNoChat: ["omo"], __omherMockAgents: ["claude", "codex", "omo", "pi"] });
    await start(page, "omo", "Summarize the README");
    const ended = page.getByTestId("session-ended");
    const why = "OmO did not answer in chat mode; it may be an old version: npm i -g omo-ai";
    await expect(ended).toContainText(why);
    await expect(page.getByTestId("session-restart")).toBeVisible();
    await page.mouse.move(5, 5);
    await shot(page, "4-ended", theme);
    // the reason sentence is on screen once
    const shown = await page.getByTestId("session-chat").evaluate((el, w) => (el as HTMLElement).innerText.split(w).length - 1, why);
    expect(shown).toBe(1);
    // and the chat still says the message failed (a short line, no second copy of the reason)
    await expect(page.getByTestId("activity").last()).toHaveAttribute("data-state", "error");
    // Restart sits on the same line as the reason
    const [r, b] = await Promise.all([page.locator(".ss-ended-t").boundingBox(), page.getByTestId("session-restart").boundingBox()]);
    expect(Math.abs(r!.y + r!.height / 2 - (b!.y + b!.height / 2))).toBeLessThan(4);
  });
}

/** The header once the panel has stopped sliding (two reads 80ms apart agree). */
async function settledHeader(page: Page) {
  const read = () => page.evaluate(() => document.querySelector('[data-testid="header"]')!.getBoundingClientRect().right);
  await expect
    .poll(async () => {
      const a = await read();
      await page.waitForTimeout(80);
      return a === (await read());
    })
    .toBe(true);
}

test("5. a bot's header keeps the model name whole from 900px up, panel open and closed, in every language", async ({ page }) => {
  test.setTimeout(240_000);
  for (const lang of ["en", "ko", "ja", "zh"]) {
    await setup(page, "dark", {}, lang);
    await expect(page.getByTestId("places")).toBeVisible();
    const btn = page.getByTestId("panel-button");
    for (const open of [false, true]) {
      for (const width of [900, 1000, 1100, 1180, 1280, 1440]) {
        await page.setViewportSize({ width, height: 800 });
        // under 1100px an open panel lies over the chat, header included: toggle it with the shortcut (⌘. / Ctrl+.)
        if ((await btn.getAttribute("aria-pressed")) !== String(open)) await page.keyboard.press("ControlOrMeta+Period");
        await expect(btn).toHaveAttribute("aria-pressed", String(open));
        // the widest panel is Plans (the case that cut the name): open on that tab
        if (open && (await page.getByTestId("panel-tab-runs").getAttribute("aria-selected")) !== "true") await page.getByTestId("panel-tab-runs").click();
        await settledHeader(page);
        const where = `${lang} ${width}px panel ${open ? "open" : "closed"}`;
        const m = await page.evaluate(() => {
          const q = (id: string) => document.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;
          const label = q("model-label")!;
          const places = q("places");
          const ids = ["who", "places", "model-pill", "panel-button"];
          const rects = ids.map((id) => q(id)?.getBoundingClientRect().toJSON() ?? null);
          return { cw: label.clientWidth, sw: label.scrollWidth, placesLabel: !!places && getComputedStyle(places.querySelector('[data-testid="places-label"]')!).display !== "none", rects };
        });
        expect(m.sw, `model name whole at ${where} (${m.cw} of ${m.sw})`).toBeLessThanOrEqual(m.cw);
        // nothing overlaps, left to right
        const r = m.rects.filter(Boolean) as DOMRect[];
        for (let i = 1; i < r.length; i++) expect(r[i].left, `order at ${where}`).toBeGreaterThanOrEqual(r[i - 1].right - 0.5);
        // closed, the chip keeps its words at every width
        if (!open) expect(m.placesLabel, `places words at ${where}`).toBe(true);
      }
    }
  }
});

for (const theme of ["dark", "light"] as const) {
  test(`5. the header at 1100px with Plans open keeps "Opus 5.5" whole, the chip down to its marks (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await page.setViewportSize({ width: 1100, height: 800 });
    await expect(page.getByTestId("places")).toBeVisible();
    const btn = page.getByTestId("panel-button");
    if ((await btn.getAttribute("aria-pressed")) !== "true") await btn.click();
    await expect(page.getByTestId("panel-tab-runs")).toHaveAttribute("aria-selected", "true");
    await settledHeader(page);
    await shot(page, "5-header", theme);
    const m = await page.getByTestId("model-label").evaluate((e) => [e.scrollWidth, e.clientWidth]);
    expect(m[0], `model label ${m[1]} of ${m[0]}`).toBeLessThanOrEqual(m[1]);
    await expect(page.getByTestId("places-label")).toBeHidden();
  });
}

async function plusMenu(page: Page, height: number, width = 1280) {
  await page.setViewportSize({ width, height });
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-more")).toHaveAttribute("aria-expanded", "false");
  await page.getByTestId("session-more").click();
  await expect(page.getByTestId("session-agent-grok")).toBeAttached();
  await page.keyboard.press("Home");
  await page.waitForFunction(() => document.querySelector(".ss-pop")?.getAnimations().every((a) => a.playState !== "running"));
}

for (const theme of ["dark", "light"] as const) {
  test(`6. the + menu shows a fade where its list is cut, none at the end, and air above (${theme})`, async ({ page }) => {
    await setup(page, theme, { __omherMockAgents: ["claude", "codex", "omh", "opencode"] });
    for (const height of [600, 720, 820]) {
      for (const width of [900, 1100, 1280]) {
        await page.reload();
        await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
        await plusMenu(page, height, width);
        const where = `${width}x${height}`;
        const read = () =>
          page.evaluate(() => {
            const el = document.querySelector(".ss-pop")!;
            const pop = el.getBoundingClientRect();
            // an upward menu's air: a band of the sidebar's colour above its edge, covering the strip between
            const air = parseFloat(getComputedStyle(el, "::before").height) || 0;
            const list = document.querySelector<HTMLElement>(".ss-scroll")!;
            const cs = getComputedStyle(list);
            const mask = cs.maskImage || (cs as unknown as { webkitMaskImage: string }).webkitMaskImage || "none";
            // the sidebar rows that begin above the menu and its air: how far the nearest ends from the menu's edge,
            // and whether any reaches into the air (half a row would show there)
            const rows = [...document.querySelectorAll(".side .bot-list > *, .side .ss-list > *, .side-sec > .side-sh, .side-top")].map((r) => r.getBoundingClientRect());
            const above = rows.filter((r) => r.height > 0 && r.top < pop.top - air - 0.5);
            const nearest = above.length ? Math.min(...above.map((r) => pop.top - r.bottom)) : 99;
            const half = above.filter((r) => r.bottom > pop.top - air + 0.5).length;
            const shown = list.clientHeight;
            return { cut: list.scrollHeight > list.clientHeight + 1, atEnd: list.scrollTop + list.clientHeight >= list.scrollHeight - 1, mask, nearest, half, shown };
          });
        if (height === 720 && width === 1280) {
          await page.mouse.move(700, 700);
          await shot(page, "6-plus-menu", theme);
        }
        const a = await read();
        expect(a.cut, `the list is cut at ${where}`).toBe(true);
        // a cut list shows a fade at its bottom edge
        expect(a.mask, `fade at ${where}`).toContain("gradient");
        // a few px of air between the menu and the row above it (no overlap, not 1px), no row half in it, and the
        // list still shows most agents (at least six 30px rows), not a sliver
        expect(a.nearest, `air above at ${where}`).toBeGreaterThanOrEqual(4);
        expect(a.half, `half a row in the air at ${where}`).toBe(0);
        expect(a.shown, `rows shown at ${where}`).toBeGreaterThanOrEqual(180);
        // scrolled to the end: no fade over the last row
        await page.locator(".ss-scroll").evaluate((e) => e.scrollTo({ top: e.scrollHeight }));
        await expect.poll(async () => (await read()).mask, { message: `no fade at the end, ${where}` }).toBe("none");
        await page.keyboard.press("Escape");
      }
    }
  });

  test(`7. the / menu tells skills apart, gives descriptions the column's width, names plain (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await page.setViewportSize({ width: 1280, height: 820 });
    await start(page, "claude", "Look at the README and tell me what this repo does");
    await expect(page.getByTestId("session-status")).toHaveText("Ready");
    await page.getByTestId("composer").fill("/");
    const picker = page.getByTestId("command-picker");
    await expect(picker).toBeVisible();
    await page.mouse.move(5, 5);
    await shot(page, "7-slash", theme);
    const m = await page.evaluate(() => {
      const pop = document.querySelector('[data-testid="command-picker"]')!.getBoundingClientRect();
      const box = document.querySelector('[data-testid="composer-box"]')!.getBoundingClientRect();
      const rows = [...document.querySelectorAll<HTMLElement>('[data-testid="command-option"]')];
      const cut = rows.slice(0, 8).filter((r) => {
        const d = r.querySelector<HTMLElement>(".sk-d");
        return d && d.scrollWidth > d.clientWidth;
      }).length;
      const name = rows[0].querySelector<HTMLElement>('[data-testid="command-name"]');
      const nameBg = name ? getComputedStyle(name).backgroundColor : "missing";
      const skill = rows.find((r) => r.dataset.kind === "skill")!;
      const mark = skill.querySelector<HTMLElement>('[data-testid="command-skill"]');
      const cmd = rows.find((r) => r.dataset.kind === "command")!;
      // the list ends on a row boundary: no row shows half under the menu's bottom edge
      const el = document.querySelector<HTMLElement>('[data-testid="command-picker"]')!;
      const inner = el.getBoundingClientRect().top + el.clientTop + el.clientHeight;
      const half = rows.filter((r) => {
        const b = r.getBoundingClientRect();
        return b.top < inner - 0.5 && b.bottom > inner + 0.5;
      }).length;
      return {
        half,
        popW: pop.width,
        boxW: box.width,
        cut,
        nameBg,
        hasMark: !!mark,
        markColor: mark ? getComputedStyle(mark).color : "",
        markSize: mark ? parseFloat(getComputedStyle(mark).fontSize) : 0,
        cmdMark: !!cmd.querySelector('[data-testid="command-skill"]'),
        quiet: getComputedStyle(document.documentElement).getPropertyValue("--quiet").trim(),
      };
    });
    // as wide as the chat column's composer
    expect(Math.abs(m.popW - m.boxW)).toBeLessThanOrEqual(2);
    // no description cut among the rows on screen, and no row cut through at the bottom
    expect(m.cut).toBe(0);
    expect(m.half).toBe(0);
    // the name is plain text: no gray box
    expect(m.nameBg).toBe("rgba(0, 0, 0, 0)");
    // a skill carries a mark a command does not, in the skill colour, at the menu's text size
    expect(m.hasMark).toBe(true);
    expect(m.cmdMark).toBe(false);
    expect(m.markSize).toBeGreaterThanOrEqual(11);
    const accent = await page.evaluate(() => {
      const d = document.createElement("span");
      d.style.color = "var(--accent)";
      document.body.append(d);
      const c = getComputedStyle(d).color;
      d.remove();
      return c;
    });
    expect(m.markColor).toBe(accent);
  });
}
