// Fit checks and shots for Settings > Terminal and a themed terminal (dark and light). The fit checks always run;
// the shots are written when OMHER_SHOTS=<dir> is set.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { termSample } from "../src/sessions/term/look-sample";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

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

async function open(page: Page, theme: string, lang = "en") {
  await page.addInitScript(
    ([t, l]) => {
      localStorage.setItem("omher.theme", t);
      localStorage.setItem("omher.lang", l);
      for (const k of ["omher.term", "omher.sessions.recent", "omher.sessions.open", "omher.resume"]) localStorage.removeItem(k);
      const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
      w.__omherPickFolder = "/Users/you/code/web-app";
      w.__omherMockAgents = ["claude", "codex", "omh"];
    },
    [theme, lang],
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function settings(page: Page) {
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  await expect(page.getByTestId("term-preview").locator(".xterm-rows")).toContainText("42 passed");
}

async function terminalClaude(page: Page) {
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-way-terminal").click();
  await page.getByTestId("session-go").click();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
}

/** Nothing on the Terminal page is clipped, overlaps its neighbour or runs off the page. */
async function fits(page: Page, at: string) {
  const r = await page.evaluate(() => {
    const body = document.querySelector<HTMLElement>(".st-body")!;
    const bb = body.getBoundingClientRect();
    const out: string[] = [];
    if (document.documentElement.scrollWidth > window.innerWidth) out.push("the window scrolls sideways");
    if (body.scrollWidth > body.clientWidth) out.push("the page scrolls sideways");
    const within = (el: Element, what: string) => {
      const b = el.getBoundingClientRect();
      if (b.width === 0 || b.left < bb.left - 0.5 || b.right > bb.right + 0.5) out.push(`${what} is outside the page (${Math.round(b.left)}..${Math.round(b.right)} in ${Math.round(bb.left)}..${Math.round(bb.right)})`);
    };
    // each row: its words and its control side by side, neither over the other, neither clipped
    for (const row of document.querySelectorAll<HTMLElement>("[data-testid=term-settings] .st-row")) {
      const k = row.querySelector<HTMLElement>(".st-k")!;
      const v = row.querySelector<HTMLElement>(".st-v")!;
      const name = k.querySelector("b")?.textContent ?? "row";
      within(k, `${name}: words`);
      within(v, `${name}: control`);
      const kb = k.getBoundingClientRect();
      const vb = v.getBoundingClientRect();
      // side by side, or (a narrow page) the control under the words: never one over the other
      if (kb.right > vb.left + 0.5 && kb.bottom > vb.top + 0.5) out.push(`${name}: words and control overlap`);
      // the title stays on one line; a hint may wrap but keeps a readable measure
      const title = k.querySelector<HTMLElement>("b")!;
      if (title.getBoundingClientRect().height > 22) out.push(`${name}: title wraps`);
      for (const hint of k.querySelectorAll<HTMLElement>("span")) if (hint.getBoundingClientRect().width < 150) out.push(`${name}: hint squeezed to ${Math.round(hint.getBoundingClientRect().width)}px`);
      const rb = row.getBoundingClientRect();
      if (kb.bottom > rb.bottom + 0.5 || vb.bottom > rb.bottom + 0.5) out.push(`${name}: taller than its row`);
      for (const el of [...v.querySelectorAll<HTMLElement>("button, input")]) if (el.scrollWidth > el.clientWidth + 1) out.push(`${name}: "${el.textContent || el.getAttribute("aria-label")}" is clipped`);
    }
    // rows follow one another without overlap
    const rows = [...document.querySelectorAll<HTMLElement>("[data-testid=term-settings] .st-row")].map((e) => e.getBoundingClientRect());
    for (const grp of document.querySelectorAll<HTMLElement>("[data-testid=term-settings] .st-grp")) {
      const rs = [...grp.querySelectorAll<HTMLElement>(":scope > .st-row")].map((e) => e.getBoundingClientRect());
      for (let i = 1; i < rs.length; i++) if (rs[i].top < rs[i - 1].bottom - 0.5) out.push("two rows overlap");
    }
    // the bar: the Dark | Light choice and the search field, apart
    const slot = document.querySelector<HTMLElement>("[data-testid=term-slot]")!;
    const search = document.querySelector<HTMLElement>("[data-testid=term-search]")!;
    within(slot, "the theme choice");
    within(search, "the search field");
    const sb = slot.getBoundingClientRect();
    const qb = search.getBoundingClientRect();
    if (!(sb.right <= qb.left + 0.5 || sb.bottom <= qb.top + 0.5)) out.push("the theme choice and the search field overlap");
    for (const el of slot.querySelectorAll<HTMLElement>("button")) if (el.scrollWidth > el.clientWidth + 1) out.push(`"${el.textContent}" is clipped`);
    // the list: every theme row inside it, its swatch whole
    const list = document.querySelector<HTMLElement>("[data-testid=term-themes]")!;
    if (list.scrollWidth > list.clientWidth) out.push("the theme list scrolls sideways");
    const lb = list.getBoundingClientRect();
    for (const row of list.querySelectorAll<HTMLElement>(".tm-row")) {
      const b = row.getBoundingClientRect();
      const sw = row.querySelector<HTMLElement>(".tm-sw")!.getBoundingClientRect();
      const nm = row.querySelector<HTMLElement>(".tm-name")!.getBoundingClientRect();
      if (b.left < lb.left - 0.5 || b.right > lb.right + 0.5) out.push(`theme ${row.textContent} is outside the list`);
      if (sw.width < 80 || sw.right > nm.left + 0.5) out.push(`theme ${row.textContent}: swatch squeezed or under the name`);
      const name = row.querySelector<HTMLElement>(".tm-name")!;
      if (name.scrollWidth > name.clientWidth) out.push(`theme ${row.textContent}: name cut short`);
    }
    // the preview: inside the page, its terminal inside it
    const pv = document.querySelector<HTMLElement>("[data-testid=term-preview]")!;
    within(pv, "the preview");
    // the page adds no outline Settings > General does not have: the theme list is not a box, and the text
    // fields and steppers (controls General has none of) carry none
    const edge = (el: HTMLElement, side: "Top" | "Left" | "Right") => parseFloat(getComputedStyle(el)[`border${side}Width`]) || 0;
    if (edge(list, "Left") || edge(list, "Right")) out.push("the theme list is a box");
    for (const el of document.querySelectorAll<HTMLElement>("[data-testid=term-search], [data-testid=term-font], [data-testid=term-settings] .tm-step")) {
      const c = getComputedStyle(el);
      if (parseFloat(c.borderTopWidth) > 0 && c.borderTopColor !== "rgba(0, 0, 0, 0)") out.push(`${el.dataset.testid ?? "a field"} is outlined`);
    }
    const screen = pv.querySelector<HTMLElement>(".xterm-screen")!.getBoundingClientRect();
    const pb = pv.getBoundingClientRect();
    if (screen.right > pb.right + 0.5 || screen.bottom > pb.bottom + 0.5) out.push("the preview's terminal is cut off");
    return { out, rows: rows.length };
  });
  expect(r.rows, at).toBeGreaterThanOrEqual(9);
  expect(r.out, at).toEqual([]);
}

for (const theme of ["dark", "light"] as const) {
  test.describe(theme, () => {
    test.use({ colorScheme: theme });

    test(`Settings > Terminal fits at 1280x820 and 900x700 in every language (${theme})`, async ({ page }) => {
      for (const lang of ["en", "ko", "ja", "zh"]) {
        for (const size of [{ width: 1280, height: 820 }, { width: 900, height: 700 }]) {
          await page.setViewportSize(size);
          await open(page, theme, lang);
          await settings(page);
          await fits(page, `${lang} ${size.width}x${size.height} ${theme}`);
        }
      }
    });

    test(`shots (${theme})`, async ({ page }) => {
      test.skip(!SHOTS, "no shot folder");
      mkdirSync(SHOTS, { recursive: true });
      // staged shots carry no bot named after the product: the default profile shows as "Juno" (mock.reset, before
      // each test, puts the name back)
      await mock("bots.rename", { bot: "default", name: "Juno" });
      const shot = async (name: string) => {
        await page.mouse.move(640, 40);
        await page.waitForTimeout(350);
        await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled" });
      };
      await open(page, theme);
      await terminalClaude(page);
      // The mock program prints white and gray only, so a theme would show as a background and nothing else. The
      // shot's output is the preview's sample (every ANSI colour, bold, dim), written into the session's own
      // terminal through the dev build's hook, in place of the mock's waiting prompt.
      await page.evaluate((bytes) => {
        type T = { element?: HTMLElement; write(data: string): void };
        const set = (window as unknown as { __omherTerms?: Set<T> }).__omherTerms;
        [...(set ?? [])].find((x) => x.element?.closest(".term-host"))!.write(bytes);
      }, `\r\x1b[2K${termSample()}`);
      await expect(page.locator(".xterm-rows")).toContainText("42 passed");

      await settings(page);
      await fits(page, `shot ${theme}`);
      await shot(`term-look-settings-${theme}`);
      // the option rows, lower on the page
      await page.getByTestId("term-gpu-row").scrollIntoViewIfNeeded();
      await shot(`term-look-options-${theme}`);
      await page.locator(".st-body").evaluate((el) => el.scrollTo(0, 0));
      // the same page in the smallest window
      await page.setViewportSize({ width: 900, height: 700 });
      // the preview refits when its box changes size (a ResizeObserver, so a frame later)
      await expect
        .poll(() =>
          page.evaluate(() => {
            const pv = document.querySelector<HTMLElement>("[data-testid=term-preview]")!;
            return pv.querySelector<HTMLElement>(".xterm-screen")!.getBoundingClientRect().right <= pv.getBoundingClientRect().right + 0.5;
          }),
        )
        .toBe(true);
      await fits(page, `shot 900x700 ${theme}`);
      await shot(`term-look-settings-900-${theme}`);
      await page.getByTestId("term-gpu-row").scrollIntoViewIfNeeded();
      await shot(`term-look-options-900-${theme}`);
      await page.locator(".st-body").evaluate((el) => el.scrollTo(0, 0));
      await page.setViewportSize({ width: 1280, height: 820 });

      // the app theme's own pick: Dracula for dark, Solarized Light for light
      const pick = theme === "dark" ? "dracula" : "solarized-light";
      if (theme === "dark") {
        await page.getByTestId("term-search").fill("github");
        await expect(page.locator("[data-testid=term-themes] .tm-row")).toHaveCount(6);
        await shot("term-look-picker-search-dark");
        await page.getByTestId("term-search").fill("");
      }
      await page.getByTestId(`term-theme-${pick}`).click();
      await expect(page.getByTestId("term-preview")).toHaveAttribute("data-theme-id", pick);
      await page.locator("[data-testid=session-list] .ss-row .ss-open").first().click();
      await expect(page.getByTestId("terminal")).toBeVisible();
      await expect(page.locator(".xterm-rows")).toContainText("42 passed");
      await shot(theme === "dark" ? "term-look-dracula-dark" : "term-look-solarized-light");
    });
  });
}
