// Settings › Computer (BOUNDARY rule 52), against the mock bridge: "This computer" as Hermes' own
// `computer-use permissions status --json` reads it (Install while the driver is missing, Grant access on macOS while a
// grant is missing), each bot's computer_use switch flipped with only the bot and on/off sent and the state read back,
// a failed flip showing Hermes' words, and a bot on another computer off with its reason.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

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

type Call = { op: string; params: Record<string, unknown> };
const calls = async (op: string): Promise<Call[]> => ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op === op);

async function openComputer(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("nav-settings").click();
  // the page is built: its nav entry no longer says Soon
  await expect(page.getByTestId("settings-nav-computer")).toHaveText("Computer");
  await page.getByTestId("settings-nav-computer").click();
  await expect(page.getByTestId("computer")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("no driver: Install runs Hermes' install and the page reads the computer again", async ({ page }) => {
  await mock("mock.computer", { status: { installed: false, version: null, ready: null, accessibility: null, screen_recording: null, checks: [] } });
  await openComputer(page);
  await expect(page.getByTestId("computer-platform")).toHaveText("macOS");
  await expect(page.getByTestId("computer-driver")).toHaveText("Not installed");
  await expect(page.getByTestId("computer-ready")).toHaveText("Not known");
  await expect(page.getByTestId("computer-grant")).toHaveCount(0);
  await mock("mock.computer", { ms: 600 });
  await page.getByTestId("computer-install").click();
  await expect(page.getByTestId("computer-install")).toHaveText("Installing…");
  await expect(page.getByTestId("computer-check-again")).toBeDisabled();
  await expect(page.getByTestId("computer-driver")).toHaveText("Installed · cua-driver 0.4.2");
  await expect(page.getByTestId("computer-install")).toHaveCount(0);
  // a press sends the op alone: no command, no argument
  expect((await calls("computer.install")).map((c) => c.params)).toEqual([{}]);
  // after an install the grants are still missing on macOS: Grant access is offered next
  await expect(page.getByTestId("computer-grant")).toBeVisible();
});

test("installed, a macOS grant missing: Grant access asks macOS and shows the grants after", async ({ page }) => {
  await mock("mock.computer", { status: { ready: false, screen_recording: false } });
  await openComputer(page);
  await expect(page.getByTestId("computer-driver")).toHaveText("Installed · cua-driver 0.4.2");
  await expect(page.getByTestId("computer-accessibility")).toHaveText("Granted");
  await expect(page.getByTestId("computer-screen")).toHaveText("Not granted");
  await expect(page.getByTestId("computer-ready")).toHaveText("Not ready");
  await expect(page.getByTestId("computer-install")).toHaveCount(0);
  await mock("mock.computer", { ms: 600 });
  await page.getByTestId("computer-grant").click();
  await expect(page.getByTestId("computer-granting")).toContainText("CuaDriver");
  await expect(page.getByTestId("computer-screen")).toHaveText("Granted");
  await expect(page.getByTestId("computer-ready")).toHaveText("Ready to use");
  await expect(page.getByTestId("computer-grant")).toHaveCount(0);
  expect((await calls("computer.grant")).map((c) => c.params)).toEqual([{}]);
});

test("a grant still waiting on macOS keeps the note until a read shows the grants", async ({ page }) => {
  await mock("mock.computer", { status: { ready: false, screen_recording: false, grantPending: true } });
  await openComputer(page);
  await page.getByTestId("computer-grant").click();
  // Hermes' command returned, the dialog has not been answered: the note stays
  await expect(page.getByTestId("computer-grant")).toHaveText("Grant access");
  await expect(page.getByTestId("computer-granting")).toContainText("CuaDriver");
  await expect(page.getByTestId("computer-screen")).toHaveText("Not granted");
  // the person allowed it in System Settings and came back to omher
  await mock("mock.computer", { status: { screen_recording: true, ready: true, grantPending: false } });
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByTestId("computer-screen")).toHaveText("Granted");
  await expect(page.getByTestId("computer-granting")).toHaveCount(0);
});

test("another computer-use run holding the slot: the page waits with its buttons off, then reads on its own", async ({ page }) => {
  await mock("mock.computer", { busy: 1 });
  await openComputer(page);
  await expect(page.getByTestId("computer-reading")).toContainText("Hermes is still running another computer-use command");
  await expect(page.getByTestId("computer-check-again")).toBeDisabled();
  await expect(page.getByTestId("computer-ready")).toHaveText("Ready to use", { timeout: 8000 });
  await expect(page.getByTestId("computer-check-again")).toBeEnabled();
});

test("Windows: no grants to ask for, so no Grant access", async ({ page }) => {
  await mock("mock.computer", { status: { platform: "win32", can_grant: false, accessibility: null, screen_recording: null, ready: false } });
  await openComputer(page);
  await expect(page.getByTestId("computer-platform")).toHaveText("Windows");
  await expect(page.getByTestId("computer-accessibility")).toHaveCount(0);
  await expect(page.getByTestId("computer-grant")).toHaveCount(0);
  await expect(page.getByTestId("computer-check")).toHaveCount(2);
});

test("ready: a bot's switch flips, sends only the bot and on/off, and the row shows the new state", async ({ page }) => {
  await mock("mock.computer", { bots: { kami: "on" } });
  await openComputer(page);
  await expect(page.getByTestId("computer-ready")).toHaveText("Ready to use");
  const kami = page.getByTestId("computer-switch-kami");
  const friren = page.getByTestId("computer-switch-friren");
  await expect(kami).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("computer-why-kami")).toHaveText("May use this computer");
  await expect(friren).toHaveAttribute("aria-checked", "false");
  await expect(friren).toBeEnabled();
  await friren.click();
  await expect(friren).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("computer-why-friren")).toHaveText("May use this computer");
  // when it takes effect, said plainly: new threads now, the main chat after a restart
  await expect(page.getByTestId("computer-result-friren")).toHaveText(
    "On for Friren’s new threads. Restart Friren to give its main chat the tool too.",
  );
  expect((await calls("computer.toggle")).map((c) => c.params)).toEqual([{ bot: "friren", on: true }]);
  await kami.click();
  await expect(kami).toHaveAttribute("aria-checked", "false");
  expect((await calls("computer.toggle")).map((c) => c.params)).toEqual([
    { bot: "friren", on: true },
    { bot: "kami", on: false },
  ]);
});

test("a flip Hermes did not make shows the failure and Hermes' words; the switch stays as it was", async ({ page }) => {
  await mock("mock.computer", { next: { verb: "toggle", line: "✗ Unknown toolset 'computer_use'" } });
  await openComputer(page);
  const kami = page.getByTestId("computer-switch-kami");
  await expect(kami).toHaveAttribute("aria-checked", "false");
  await kami.click();
  const result = page.getByTestId("computer-result-kami");
  await expect(result).toContainText("Hermes didn’t turn computer use on for Kami.");
  await expect(result).toContainText("✗ Unknown toolset 'computer_use'");
  await expect(result).toHaveAttribute("role", "alert");
  await expect(kami).toHaveAttribute("aria-checked", "false");
});

test("a flip whose switch cannot be read back says omher can't tell, not that Hermes refused", async ({ page }) => {
  await mock("mock.computer", { next: { verb: "toggle", line: "omher could not read Kami's switch back.", unknown: true } });
  await openComputer(page);
  const kami = page.getByTestId("computer-switch-kami");
  await kami.click();
  const result = page.getByTestId("computer-result-kami");
  await expect(result).toContainText("omher can’t tell whether computer use changed for Kami");
  await expect(result).not.toContainText("didn’t turn");
  // not known: announced as mixed, never as off
  await expect(kami).toHaveAttribute("aria-checked", "mixed");
  await expect(page.getByTestId("computer-why-kami")).toHaveText("omher can’t tell: Kami’s Hermes didn’t say.");
});

test("no Hermes to run: the flip says nothing was asked, never that Hermes declined", async ({ page }) => {
  await mock("mock.computer", { status: { noHermes: true } });
  await openComputer(page);
  const kami = page.getByTestId("computer-switch-kami");
  await kami.click();
  const result = page.getByTestId("computer-result-kami");
  await expect(result).toContainText("Nothing changed for Kami: omher didn’t ask Hermes.");
  await expect(result).toContainText("Hermes is not on this computer.");
  await expect(result).not.toContainText("didn’t turn");
  await expect(kami).toHaveAttribute("aria-checked", "false");
});

test("the code-folder line shows only for a bot whose config sets agent.coding_context: focus", async ({ page }) => {
  await mock("mock.computer", { status: { codeFocus: ["friren"] } });
  await openComputer(page);
  await expect(page.getByTestId("computer-code-focus-friren")).toHaveText(
    "Friren’s config sets agent.coding_context: focus, so its chats in a code folder use Hermes’ coding tools, which leave computer use out.",
  );
  await expect(page.getByTestId("computer-switch-kami")).toBeEnabled();
  await expect(page.getByTestId("computer-code-focus-kami")).toHaveCount(0);
});

test("a switch the profile's agent.disabled_toolsets turns off reads off with why, and turning it on works", async ({ page }) => {
  await mock("mock.computer", { bots: { friren: "disabled" } });
  await openComputer(page);
  const friren = page.getByTestId("computer-switch-friren");
  await expect(friren).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("computer-why-friren")).toContainText("agent.disabled_toolsets");
  await friren.click();
  await expect(friren).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("computer-why-friren")).toHaveText("May use this computer");
});

test("a computer_use step in the chat reads as its action and app", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  const ev = (event: string, extra: Record<string, unknown> = {}) => ({ event, bot: "kami", ...extra });
  await mock("mock.emit", {
    events: [ev("turn.start"), ev("tool.start", { tool_id: "c1", name: "computer_use", detail: "Safari", action: "click" })],
  });
  const act = page.getByTestId("activity").last();
  await expect(act.getByTestId("activity-text")).toHaveText("Clicking in Safari");
  await mock("mock.emit", {
    events: [
      ev("tool.end", { tool_id: "c1", name: "computer_use", ok: true, ms: 10 }),
      ev("tool.start", { tool_id: "c2", name: "computer_use", detail: "screen", action: "capture" }),
      ev("tool.end", { tool_id: "c2", name: "computer_use", ok: true, ms: 10 }),
      ev("turn.end", { outcome: "done" }),
    ],
  });
  await expect(act).toHaveAttribute("data-state", "done");
  await act.getByTestId("activity-toggle").click();
  await expect(act.getByTestId("activity-step").locator(".k")).toHaveText(["Clicked in Safari", "Looked at the screen"]);
});

test("a bot on another computer and an offline bot are off with their reason, and nothing is asked for them", async ({ page }) => {
  await mock("peers.attach", { peer: "mac", label: "Mac mini", host: "demo@mini.local", url: `ws://127.0.0.1:5999/?token=${"0".repeat(32)}` });
  await mock("mock.botStatus", { bot: "friren", status: "offline" });
  await openComputer(page);
  const peer = page.getByTestId("computer-switch-mac:mini");
  // off for a stated reason: still focusable, its reason linked, a press does nothing
  await expect(peer).toHaveAttribute("aria-disabled", "true");
  await expect(peer).toHaveAttribute("aria-describedby", "computer-why-mac:mini");
  await expect(peer).toHaveAttribute("aria-checked", "false");
  await peer.focus();
  await expect(peer).toBeFocused();
  await page.keyboard.press("Space");
  await peer.click({ force: true });
  await expect(page.getByTestId("computer-switch-friren")).toHaveAttribute("aria-checked", "mixed");
  await expect(page.getByTestId("computer-why-mac:mini")).toHaveText(
    "On Mac mini: computer use would act on that computer’s screen, so omher doesn’t set it up from here.",
  );
  await expect(page.getByTestId("computer-switch-friren")).toBeDisabled();
  await expect(page.getByTestId("computer-why-friren")).toHaveText("Can’t tell while Friren is offline.");
  await expect(page.getByTestId("computer-switch-kami")).toBeEnabled();
  for (const op of ["computer.bot", "computer.toggle"]) expect((await calls(op)).filter((c) => c.params.bot === "mac:mini")).toEqual([]);
});

test("toolsets pinned by HERMES_TUI_TOOLSETS: every switch is off with the reason", async ({ page }) => {
  await mock("mock.computer", { status: { pinned: true } });
  await openComputer(page);
  await expect(page.getByTestId("computer-switch-kami")).toBeDisabled();
  await expect(page.getByTestId("computer-why-kami")).toContainText("HERMES_TUI_TOOLSETS");
});

test("a status Hermes could not give says omher can't tell, and Check again reads it again", async ({ page }) => {
  await mock("mock.computer", { status: { read: false, line: "✗ Computer Use: unknown backend 'vm'" } });
  await openComputer(page);
  await expect(page.getByTestId("computer-unread")).toContainText("omher can’t tell");
  await expect(page.getByTestId("computer-unread")).toContainText("unknown backend 'vm'");
  await expect(page.getByTestId("computer-ready")).toHaveText("Not known");
  await mock("mock.computer", { status: { read: true } });
  await page.getByTestId("computer-check-again").click();
  await expect(page.getByTestId("computer-ready")).toHaveText("Ready to use");
  expect((await calls("computer.status")).length).toBe(2);
});

test("the bot page's computer row opens the Computer page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-bot-friren").click();
  await page.getByTestId("bot-computer").click();
  await expect(page.getByTestId("settings-nav-computer")).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("computer")).toBeVisible();
});
