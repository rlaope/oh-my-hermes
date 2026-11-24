// Google Antigravity CLI (`agy`) in TERMINALS and Settings › Agents, on the mock host (the shell's row comes from
// src/sessions/mockAcpAgents.json, which a Rust test pins to `ACP_LIST`):
//   1. installed: the + menu offers Antigravity with its official mark (Lobe Icons' antigravity-color.svg, never a
//      letter); picking it starts `agy` as a terminal session (the page sends the id only, no arguments);
//   2. not installed: More agents opens its row with the official installer line, word for word;
//   3. a Shell whose foreground program is `agy` (the shell's fg.rs answer) shows the Antigravity mark and name on
//      its row, and the shell icon again when it leaves;
//   4. Settings › Agents lists it as an ACP agent, installed or not.
// Shots: OMHER_SHOTS=<dir> -> agy-plus-menu-{dark,light}.png, agy-plus-missing-{dark,light}.png,
// agy-settings-agents-{dark,light}.png, agy-term-row-{dark,light}.png
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const INSTALL = "curl -fsSL https://antigravity.google/cli/install.sh | bash";

async function mock(op: string): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op }));
  });
  ws.close();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled", caret: "initial" });
}

async function open(page: Page, installed: string[], theme: "dark" | "light" = "dark") {
  await page.addInitScript(
    ([list, t]) => {
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume"]) localStorage.removeItem(k);
      localStorage.setItem("omher.theme", t as string);
      const w = window as unknown as Record<string, unknown>;
      w.__omherPickFolder = "/home/you/code/web-app";
      w.__omherMockAgents = list as string[];
    },
    [installed, theme] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

async function plus(page: Page) {
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await page.waitForFunction(() => document.querySelector(".ss-pop")?.getAnimations().every((a) => a.playState !== "running"));
}

type Call = { op: string; agent?: string; cwd?: string; args?: unknown };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));

for (const theme of ["dark", "light"] as const) {
  test(`installed: the + menu offers Antigravity with its official mark and starts agy in a terminal (${theme})`, async ({ page }) => {
    await open(page, ["claude", "codex", "omh", "agy"], theme);
    await plus(page);
    const menu = page.getByTestId("session-menu");
    const row = menu.getByTestId("session-agent-agy");
    await expect(row).toBeVisible();
    await expect(row.locator(".ss-l")).toHaveText("Antigravity");
    // the mark its shell row names, drawn as the vendor's svg (its own colours), never a letter
    const mark = row.locator('svg[data-agent]:not([data-agent="letter"])');
    await expect(mark).toHaveCount(1);
    const box = (await mark.boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(14);
    expect(box.height).toBeGreaterThanOrEqual(14);
    // the mark is not clipped by its row
    const rb = (await row.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(rb.x);
    expect(box.y).toBeGreaterThanOrEqual(rb.y);
    expect(box.y + box.height).toBeLessThanOrEqual(rb.y + rb.height + 0.5);
    await expect(page.getByTestId("session-way")).toHaveCount(0);
    await page.mouse.move(1200, 780);
    await shot(page, `agy-plus-menu-${theme}`);
    await row.click();
    await expect(page.getByTestId("terminal")).toBeVisible();
    await expect(page.getByTestId("session-chat")).toHaveCount(0);
    await expect
      .poll(async () => (await calls(page)).filter((c) => c.op === "start"))
      .toEqual([expect.objectContaining({ op: "start", agent: "agy", cwd: "/home/you" })]);
    // the id, a folder and a size: no program path, argument or command line goes out
    const start = (await calls(page)).find((c) => c.op === "start")!;
    expect(Object.keys(start).sort()).toEqual(["agent", "cols", "cwd", "id", "op", "rows"]);
    // a terminal, never a chat: no structured-mode start
    expect((await calls(page)).some((c) => c.op === "chat.start")).toBe(false);
  });

  test(`not installed: More agents shows Antigravity with its official installer line (${theme})`, async ({ page }) => {
    await open(page, ["claude", "codex", "omh"], theme);
    await plus(page);
    const menu = page.getByTestId("session-menu");
    await menu.getByTestId("session-more").click();
    const row = menu.getByTestId("session-agent-agy");
    await expect(row).toBeAttached();
    await row.evaluate((e) => e.scrollIntoView({ block: "nearest" }));
    await expect(row.locator(".ss-l")).toHaveText("Antigravity");
    await expect(menu.getByTestId("session-install-agy")).toHaveText(INSTALL);
    await expect(row.locator('svg[data-agent]:not([data-agent="letter"])')).toHaveCount(1);
    // the whole line is in the row, none cut
    const line = (await menu.getByTestId("session-install-agy").boundingBox())!;
    const rb = (await row.boundingBox())!;
    expect(line.y + line.height).toBeLessThanOrEqual(rb.y + rb.height + 0.5);
    expect(line.x + line.width).toBeLessThanOrEqual(rb.x + rb.width + 0.5);
    await page.mouse.move(1200, 780);
    await shot(page, `agy-plus-missing-${theme}`);
  });

  test(`a Shell running agy shows the Antigravity mark on its row (${theme})`, async ({ page }) => {
    await open(page, ["claude", "codex", "omh", "agy"], theme);
    await plus(page);
    await page.getByTestId("session-agent-shell").click();
    await expect(page.getByTestId("terminal")).toBeVisible();
    const id = await page.locator('[data-testid^="session-s"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!).find((x) => /^session-s\d+$/.test(x))!);
    const sid = id.slice("session-".length);
    const setFg = (agent: string | null) =>
      page.evaluate(([i, a]) => (window as unknown as { __omherSessions: { setSessionFg(id: string, a: string | null): void } }).__omherSessions.setSessionFg(i as string, a as string | null), [sid, agent] as const);
    const row = page.getByTestId(id);
    await expect(row.getByTestId("term-row-mark")).toHaveAttribute("data-agent", "shell");
    // fg.rs answers the agent id `agy` for the native binary in the terminal's foreground
    await setFg("agy");
    await expect(row.getByTestId("term-row-mark")).toHaveAttribute("data-agent", "antigravity");
    await expect(row.getByTestId("term-row-mark").locator("svg, img").first()).toBeVisible();
    await expect(row.getByTestId("session-name")).toHaveText("Antigravity");
    await page.mouse.move(1200, 780);
    await shot(page, `agy-term-row-${theme}`);
    await setFg(null);
    await expect(row.getByTestId("term-row-mark")).toHaveAttribute("data-agent", "shell");
  });

  test(`Settings › Agents lists Antigravity as an ACP agent (${theme})`, async ({ page }) => {
    await open(page, ["claude", "codex", "omh", "agy"], theme);
    await page.getByTestId("nav-settings").click();
    await page.getByTestId("settings-nav-agents").click();
    const row = page.getByTestId("agents-row-agy");
    await expect(row).toBeVisible();
    await expect(row).toContainText("Antigravity");
    await expect(row).toContainText("Installed");
    await expect(page.getByTestId("agents-tier-agy")).toHaveText("ACP");
    await expect(row.locator('svg[data-agent]:not([data-agent="letter"])')).toHaveCount(1);
    await row.scrollIntoViewIfNeeded();
    await page.mouse.move(1200, 780);
    await shot(page, `agy-settings-agents-${theme}`);
  });
}
