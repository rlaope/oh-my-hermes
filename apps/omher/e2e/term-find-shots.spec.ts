// Shots of find and a link hover in a session terminal, dark and light. Written when OMHER_SHOTS=<dir> is set
// (otherwise skipped). The terminal's output is fed through the engine's real feed().
import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { feed, mock, modKey, newTerminal, openApp, pointAt } from "./term-find-helpers";

const SHOTS = process.env.OMHER_SHOTS || "";

/** Output of an agent that has been working a while: plain lines, a few colours, the word "build" 14 times. */
const OUTPUT = [
  "\x1b[1mRunning checks\x1b[0m",
  ...Array.from({ length: 14 }, (_, i) => `  \x1b[32m✓\x1b[0m build step ${i + 1} of 14 finished`),
  "",
  "\x1b[33m!\x1b[0m 2 warnings, see https://example.com/docs/warnings for details",
  "\x1b[2mrun `pnpm test` to continue\x1b[0m",
  "",
].join("\r\n");

for (const theme of ["dark", "light"] as const) {
  test(`find shot (${theme})`, async ({ page }) => {
    test.skip(!SHOTS, "no shot folder");
    mkdirSync(SHOTS, { recursive: true });
    await mock("mock.reset");
    // staged shots carry no bot named after the product: the default profile shows as "Juno"
    await mock("bots.rename", { bot: "default", name: "Juno" });
    await openApp(page, { theme });
    await newTerminal(page);
    await feed(page, `\r\n${OUTPUT}`);
    // closed: the bar is not in the page, so it covers no output
    await expect(page.getByTestId("term-find")).toHaveCount(0);
    await page.keyboard.press(`${await modKey(page)}+f`);
    await page.getByTestId("term-find-input").fill("build");
    await expect(page.getByTestId("term-find-count")).toHaveText(/ of 14$/);
    await page.keyboard.press("Enter");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("term-find-count")).toHaveText(/^\d+ of 14$/);
    await page.mouse.move(640, 790);
    await page.waitForTimeout(450);
    await page.screenshot({ path: join(SHOTS, `term-find-${theme}.png`), animations: "disabled" });
  });
}

test("link hover shot (dark)", async ({ page }) => {
  test.skip(!SHOTS, "no shot folder");
  mkdirSync(SHOTS, { recursive: true });
  await mock("mock.reset");
  await mock("bots.rename", { bot: "default", name: "Juno" });
  await openApp(page, { theme: "dark" });
  await newTerminal(page);
  await feed(page, `\r\n${OUTPUT}`);
  const p = await pointAt(page, "https://example.com/docs/warnings", 0, 26);
  await page.mouse.move(p.x - 4, p.y);
  await page.mouse.move(p.x, p.y);
  await expect(page.locator(".term-linktip")).toBeVisible();
  await page.waitForTimeout(450);
  await page.screenshot({ path: join(SHOTS, "term-link-hover-dark.png"), animations: "disabled" });
});
