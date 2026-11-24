// "Reply there" in the side panel's "Where Kami is": on hover it takes the place of the row's time, never drawn over
// text. A Windows report showed "거기에 답장" overlapping the row's time ("거기에답장일"): the button sat over the time with
// a translucent hover fill, and the title kept a fixed 64px of room sized for macOS. Here, in every UI language and
// with a wider font than macOS sets (Windows' Malgun Gothic, Yu Gothic UI and Microsoft YaHei UI run wider), the
// button must stay one line, opaque, and clear of every visible text box in its row.
import { expect, test, type Locator, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || join(dirname(fileURLToPath(import.meta.url)), "__shots__");

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

/** A wider text face than macOS sets, on every element: what Windows' fonts do to the same words. */
const WIDE_FONT = `* { font-family: Verdana, "Malgun Gothic", "Apple SD Gothic Neo", sans-serif !important;
  letter-spacing: 0.06em !important; }`;

async function open(page: Page, lang: string, theme: "light" | "dark", wide = false) {
  await page.addInitScript(
    ([l, t]) => {
      localStorage.setItem("omher.lang", l);
      localStorage.setItem("omher.theme", t);
    },
    [lang, theme] as const,
  );
  await page.emulateMedia({ colorScheme: theme });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  if (wide) await page.addStyleTag({ content: WIDE_FONT });
  await page.getByTestId("places").click();
  await expect(page.getByTestId("details-panel").getByTestId("where-row")).toHaveCount(4);
}

const row = (page: Page, session: string) => page.getByTestId("details-panel").locator(`[data-testid=where-row][data-session=${session}]`);

type Box = { x: number; y: number; width: number; height: number };
const overlaps = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

/** Every element in the row that shows text right now, with its box (a hidden time is left out). */
async function visibleTextBoxes(r: Locator): Promise<{ cls: string; text: string; box: Box }[]> {
  return r.evaluate((li) => {
    const out: { cls: string; text: string; box: Box }[] = [];
    for (const el of li.querySelectorAll<HTMLElement>(".ew-ss .t1, .ew-ss > .st, .ew-ss .ew-src, .ew-ss .ew-go")) {
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none" || Number(cs.opacity) === 0 || !el.textContent?.trim()) continue;
      // a text box's own extent: the title's box is clipped to its column, its ellipsis inside
      const r = el.getBoundingClientRect();
      out.push({ cls: el.className, text: el.textContent.trim(), box: { x: r.x, y: r.y, width: r.width, height: r.height } });
    }
    return out;
  });
}

async function expectReplyClear(page: Page, session: string) {
  const r = row(page, session);
  const btn = r.getByTestId("where-reply");
  const st = r.locator(".ew-ss > .st");
  await expect(btn).toHaveCSS("opacity", "0");
  await expect(st).toBeVisible(); // the time shows until the row is hovered
  await r.hover();
  await expect(btn).toHaveCSS("opacity", "1");
  // the time gives way to the button: no two layers of text in one place; it is only out of sight (opacity), so it
  // stays in the link's accessible name
  await expect(st).toHaveCSS("opacity", "0");
  const b = (await btn.boundingBox())!;
  for (const t of await visibleTextBoxes(r)) {
    expect(overlaps(b, t.box), `Reply there ${JSON.stringify(b)} covers ${t.cls} "${t.text}" ${JSON.stringify(t.box)}`).toBe(false);
  }
  // one line that fits its box, on an opaque fill (under the pointer too)
  const fit = await btn.evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, h: el.getBoundingClientRect().height, lh: parseFloat(getComputedStyle(el).lineHeight) }));
  expect(fit.sw).toBeLessThanOrEqual(fit.cw);
  expect(fit.h).toBeLessThan(fit.lh * 2);
  await btn.hover();
  const bg = await btn.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bg, "the hover fill is opaque").toMatch(/^rgb\(/);
  // the button stays inside its row and the panel
  const rb = (await r.boundingBox())!;
  expect(b.x).toBeGreaterThanOrEqual(rb.x);
  expect(b.x + b.width).toBeLessThanOrEqual(rb.x + rb.width + 0.5);
}

for (const lang of ["en", "ko", "ja", "zh"] as const) {
  for (const wide of [false, true]) {
    test(`Reply there never covers row text (${lang}${wide ? ", wide font" : ""})`, async ({ page }) => {
      await open(page, lang, "dark", wide);
      for (const s of ["slack-og-dev-502", "discord-cron-openmaus", "discord-omh-2657"]) await expectReplyClear(page, s);
    });
  }
}

for (const lang of ["ko", "en"] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`Reply there hover shot (${lang}, ${theme})`, async ({ page }) => {
      await open(page, lang, theme);
      const r = row(page, "discord-cron-openmaus");
      await r.hover();
      await expect(r.getByTestId("where-reply")).toHaveCSS("opacity", "1");
      mkdirSync(SHOTS, { recursive: true });
      await page.getByTestId("details-panel").screenshot({ path: join(SHOTS, `reply-there-${lang}-${theme}.png`) });
      // the same row with the pointer on the button itself (the state of the Windows report)
      await r.getByTestId("where-reply").hover();
      await page.getByTestId("details-panel").screenshot({ path: join(SHOTS, `reply-there-${lang}-${theme}-btn.png`) });
    });
  }
}

test("keyboard: Tab to a row shows Reply there in the time's place; the time stays in the link's name", async ({ page }) => {
  await open(page, "en", "dark");
  const r = row(page, "discord-cron-openmaus");
  const link = r.locator("a.ew-ss");
  const btn = r.getByTestId("where-reply");
  const st = r.locator(".ew-ss > .st");
  const time = (await st.textContent())!.trim();
  expect(time).not.toBe("");
  await page.mouse.move(0, 0);
  // walk the focus order to the row's link, as a keyboard user does
  await page.getByTestId("details-edit").focus();
  for (let i = 0; i < 20 && !(await link.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(link).toBeFocused();
  await expect(btn).toHaveCSS("opacity", "1");
  await expect(st).toHaveCSS("opacity", "0");
  await expect(link).toHaveAccessibleName(new RegExp(time.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  const b = (await btn.boundingBox())!;
  for (const t of await visibleTextBoxes(r)) expect(overlaps(b, t.box), `covers ${t.cls} "${t.text}"`).toBe(false);
  // Tab once more lands on the button itself, still shown
  await page.keyboard.press("Tab");
  await expect(btn).toBeFocused();
  await expect(btn).toHaveCSS("opacity", "1");
});

test("a mouse click leaves focus on the row, but not its hover state once the pointer leaves", async ({ page }) => {
  await open(page, "en", "dark");
  const r = row(page, "discord-cron-openmaus");
  const link = r.locator("a.ew-ss");
  // keep the click from opening the thread: the focus a click leaves (Chromium, WebView2) is what is under test
  await link.evaluate((el) =>
    el.addEventListener(
      "click",
      (e) => {
        e.preventDefault();
        e.stopPropagation();
      },
      { capture: true },
    ),
  );
  await link.click();
  await expect(link).toBeFocused();
  await page.mouse.move(0, 0);
  await expect(r.getByTestId("where-reply")).toHaveCSS("opacity", "0");
  await expect(r.locator(".ew-ss > .st")).toHaveCSS("opacity", "1");
});

test("Japanese UI puts the Japanese fonts before the Chinese ones", async ({ page }) => {
  await open(page, "ja", "dark");
  const fam = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
  for (const f of ["Segoe UI", "Hiragino Sans", "Yu Gothic UI", "Meiryo", "PingFang SC", "Microsoft YaHei UI", "Malgun Gothic"]) {
    expect(fam, f).toContain(f);
  }
  expect(fam.indexOf("Hiragino Sans")).toBeLessThan(fam.indexOf("PingFang SC"));
  expect(fam.indexOf("Yu Gothic UI")).toBeLessThan(fam.indexOf("Microsoft YaHei"));
  // Latin still comes first
  expect(fam.indexOf("Segoe UI")).toBeLessThan(fam.indexOf("Hiragino Sans"));
});
