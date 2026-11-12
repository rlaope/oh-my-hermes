// Shots of the finished terminal work, dark and light, written when OMHER_SHOTS=<dir> is set (otherwise skipped):
// Settings > Terminal, a session in Dracula and one in Solarized Light, find with matches, the theme picker
// filtered by a search, and a link's hover hint. The terminal's output is a git log and a test run, fed through the
// engine's real feed(); the names are neutral (web-app, api-server) and no bot is named after the product.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { feed, mock, modKey, newTerminal, openApp, pointAt } from "./term-find-helpers";

const SHOTS = process.env.OMHER_SHOTS || "";

const E = "\x1b[";
const c = (code: string, text: string) => `${E}${code}m${text}${E}0m`;
const PROMPT = `${c("1;34", "~/code/web-app")} ${c("32", "main")} ${c("35", "❯")} `;
const hash = (h: string) => c("33", h);
const refs = (...names: string[]) => `${c("33", "(")}${names.join(c("33", ", "))}${c("33", ")")}`;
const ok = (file: string, tests: number, ms: number) => ` ${c("32", "✓")} ${c("2", "src/")}${file} ${c("2", `(${tests} tests)`)} ${c("2", `${ms}ms`)}`;

/** What a person sees after a look at the history and a test run: plain program output, coloured as git and a test
 *  runner colour it. The screen and its scrollback are cleared first, so the mock program's banner is gone. */
const OUTPUT = [
  `${E}2J${E}3J${E}H${PROMPT}git log --oneline --graph -8`,
  `${c("31", "*")} ${hash("a1b2c3d")} ${refs(c("1;36", "HEAD -> ") + c("1;32", "main"), c("1;31", "origin/main"))} fix(api): retry a dropped upstream connection once`,
  `${c("31", "*")} ${hash("9f8e7d6")} feat(web): keyboard shortcuts for the session list`,
  `${c("31", "*")}   ${hash("5c4b3a2")} Merge branch 'feat/session-export'`,
  `${c("31", "|")}${c("32", "\\")}`,
  `${c("31", "|")} ${c("32", "*")} ${hash("3d2e1f0")} feat(api): export a session as JSON`,
  `${c("31", "|")} ${c("32", "*")} ${hash("7a6b5c4")} test(api): cover the export route`,
  `${c("31", "|")}${c("32", "/")}`,
  `${c("31", "*")} ${hash("1e2d3c4")} ${refs(c("1;33", "tag: v0.8.2"))} chore: release 0.8.2`,
  `${c("31", "*")} ${hash("8b7a6f5")} docs: how to run api-server locally, see https://example.com/docs/api-server`,
  "",
  `${PROMPT}pnpm test`,
  "",
  ` ${c("1;30;46", " RUN ")} ${c("36", "v3.2.7")} ${c("2", "~/code/web-app")}`,
  "",
  ok("session/list.test.ts", 12, 48),
  ok("session/export.test.ts", 7, 31),
  ok("api/retry.test.ts", 9, 112),
  ` ${c("33", "❯")} ${c("2", "src/")}api/client.test.ts ${c("2", "(6 tests | ")}${c("31", "1 failed")}${c("2", ")")} ${c("2", "87ms")}`,
  `   ${c("31", "× retries once, then gives up")} ${c("2", "41ms")}`,
  `     ${c("31", "→ expected 2 to be 1")}`,
  ok("ui/shortcuts.test.ts", 15, 22),
  "",
  `${c("2", " Test Files ")} ${c("1;31", "1 failed")} ${c("2", "|")} ${c("1;32", "4 passed")} ${c("2", "(5)")}`,
  `${c("2", "      Tests ")} ${c("1;31", "1 failed")} ${c("2", "|")} ${c("1;32", "48 passed")} ${c("2", "(49)")}`,
  `${c("2", "   Duration ")} 1.24s`,
  "",
  PROMPT,
].join("\r\n");

const LINK = "https://example.com/docs/api-server";

async function stage(page: Page, theme: "dark" | "light", term: Record<string, unknown> = {}) {
  await mock("mock.reset");
  // staged shots carry no bot named after the product: the default profile shows as "Juno"
  await mock("bots.rename", { bot: "default", name: "Juno" });
  await openApp(page, { theme, term });
}

async function session(page: Page) {
  await newTerminal(page);
  await feed(page, OUTPUT);
  await expect(page.locator(".xterm-rows")).toContainText("48 passed");
  await expect(page.locator(".xterm-rows")).not.toContainText("(mock)");
}

async function settings(page: Page) {
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  // the preview is wide enough here for its second pane
  await expect(page.getByTestId("term-preview").locator(".xterm-rows")).toContainText("api-server");
}

async function shot(page: Page, name: string, rest: { x: number; y: number } | null = { x: 640, y: 800 }) {
  if (rest) await page.mouse.move(rest.x, rest.y);
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled" });
}

for (const theme of ["dark", "light"] as const) {
  // the app theme's own pick: Dracula for dark, Solarized Light for light
  const pick = theme === "dark" ? "dracula" : "solarized-light";
  const picked = { [theme === "dark" ? "themeDark" : "themeLight"]: pick };

  test.describe(`final shots (${theme})`, () => {
    test.use({ colorScheme: theme });
    test.beforeEach(() => {
      test.skip(!SHOTS, "no shot folder");
      mkdirSync(SHOTS, { recursive: true });
    });

    test(`Settings > Terminal, and the theme picker filtered by a search (${theme})`, async ({ page }) => {
      await stage(page, theme);
      await session(page);
      await settings(page);
      // the preview uses its width: text reaches into the last fifth of the box
      const used = await page.getByTestId("term-preview").evaluate((pv) => {
        const box = pv.getBoundingClientRect();
        let right = 0;
        for (const s of pv.querySelectorAll<HTMLElement>(".xterm-rows span")) if ((s.textContent ?? "").trim()) right = Math.max(right, s.getBoundingClientRect().right);
        return (right - box.left) / box.width;
      });
      expect(used).toBeGreaterThan(0.8);
      expect(used).toBeLessThanOrEqual(1);
      await page.getByTestId("term-settings").locator(".st-gh").first().click(); // no field holds the keyboard
      await shot(page, `term-final-settings-${theme}`);

      await page.getByTestId("term-search").fill("github");
      await expect(page.locator("[data-testid=term-themes] .tm-row")).toHaveCount(6);
      await page.getByTestId("term-settings").locator(".st-gh").first().click();
      await shot(page, `term-final-picker-${theme}`);
    });

    test(`a terminal session in ${pick} (${theme})`, async ({ page }) => {
      await stage(page, theme, picked);
      await session(page);
      await shot(page, `term-final-${pick === "dracula" ? "dracula-dark" : "solarized-light"}`);
    });

    test(`find with matches (${theme})`, async ({ page }) => {
      await stage(page, theme, picked);
      await session(page);
      await page.keyboard.press(`${await modKey(page)}+f`);
      await page.getByTestId("term-find-input").fill("test");
      await expect(page.getByTestId("term-find-count")).toHaveText(/^\d+ of \d+$/);
      // on to a match in the middle of the screen
      for (let i = 0; i < 4; i++) await page.keyboard.press("Enter");
      await expect(page.getByTestId("term-find-count")).toHaveText(/^\d+ of \d+$/);
      await shot(page, `term-final-find-${theme}`);
    });

    test(`a link's hover hint (${theme})`, async ({ page }) => {
      await stage(page, theme, picked);
      await session(page);
      const p = await pointAt(page, LINK, 0, 20);
      await page.mouse.move(p.x - 4, p.y);
      await page.mouse.move(p.x, p.y);
      await expect(page.locator(".term-linktip")).toBeVisible();
      await shot(page, `term-final-link-${theme}`, null);
    });
  });
}
