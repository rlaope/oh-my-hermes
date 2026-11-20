// The chat timeline's way back (kasaterm's "Jump to bottom" pill and pinned own message): scrolled up more than a
// screen, a pill bottom-centre takes the view back to the bottom ("· N new" once messages came in meanwhile); End or
// ⌘↓ / Ctrl+End in the timeline does the same. While the person reads the long answer below their last message, that
// message stays as one muted line at the top; a click brings the bubble back, and it goes when the bubble is in view.
// Shots (dark/light): OMHER_SHOTS=<dir>.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { mock, usePlatform } from "./term-find-helpers";

const SHOTS = process.env.OMHER_SHOTS || "";
const ASK = "Walk me through the whole retry design, every piece of it";
const LONG = Array.from({ length: 40 }, (_, i) => `Paragraph ${i + 1}: the retry layer keeps one budget per upstream and backs off with jitter.`).join("\n\n");

test.beforeEach(async () => {
  await mock("mock.reset");
});

const tl = (page: Page) => page.getByTestId("timeline");
const gap = (page: Page) => tl(page).evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight);

async function longAnswer(page: Page, theme: "dark" | "light" = "dark") {
  await usePlatform(page);
  await page.addInitScript((th) => localStorage.setItem("omher.theme", th), theme);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  await mock("mock.answer", { bot: "kami", text: LONG });
  await page.getByTestId("composer").fill(ASK);
  await page.getByTestId("composer").press("Enter");
  await expect(tl(page).getByText("Paragraph 40:")).toBeVisible();
  await expect(page.getByTestId("stop")).toHaveCount(0);
}

test("scrolled up: the pill shows, counts new messages, and a click goes back to the bottom and sticks again", async ({ page }) => {
  await longAnswer(page);
  // at the bottom: no pill
  await expect.poll(() => gap(page)).toBeLessThan(40);
  await expect(page.getByTestId("jump-bottom")).toHaveCount(0);
  // the person scrolls up more than a screen
  await tl(page).hover();
  await page.mouse.wheel(0, -2500);
  const pill = page.getByTestId("jump-bottom");
  await expect(pill).toBeVisible();
  await expect(pill).toHaveText("Jump to bottom");
  // a message arrives meanwhile: the view stays where it is and the pill counts it
  const before = await tl(page).evaluate((el) => el.scrollTop);
  await mock("mock.emit", { events: [{ event: "message", bot: "kami", id: "late-1", text: "One more thing about the budget." }] });
  await expect(pill).toHaveText("Jump to bottom · 1 new");
  await mock("mock.emit", { events: [{ event: "message", bot: "kami", id: "late-2", text: "And the jitter bounds." }] });
  await expect(pill).toHaveText("Jump to bottom · 2 new");
  expect(Math.abs((await tl(page).evaluate((el) => el.scrollTop)) - before)).toBeLessThan(4);
  // the pill is centred over the column, above the composer
  const [pb, cb, tb] = [(await pill.boundingBox())!, (await page.getByTestId("composer").boundingBox())!, (await tl(page).boundingBox())!];
  expect(pb.y + pb.height).toBeLessThanOrEqual(cb.y);
  expect(Math.abs(pb.x + pb.width / 2 - (tb.x + tb.width / 2))).toBeLessThan(4);
  // quiet: filled, small radius, no border ring
  const st = await pill.evaluate((el) => ({ bg: getComputedStyle(el).backgroundColor, radius: getComputedStyle(el).borderTopLeftRadius, border: getComputedStyle(el).borderTopWidth }));
  expect(st.bg).not.toBe("rgba(0, 0, 0, 0)");
  expect(parseFloat(st.radius)).toBeLessThanOrEqual(8);
  expect(st.border).toBe("0px");
  if (SHOTS) {
    mkdirSync(join(SHOTS), { recursive: true });
    await page.waitForTimeout(300);
    await page.screenshot({ path: join(SHOTS, "chat-jump-dark.png") });
  }
  await pill.click();
  await expect.poll(() => gap(page)).toBeLessThan(40);
  await expect(pill).toHaveCount(0);
  // sticking again: the next message keeps the view at the bottom
  await mock("mock.emit", { events: [{ event: "message", bot: "kami", id: "late-3", text: "Last note: retries are logged." }] });
  await expect(tl(page).getByText("Last note: retries are logged.")).toBeVisible();
  await expect.poll(() => gap(page)).toBeLessThan(40);
  await expect(page.getByTestId("jump-bottom")).toHaveCount(0);
});

test("End and ⌘↓ / Ctrl+End in the timeline go to the bottom; in the composer they stay the composer's", async ({ page }) => {
  await longAnswer(page);
  const mac = await page.evaluate(() => /Mac|iPhone|iPad/.test(navigator.platform));
  await tl(page).hover();
  await page.mouse.wheel(0, -2500);
  await expect(page.getByTestId("jump-bottom")).toBeVisible();
  // in the composer: End moves its caret, the view does not move
  await page.getByTestId("composer").focus();
  await page.keyboard.press("End");
  await page.waitForTimeout(300);
  await expect(page.getByTestId("jump-bottom")).toBeVisible();
  // a click in the timeline, then End
  await tl(page).getByText("Paragraph 3:").click();
  await page.keyboard.press("End");
  await expect.poll(() => gap(page)).toBeLessThan(40);
  await expect(page.getByTestId("jump-bottom")).toHaveCount(0);
  // up again, then the platform's modifier key
  await tl(page).hover();
  await page.mouse.wheel(0, -2500);
  await expect(page.getByTestId("jump-bottom")).toBeVisible();
  await tl(page).getByText("Paragraph 3:").click();
  await page.keyboard.press(mac ? "Meta+ArrowDown" : "Control+End");
  await expect.poll(() => gap(page)).toBeLessThan(40);
});

test("the pinned own message: one line at the top while the answer below it is read; a click brings it back; gone at the top", async ({ page }) => {
  await longAnswer(page);
  const pin = page.getByTestId("pinned-own");
  // at the bottom of the long answer, the question is above the view: it is pinned, one muted line
  await expect(pin).toBeVisible();
  await expect(pin).toHaveText(ASK);
  const own = page.locator("[data-testid=bubble-user]", { hasText: ASK });
  const h = await pin.locator(".tl-pin-t").evaluate((el) => ({ h: el.getBoundingClientRect().height, ws: getComputedStyle(el).whiteSpace, lh: parseFloat(getComputedStyle(el).fontSize) }));
  expect(h.ws).toBe("nowrap");
  expect(h.h).toBeLessThan(h.lh * 3);
  // at the top of the timeline
  const [pb, tb] = [(await pin.boundingBox())!, (await tl(page).boundingBox())!];
  expect(pb.y - tb.y).toBeLessThan(20);
  if (SHOTS) {
    mkdirSync(join(SHOTS), { recursive: true });
    await page.waitForTimeout(300);
    await page.screenshot({ path: join(SHOTS, "chat-pinned-dark.png") });
  }
  // a click scrolls to the bubble, and the line goes when the bubble is back in view
  await pin.click();
  await expect(own).toBeInViewport();
  await expect(pin).toHaveCount(0);
  // reading down the answer again pins it again
  await tl(page).hover();
  await page.mouse.wheel(0, 1500);
  await expect(pin).toBeVisible();
  // the top of the timeline: the question is below or in view, nothing pinned
  await tl(page).evaluate((el) => (el.scrollTop = 0));
  await expect(pin).toHaveCount(0);
});

test("shots: the pill and the pinned header, light", async ({ page }) => {
  test.skip(!SHOTS, "OMHER_SHOTS unset");
  await longAnswer(page, "light");
  await expect(page.getByTestId("pinned-own")).toBeVisible();
  mkdirSync(join(SHOTS), { recursive: true });
  await page.waitForTimeout(300);
    await page.screenshot({ path: join(SHOTS, "chat-pinned-light.png") });
  await tl(page).hover();
  await page.mouse.wheel(0, -2500);
  await expect(page.getByTestId("jump-bottom")).toBeVisible();
  await mock("mock.emit", { events: [{ event: "message", bot: "kami", id: "late-1", text: "One more thing." }] });
  await expect(page.getByTestId("jump-bottom")).toHaveText("Jump to bottom · 1 new");
  await page.waitForTimeout(300);
    await page.screenshot({ path: join(SHOTS, "chat-jump-light.png") });
});
