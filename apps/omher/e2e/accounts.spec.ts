// Settings › Accounts: the coding-CLI logins on this computer that sessions start with. The page reads
// accounts.list from the (mock) bridge and asks the desktop app for what only it knows: which CLIs are here,
// each CLI's own login status, and the CLI's own sign-in. A plain browser has no app, so these tests inject a
// stand-in (`window.__omherAccountHost`) that records calls and lets the test finish or cancel a sign-in.
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS_DIR || join(dirname(fileURLToPath(import.meta.url)), "__shots__");

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "a1") res(msg);
    };
    ws.send(JSON.stringify({ id: "a1", op, ...params }));
  });
  ws.close();
  return reply.result;
}
const callsOf = async (op: string) =>
  ((await mock("mock.calls")).calls as { op: string; params: Record<string, unknown> }[]).filter((c) => c.op === op);

/** The desktop app's part, as the Rust commands answer it: claude/codex/pi on this computer, Claude signed in
 *  (`claude auth status --json` -> owner@example.com, max_20x), every sign-in recorded and held open. */
function installHost() {
  type Ev = { kind: "line"; text: string } | { kind: "exit"; code: number | null };
  const w = window as any;
  w.__acct = { signIns: [] as { cli: string; account: string }[], cancels: [] as number[], status: {} as Record<string, unknown>, live: {} as Record<number, (e: Ev) => void> };
  w.__acct.status["claude:default"] = { logged_in: true, email: "owner@example.com", plan: "max_20x", method: "claude.ai" };
  w.__acct.status["codex:default"] = { logged_in: true, email: null, plan: null, method: "chatgpt" };
  w.__acct.status["codex:work"] = { logged_in: true, email: null, plan: null, method: "chatgpt" };
  w.__omherAccountHost = {
    canSignIn: true,
    clis: async () => ({ claude: true, codex: true, pi: true, omp: false, grok: false, gemini: false }),
    status: async (cli: string, account: string) =>
      w.__acct.status[`${cli}:${account}`] ?? (cli === "claude" ? { logged_in: false, email: null, plan: null, method: "none" } : null),
    signIn: async (cli: string, account: string, on: (e: Ev) => void) => {
      const n = w.__acct.signIns.push({ cli, account });
      w.__acct.live[n] = on;
      setTimeout(() => on({ kind: "line", text: "Opening browser to sign in…" }), 0);
      return n;
    },
    cancel: async (n: number) => {
      w.__acct.cancels.push(n);
      w.__acct.live[n]?.({ kind: "exit", code: null });
    },
  };
  /** The CLI's sign-in finished in the browser (`email`) or was closed without one (null). */
  w.__finishSignIn = (n: number, email: string | null) => {
    const s = w.__acct.signIns[n - 1];
    if (email) w.__acct.status[`${s.cli}:${s.account}`] = { logged_in: true, email, plan: "pro", method: "claude.ai" };
    w.__acct.live[n]?.({ kind: "exit", code: email ? 0 : 1 });
  };
}

async function openAccounts(page: Page, theme: "dark" | "light" = "dark") {
  await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
  await page.addInitScript(installHost);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("me").click();
  await expect(page.getByTestId("accounts-page")).toBeVisible();
}

const row = (page: Page, cli: string, id: string) => page.getByTestId(`accounts-${cli}`).locator(`[data-testid=account-row][data-id="${id}"]`);

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("the user row opens Accounts: one plain header line, CLIs on this computer only", async ({ page }) => {
  await openAccounts(page);
  await expect(page.getByTestId("settings-nav-accounts")).toHaveAttribute("aria-current", "page");
  await expect(page.locator(".st-nav button").first()).toHaveText("Accounts");
  await expect(page.getByTestId("me")).toHaveClass(/\bon\b/);
  await expect(page.getByTestId("accounts-lead")).toHaveText("Subscriptions your coding sessions use. Bots use their own Hermes settings.");
  await expect(page.locator(".acc-g")).toHaveCount(3);
  await expect(page.locator(".acc-g .acc-gh b")).toHaveText(["Claude Code", "Codex", "pi"]);
  await expect(page.getByTestId("accounts-missing")).toHaveText("Not on this computer: oh-my-pi, Grok, Gemini CLI");
  const text = await page.getByTestId("accounts-page").innerText();
  for (const gone of ["Stack your logins", "fill-first", "config.yaml", "secret-key", "CPA ", "management"]) expect(text).not.toContain(gone);
});

test("This computer: Claude's own login from its status, in full, with plan and In use; CPA is one quiet line", async ({ page }) => {
  await openAccounts(page);
  const me = row(page, "claude", "default");
  await expect(me.getByTestId("account-name")).toContainText("owner@example.com");
  await expect(me.getByTestId("account-name")).toContainText("This computer");
  await expect(me.getByTestId("account-plan")).toHaveText("Max 20x");
  await expect(me.getByTestId("account-pill")).toHaveText("In use");
  await expect(me).toHaveAttribute("data-in-use", "true");
  await expect(page.getByTestId("accounts-claude").getByTestId("accounts-also")).toHaveText(
    "Also found: CLIProxyAPI with 5 accounts (managed there).",
  );
  await expect(page.getByTestId("accounts-also")).toHaveCount(1);
  // Codex: usage ring with a plain tooltip; only one In use per CLI
  const codex = row(page, "codex", "default");
  await expect(codex.getByTestId("account-usage")).toHaveAttribute("title", /^5-hour limit: 73% used · resets [^\n]+\nWeekly limit: 60% used · resets /);
  await expect(codex.getByTestId("account-name")).toContainText("ChatGPT login · 5-hour limit: 73% used · resets");
  await expect(page.getByTestId("accounts-codex").getByTestId("account-pill")).toHaveText(["In use"]);
  // one switch per CLI with more than one login, with its sentence
  await expect(page.getByTestId("autoswitch-codex")).toHaveAttribute("role", "switch");
  await expect(page.getByTestId("autoswitch-row-codex")).toContainText("When this account hits its limit, new turns use the next one.");
  await expect(page.getByTestId("autoswitch-claude")).toHaveCount(0);
  // + Add account only where omher can run the CLI's own sign-in
  await expect(page.getByTestId("add-account-claude")).toBeVisible();
  await expect(page.getByTestId("add-account-codex")).toBeVisible();
  await expect(page.getByTestId("add-account-pi")).toBeDisabled();
  await expect(page.getByTestId("add-account-pi")).toContainText("Soon");
  const html = await page.content();
  for (const k of ["access_token", "refresh_token", "id_token", "api_key", "OPENAI_API_KEY"]) expect(html).not.toContain(k);
});

test("+ Add account runs the CLI's own sign-in; when it ends signed in, the row shows the email and plan", async ({ page }) => {
  await openAccounts(page);
  const g = page.getByTestId("accounts-claude");
  await g.getByTestId("add-account-claude").click();
  await g.getByTestId("add-label-claude").fill("Work");
  await g.getByTestId("add-confirm-claude").click();
  await expect(g.getByTestId("signin-panel")).toContainText("Finish signing in to Claude Code in your browser.");
  await expect(g.getByTestId("signin-lines")).toHaveText("Opening browser to sign in…");
  expect((await callsOf("accounts.add")).map((c) => c.params)).toEqual([{ cli: "claude", label: "Work" }]);
  expect(await page.evaluate(() => (window as any).__acct.signIns)).toEqual([{ cli: "claude", account: "work" }]);
  // no field anywhere asks for a code, token or key
  await expect(g.locator("input")).toHaveCount(0);

  await mock("mock.accounts", { cli: "claude", signed_in: { id: "work", email: "work@example.com" } });
  await page.evaluate(() => (window as any).__finishSignIn(1, "work@example.com"));
  await expect(g.getByTestId("signin-panel")).toHaveCount(0);
  const work = row(page, "claude", "work");
  await expect(work.getByTestId("account-name")).toContainText("work@example.com");
  await expect(work.getByTestId("account-name")).toContainText("Work · Added in omher");
  await expect(work.getByTestId("account-plan")).toHaveText("Pro");
  await expect(work.getByTestId("account-pill")).toHaveCount(0); // signed in, not in use
  expect(await callsOf("accounts.discard")).toEqual([]);
  await expect(page.getByTestId("autoswitch-claude")).toBeVisible(); // two logins now
});

test("cancelling the sign-in stops it and removes the empty folder", async ({ page }) => {
  await openAccounts(page);
  const g = page.getByTestId("accounts-claude");
  await g.getByTestId("add-account-claude").click();
  await g.getByTestId("add-confirm-claude").click();
  await expect(g.getByTestId("signin-panel")).toBeVisible();
  await expect(g.getByTestId("account-row")).toHaveCount(2);
  await g.getByTestId("signin-cancel").click();
  await expect(g.getByTestId("signin-panel")).toHaveCount(0);
  await expect(g.getByTestId("accounts-msg")).toHaveText("Sign-in cancelled. Nothing was added.");
  await expect(g.getByTestId("account-row")).toHaveCount(1);
  expect(await page.evaluate(() => (window as any).__acct.cancels)).toEqual([1]);
  expect((await callsOf("accounts.discard")).map((c) => c.params)).toEqual([{ cli: "claude", account: "account-2" }]);
  // a sign-in the CLI ends without a login (browser closed) cleans up the same way
  await g.getByTestId("add-account-claude").click();
  await g.getByTestId("add-confirm-claude").click();
  await expect(g.getByTestId("signin-panel")).toBeVisible();
  await page.evaluate(() => (window as any).__finishSignIn(2, null));
  await expect(g.getByTestId("signin-panel")).toHaveCount(0);
  await expect(g.getByTestId("account-row")).toHaveCount(1);
  expect((await callsOf("accounts.discard")).length).toBe(2);
});

test("Use for new sessions moves In use; a name can be set on any row", async ({ page }) => {
  await openAccounts(page);
  await row(page, "codex", "work").getByTestId("account-menu").click();
  await page.getByRole("button", { name: "Use for new sessions" }).click();
  await expect(row(page, "codex", "work").getByTestId("account-pill")).toHaveText("In use");
  await expect(row(page, "codex", "default").getByTestId("account-pill")).toHaveCount(0);
  expect((await callsOf("accounts.set_active")).map((c) => c.params)).toEqual([{ cli: "codex", account: "work" }]);

  await row(page, "claude", "default").getByTestId("account-menu").click();
  await page.getByRole("button", { name: "Add a name…" }).click();
  await page.getByTestId("rename-input").fill("Personal");
  await page.getByTestId("rename-input").press("Enter");
  await expect(row(page, "claude", "default").getByTestId("account-name")).toContainText("Personal · This computer");
  expect((await callsOf("accounts.label")).map((c) => c.params)).toEqual([{ cli: "claude", account: "default", label: "Personal" }]);
});

test("remove asks first; cancel keeps the row, confirm deletes only that account; This computer has no Remove", async ({ page }) => {
  await openAccounts(page);
  const g = page.getByTestId("accounts-codex");
  await row(page, "codex", "work").getByTestId("account-menu").click();
  await page.getByRole("button", { name: "Remove…" }).click();
  await expect(g.getByTestId("remove-confirm")).toContainText("Remove Work from omher?");
  await g.getByTestId("remove-confirm").getByRole("button", { name: "Cancel" }).click();
  await expect(g.getByTestId("account-row")).toHaveCount(2);
  expect(await callsOf("accounts.remove")).toEqual([]);
  await row(page, "codex", "work").getByTestId("account-menu").click();
  await page.getByRole("button", { name: "Remove…" }).click();
  await g.getByTestId("remove-confirm").getByRole("button", { name: "Remove" }).click();
  await expect(g.getByTestId("account-row")).toHaveCount(1);
  expect((await callsOf("accounts.remove")).map((c) => c.params)).toEqual([{ cli: "codex", account: "work" }]);
  await row(page, "codex", "default").getByTestId("account-menu").click();
  await expect(page.getByRole("button", { name: "Remove…" })).toHaveCount(0);
});

test("auto-switch: the in-use account hits its limit → the next one, a toast and one quiet chat line", async ({ page }) => {
  await openAccounts(page);
  await mock("mock.accounts", { limit: "default" });
  await expect(row(page, "codex", "work").getByTestId("account-pill")).toHaveText("In use");
  await expect(row(page, "codex", "default").getByTestId("account-pill")).toHaveText(/^Limited until/);
  const toast = page.getByTestId("accounts-codex").getByTestId("accounts-toast");
  await expect(toast).toHaveText(/^Switched Codex to Work for new sessions \(limit on This computer, resets .+\)$/);
  expect((await callsOf("accounts.set_active")).map((c) => c.params)).toEqual([{ cli: "codex", account: "work" }]);
  await page.getByTestId("bot-kami").click();
  const line = page.getByTestId("system-line");
  await expect(line).toHaveCount(1);
  await expect(line).toHaveText(/^Switched Codex to Work/);
  expect(await callsOf("chat.send")).toEqual([]);
});

test("auto-switch off: a limit does not move the account in use", async ({ page }) => {
  await openAccounts(page);
  await page.getByTestId("autoswitch-codex").click();
  await expect(page.getByTestId("autoswitch-codex")).toHaveAttribute("aria-checked", "false");
  await mock("mock.accounts", { limit: "default" });
  await expect(row(page, "codex", "default").getByTestId("account-pill")).toHaveText(/^Limited until/);
  await page.waitForTimeout(300);
  await expect(row(page, "codex", "work").getByTestId("account-pill")).toHaveCount(0);
  expect(await callsOf("accounts.set_active")).toEqual([]);
});

test("screenshots: Accounts in dark and light (T11b)", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  for (const theme of ["dark", "light"] as const) {
    await mock("mock.reset");
    await page.setViewportSize({ width: 1180, height: 820 });
    await openAccounts(page, theme);
    await expect(row(page, "claude", "default").getByTestId("account-plan")).toHaveText("Max 20x");
    await page.mouse.move(5, 5);
    await page.waitForTimeout(350);
    await page.screenshot({ path: join(SHOTS, `T11b-accounts-${theme}.png`), animations: "disabled" });
    await row(page, "codex", "work").getByTestId("account-menu").click();
    await page.screenshot({ path: join(SHOTS, `T11b-menu-${theme}.png`), animations: "disabled" });
    await page.keyboard.press("Escape");
    await page.getByTestId("add-account-claude").click();
    await page.getByTestId("add-label-claude").fill("Work");
    await page.getByTestId("add-confirm-claude").click();
    await expect(page.getByTestId("signin-panel")).toBeVisible();
    await page.mouse.move(5, 5);
    await page.screenshot({ path: join(SHOTS, `T11b-signin-${theme}.png`), animations: "disabled" });
  }
});
