// Settings › Terminal › Import from… on the mock host (MockHost termImportList / termImportRead stand in for the shell's
// term_import.rs): the menu lists the apps with a prefs file, a profile shows in the preview, Use makes it the theme the
// open terminal draws with (and it outlives a restart), a font that is not installed leaves the font as it was, a
// profile that cannot be read is greyed out, and the button is macOS's only. Shots when OMHER_SHOTS=<dir> is set.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS ? join(process.env.OMHER_SHOTS) : "";

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

async function open(page: Page, { platform = "MacIntel", theme = "dark" }: { platform?: string; theme?: string } = {}) {
  await page.addInitScript(
    ([p, th]) => {
      if (!sessionStorage.getItem("__kept")) {
        for (const k of ["omher.term", "omher.sessions.recent", "omher.sessions.open", "omher.resume"]) localStorage.removeItem(k);
        localStorage.setItem("omher.theme", th);
      }
      const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
      w.__omherPickFolder = "/home/you/code/web-app";
      w.__omherMockAgents = ["claude", "codex", "omh"];
      Object.defineProperty(navigator, "platform", { get: () => p });
    },
    [platform, theme],
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function terminalClaude(page: Page) {
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-agent-claude").click();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
}

async function settings(page: Page) {
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-terminal").click();
  await expect(page.getByTestId("term-preview").locator(".xterm-rows")).toContainText("42 passed");
}

/** The theme background and font of the terminal inside `scope` (the dev build's hook on every xterm). */
const termLook = (page: Page, scope: string) =>
  page.evaluate((sel) => {
    type T = { element?: HTMLElement; options: { theme?: { background?: string; red?: string }; fontFamily?: string; fontSize?: number } };
    const set = (window as unknown as { __omherTerms?: Set<T> }).__omherTerms;
    const t = [...(set ?? [])].find((x) => x.element?.isConnected && x.element.closest(sel));
    return t ? { bg: t.options.theme?.background, red: t.options.theme?.red, font: t.options.fontFamily, size: t.options.fontSize } : null;
  }, scope);

type Call = { op: string; key?: string };
const importCalls = (page: Page) =>
  page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []).filter((c) => c.op.startsWith("import.")));

test("Import from… iTerm2: menu, profile in the preview, Use -> the open terminal draws the imported theme and keeps it", async ({ page }) => {
  await open(page);
  await terminalClaude(page);
  const before = await termLook(page, ".term-host");
  expect(before?.bg).toBe("#0b090d");
  await settings(page);
  // nothing is read before the button is pressed
  expect(await importCalls(page)).toEqual([]);

  await page.getByTestId("term-import").click();
  await expect(page.getByTestId("term-import-menu").getByRole("menuitem")).toHaveText(["iTerm2", "Terminal"]);
  expect(await importCalls(page)).toEqual([{ op: "import.list" }]);
  await page.getByTestId("term-import-iterm2").click();

  const rows = page.getByTestId("term-import-profiles").getByRole("radio");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("Harbor Night");
  await expect(rows.first()).toContainText("Default");
  await expect(rows.first()).toHaveAttribute("aria-checked", "true");
  // the default profile is in the preview at once; the saved settings are not touched yet
  await expect.poll(async () => (await termLook(page, "[data-testid=term-preview]"))?.bg).toBe("#14202b");
  expect(await page.evaluate(() => localStorage.getItem("omher.term"))).toBeNull();
  await expect(page.getByTestId("term-import-font")).toHaveText(/Menlo 14|is not on this computer/);

  await page.getByTestId("term-import-use").click();
  await expect(page.getByTestId("term-import-panel")).toHaveCount(0);
  await expect(page.getByTestId("term-import-done")).toContainText("Harbor Night");
  const stored = JSON.parse((await page.evaluate(() => localStorage.getItem("omher.term")))!);
  expect(stored.themeDark).toBe("custom");
  expect(stored.custom.name).toBe("Harbor Night");
  expect(stored.custom.colors.red).toBe("#e06c75");
  // the kept theme is listed as the person's own and is the one picked
  await expect(page.getByTestId("term-themes-custom").getByRole("radio")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("term-themes-custom")).toContainText("Harbor Night");

  // the session's terminal takes it
  await page.locator("[data-testid=session-list] .ss-row .ss-open").first().click();
  await expect.poll(async () => (await termLook(page, ".term-host"))?.bg).toBe("#14202b");
  expect((await termLook(page, ".term-host"))?.red).toBe("#e06c75");

  // a restart reads it back from omher's own settings; the other app is not read again
  await page.evaluate(() => sessionStorage.setItem("__kept", "1"));
  await page.reload();
  await settings(page);
  await expect.poll(async () => (await termLook(page, "[data-testid=term-preview]"))?.bg).toBe("#14202b");
  expect(await importCalls(page)).toEqual([]);
});

test("a font that is not installed leaves the font as it is; Cancel puts the preview back", async ({ page }) => {
  await open(page);
  await settings(page);
  await page.getByTestId("term-font").fill("Courier New");
  await page.getByTestId("term-import").click();
  await page.getByTestId("term-import-iterm2").click();
  await page.getByTestId("term-import-profile-1").click();
  await expect(page.getByTestId("term-import-font")).toHaveText("NoSuchFontAnywhere-Regular is not on this computer: the font stays as it is.");
  await expect.poll(async () => (await termLook(page, "[data-testid=term-preview]"))?.bg).toBe("#fbf8f0");
  await page.getByTestId("term-import-cancel").click();
  await expect.poll(async () => (await termLook(page, "[data-testid=term-preview]"))?.bg).toBe("#0b090d");

  await page.getByTestId("term-import").click();
  await page.getByTestId("term-import-iterm2").click();
  await page.getByTestId("term-import-profile-1").click();
  await page.getByTestId("term-import-use").click();
  const stored = JSON.parse((await page.evaluate(() => localStorage.getItem("omher.term")))!);
  expect(stored.fontFamily).toBe("Courier New");
  expect(stored.fontSize).toBe(13);
  expect(stored.custom.name).toBe("Paper");
  await expect(page.getByTestId("term-font")).toHaveValue("Courier New");
});

test("Terminal: a profile that cannot be read is greyed out and cannot be used", async ({ page }) => {
  await open(page);
  await settings(page);
  await page.getByTestId("term-import").click();
  await page.getByTestId("term-import-terminal").click();
  const broken = page.getByTestId("term-import-profile-1");
  await expect(broken).toContainText("Archived");
  await expect(broken).toContainText("cannot read this profile");
  await expect(broken).toHaveAttribute("aria-disabled", "true");
  await broken.click({ force: true });
  await expect(broken).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("term-import-profile-0")).toHaveAttribute("aria-checked", "true");
  expect(await importCalls(page)).toEqual([{ op: "import.list" }, { op: "import.read", key: "terminal" }]);
});

test("only the apps with a prefs file are offered; none says so", async ({ page }) => {
  await page.addInitScript(() => {
    (window as unknown as { __omherMockImport: unknown }).__omherMockImport = {};
  });
  await open(page);
  await settings(page);
  await page.getByTestId("term-import").click();
  await expect(page.getByTestId("term-import-none")).toBeVisible();
  await expect(page.getByTestId("term-import-menu").getByRole("menuitem")).toHaveCount(0);
});

test("the bar's controls do not overlap at 1280 and 900 wide with the button shown", async ({ page }) => {
  await open(page);
  await settings(page);
  for (const width of [1280, 900]) {
    await page.setViewportSize({ width, height: 700 });
    const boxes = await Promise.all(["term-slot", "term-search", "term-import"].map((id) => page.getByTestId(id).boundingBox()));
    const [slot, search, btn] = boxes.map((b) => b!);
    const apart = (a: typeof slot, b: typeof slot) => a.x + a.width <= b.x + 0.5 || b.x + b.width <= a.x + 0.5 || a.y + a.height <= b.y + 0.5 || b.y + b.height <= a.y + 0.5;
    expect(apart(slot, search), `${width}: slot/search`).toBe(true);
    expect(apart(search, btn), `${width}: search/button`).toBe(true);
    // the segmented control shows its whole labels
    const clipped = await page.getByTestId("term-slot").locator("button").evaluateAll((els) => els.some((e) => e.scrollWidth > e.clientWidth + 1));
    expect(clipped, `${width}: slot labels clipped`).toBe(false);
  }
});

test("the button is macOS's: not on Windows", async ({ page }) => {
  await open(page, { platform: "Win32" });
  await settings(page);
  await expect(page.getByTestId("term-search")).toBeVisible();
  await expect(page.getByTestId("term-import")).toHaveCount(0);
});

for (const theme of ["dark", "light"] as const) {
  test(`shots: import menu and preview (${theme})`, async ({ page }) => {
    test.skip(!SHOTS, "no shot folder");
    mkdirSync(SHOTS, { recursive: true });
    await open(page, { theme });
    await settings(page);
    const shot = async (name: string) => {
      await page.waitForTimeout(350);
      await page.screenshot({ path: join(SHOTS, `${name}-${theme}.png`), animations: "disabled" });
    };
    await page.getByTestId("term-import").click();
    await expect(page.getByTestId("term-import-menu").getByRole("menuitem")).toHaveCount(2);
    await shot("import-menu");
    await page.getByTestId("term-import-iterm2").click();
    await expect.poll(async () => (await termLook(page, "[data-testid=term-preview]"))?.bg).toBe("#14202b");
    await shot("import-preview");
    await page.getByTestId("term-import").click();
    await page.getByTestId("term-import-terminal").click();
    await expect(page.getByTestId("term-import-profile-1")).toContainText("cannot read this profile");
    await shot("import-terminal");
    // a 900x700 window: the bar wraps, nothing overlaps
    await page.setViewportSize({ width: 900, height: 700 });
    await page.getByTestId("term-import").click();
    await page.getByTestId("term-import-iterm2").click();
    await shot("import-narrow");
  });
}
