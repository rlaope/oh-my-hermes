// Settings › Terminal › Customize colours: a colour changed there shows in the preview at once, reaches a terminal that
// is open, stays after a reload, and Reset goes back. The dark and the light app theme keep their own set. The pane
// border colour shows on a split's divider. Shots of the editor (dark and light) when OMHER_SHOTS=<dir> is set.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { mock } from "./term-find-helpers";

const SHOTS = process.env.OMHER_SHOTS || "";

type T = { element?: HTMLElement; options: { theme?: Record<string, string> } };
/** A theme colour of the Settings preview (`pv`) or of the open session terminal. */
const color = (page: Page, where: "pv" | "session", key: string) =>
  page.evaluate(
    ([w, k]) => {
      const set = (window as unknown as { __omherTerms?: Set<T> }).__omherTerms;
      // the session terminal may be out of the page while Settings is in front (kept, not disposed)
      const t = [...(set ?? [])].reverse().find((x) => (w === "pv" ? x.element?.isConnected && x.element.closest(".term-pv") : x.element && !x.element.closest(".term-pv")));
      return t?.options.theme?.[k] ?? null;
    },
    [where, key] as const,
  );

/** The app on the mock host; the first load starts clean, a reload keeps what it stored. The preview's colours are the
 *  theme's as they are (contrast `theme`), so a cell shows the exact colour picked. */
async function openApp(page: Page, o: { theme: "dark" | "light" }) {
  await page.addInitScript((theme) => {
    if (!sessionStorage.getItem("__kept")) {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume"]) localStorage.removeItem(k);
      localStorage.setItem("omher.term", JSON.stringify({ contrast: "theme" }));
    }
    localStorage.setItem("omher.theme", theme);
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/home/you/code/web-app";
    w.__omherMockAgents = ["claude", "codex", "omh"];
  }, o.theme);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** The colour the preview draws a cell in (#rrggbb), as the page computed it. */
const cellColour = (page: Page, text: string) =>
  page.evaluate((w) => {
    const rows = document.querySelector('[data-testid="term-preview"] .xterm-rows')!;
    const span = [...rows.querySelectorAll<HTMLElement>("span")].find((s) => (s.textContent ?? "").trim() === w);
    if (!span) return null;
    const m = /rgba?\((\d+), (\d+), (\d+)/.exec(getComputedStyle(span).color)!;
    return `#${[m[1], m[2], m[3]].map((v) => Number(v).toString(16).padStart(2, "0")).join("")}`;
  }, text);

async function settings(page: Page) {
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  await expect(page.getByTestId("term-preview").locator(".xterm-rows")).toContainText("42 passed");
}

type Sessions = { startTerminal(a: string, cwd: string): string };
const start = (page: Page, cwd: string) => page.evaluate((c) => (window as unknown as { __omherSessions: Sessions }).__omherSessions.startTerminal("shell", c), cwd);

async function setHex(page: Page, key: string, hex: string) {
  const f = page.getByTestId(`term-color-${key}-hex`);
  await f.fill(hex);
  await f.press("Enter");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

for (const mode of ["dark", "light"] as const) {
  test(`${mode} app theme: red edited shows in the preview and an open terminal, stays after a reload, and Reset goes back`, async ({ page }) => {
    await openApp(page, { theme: mode });
    const id = await start(page, "/home/you/code/web-app");
    await expect(page.locator(`[data-testid="terminal"][data-session="${id}"] .xterm-rows`)).toContainText("login shell in");
    const before = await color(page, "session", "red");
    expect(before).toBeTruthy();

    await settings(page);
    await page.getByTestId("term-colors-open").click();
    await expect(page.getByTestId("term-colors")).toHaveAttribute("data-mode", mode);
    // starts from the theme in force
    await expect(page.getByTestId("term-color-red-hex")).toHaveValue(before!.slice(0, 7));
    await expect(page.getByTestId("term-colors-reset")).toBeDisabled();
    // a bad hex is refused and changes nothing
    await page.getByTestId("term-color-red-hex").fill("#12345");
    await expect(page.getByTestId("term-color-red-hex")).toHaveAttribute("aria-invalid", "true");
    expect(await color(page, "pv", "red")).toBe(before);

    await setHex(page, "red", "#12ab34");
    await expect.poll(() => color(page, "pv", "red")).toBe("#12ab34");
    // the open terminal took it too (the relook path), while Settings is in front
    await expect.poll(() => color(page, "session", "red")).toBe("#12ab34");
    // a red cell in the preview (the sample's ✗) is drawn in it
    await expect.poll(() => cellColour(page, "✗")).toBe("#12ab34");
    // the slot of the other app theme is unchanged
    const stored = await page.evaluate(() => JSON.parse(localStorage.getItem("omher.term")!));
    const other = mode === "dark" ? "light" : "dark";
    expect(stored.edits[mode]).toEqual({ base: `omher-${mode}`, colors: { red: "#12ab34" } });
    expect(stored.edits[other]).toBeNull();
    expect(stored[mode === "dark" ? "themeLight" : "themeDark"]).toBe(`omher-${other}`);
    // the edited theme is listed under Yours and picked
    await expect(page.getByTestId("term-theme-edited")).toHaveAttribute("aria-checked", "true");

    // a reload keeps it: the terminal comes back in the edited colours
    await page.evaluate(() => sessionStorage.setItem("__kept", "1"));
    await page.reload();
    await settings(page);
    await expect.poll(() => color(page, "pv", "red")).toBe("#12ab34");
    await page.getByTestId("term-colors-open").click();
    await expect(page.getByTestId("term-color-red-hex")).toHaveValue("#12ab34");

    // Reset: back to the theme the edits started from
    await page.getByTestId("term-colors-reset").click();
    await expect.poll(() => color(page, "pv", "red")).toBe(before);
    await expect(page.getByTestId("term-color-red-hex")).toHaveValue(before!.slice(0, 7));
    await expect(page.getByTestId("term-theme-edited")).toHaveCount(0);
    expect((await page.evaluate(() => JSON.parse(localStorage.getItem("omher.term")!))).edits[mode]).toBeNull();
  });
}

test("the pane border colour shows on a split's divider and the preview's frame", async ({ page }) => {
  await openApp(page, { theme: "dark" });
  const a = await start(page, "/home/you/code/web-app");
  await expect(page.locator(`[data-testid="terminal"][data-session="${a}"] .xterm-rows`)).toContainText("login shell in");
  await settings(page);
  await page.getByTestId("term-colors-open").click();
  await setHex(page, "border", "#ff00aa");
  await expect(page.getByTestId("term-preview")).toHaveCSS("border-top-color", "rgb(255, 0, 170)");
  // a split of the open terminal: its divider is the border colour
  await page.locator("[data-testid=session-list] .ss-row .ss-open").first().click();
  const term = page.locator(`[data-testid="terminal"][data-session="${a}"]`);
  await term.locator(".xterm-helper-textarea").focus();
  const mac = await page.evaluate(() => /Mac|iPhone|iPad/.test(navigator.platform));
  await page.keyboard.press(mac ? "Meta+d" : "Control+Shift+D");
  await expect(page.getByTestId("session-split")).toHaveAttribute("data-panes", "2");
  await expect(page.getByTestId("split-divider")).toHaveCSS("background-color", "rgb(255, 0, 170)");
});

for (const mode of ["dark", "light"] as const) {
  test(`shot: the colour editor, ${mode}`, async ({ page }) => {
    test.skip(!SHOTS, "OMHER_SHOTS is not set");
    await page.setViewportSize({ width: 1280, height: 1000 });
    await openApp(page, { theme: mode });
    await settings(page);
    await page.getByTestId("term-colors-open").click();
    await setHex(page, "red", mode === "dark" ? "#ff4f7a" : "#c4003a");
    await setHex(page, "border", mode === "dark" ? "#7a5cff" : "#6a4cd8");
    await expect.poll(() => color(page, "pv", "red")).toBe(mode === "dark" ? "#ff4f7a" : "#c4003a");
    mkdirSync(SHOTS, { recursive: true });
    await page.getByTestId("term-preview").scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(SHOTS, `colour-editor-${mode}.png`), fullPage: false });
    await page.getByTestId("term-colors").screenshot({ path: join(SHOTS, `colour-editor-${mode}-swatches.png`) });
  });
}
