// SESSIONS: the sidebar half under BOTS, the + menu of agent CLIs, a mock terminal session (the browser
// build has no Tauri shell, so the MockHost echoes), switching between a bot chat and a session, closing.
// Grok is the agent that opens as a terminal (the others open as chats: e2e/sessions-chat.spec.ts), so
// these tests install it in the mock host.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

test.use({ colorScheme: "dark" });

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

async function open(page: Page, folder = "/Users/you/code/oh-my-hermes", installed = ["claude", "codex", "omh", "grok"]) {
  await page.addInitScript(
    ([f, agents]) => {
      if (!sessionStorage.getItem("__kept")) localStorage.removeItem("omher.sessions.recent");
      (window as unknown as { __omherPickFolder: string }).__omherPickFolder = f as string;
      (window as unknown as { __omherMockAgents: string[] }).__omherMockAgents = agents as string[];
    },
    [folder, installed] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** Row backgrounds fade (0.12s) and the pointer must not hover a row before a screenshot. */
async function settle(page: Page) {
  await page.mouse.move(900, 780);
  await page.waitForTimeout(350);
}

const calls = (page: Page) =>
  page.evaluate(() => ((window as unknown as { __omherSessionCalls?: { op: string; agent?: string; cwd?: string; data?: string; id?: number }[] }).__omherSessionCalls ?? []));

async function startSession(page: Page, agent: string) {
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-choose").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("bots and sessions each take the room their rows need and share what is left", async ({ page }) => {
  await open(page);
  const bots = await page.getByTestId("side-bots").boundingBox();
  const sess = await page.getByTestId("side-sessions").boundingBox();
  expect(bots && sess).toBeTruthy();
  expect(sess!.y).toBeGreaterThan(bots!.y + bots!.height - 1); // SESSIONS sits under BOTS
  // three bots and no session: neither list needs to scroll, and the spare room is shared equally between them
  const need = await page.evaluate(() => {
    const h = (id: string, list: string) => {
      const sec = document.querySelector(`[data-testid=${id}]`)!;
      const l = sec.querySelector(list) as HTMLElement | null;
      return { box: sec.getBoundingClientRect().height, spare: l ? l.clientHeight - l.scrollHeight : 0, scrolls: l ? l.scrollHeight > l.clientHeight + 1 : false };
    };
    return { bots: h("side-bots", ".bot-list"), sess: h("side-sessions", ".ss-none") };
  });
  expect(need.bots.scrolls).toBe(false);
  expect(bots!.height).toBeGreaterThan(sess!.height); // three rows need more than the empty SESSIONS
  await expect(page.getByTestId("side-sessions")).toContainText("Sessions");
  await expect(page.getByTestId("session-none")).toBeVisible();
  // the top + is still "Add a bot"; the sessions + is its own button
  await expect(page.getByRole("button", { name: "Add a bot" })).toBeVisible();
  await expect(page.getByTestId("session-new")).toHaveAttribute("aria-label", "New session");
  // each list scrolls on its own
  expect(await page.locator("[data-testid=side-bots] .bot-list").evaluate((el) => getComputedStyle(el).overflowY)).toBe("auto");
});

test("twelve bots beside an empty SESSIONS use the room: the list does not stop at five with a blank half under it", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  // the mock's three bots plus nine more
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    const ops = new Map<string, string>();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      ops.set(msg.id, msg.op);
      server.send(raw);
    });
    server.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (ops.get(msg.id) === "bots.list" && msg.ok) {
        const base = msg.result.bots[msg.result.bots.length - 1];
        for (let i = 0; i < 9; i++) msg.result.bots.push({ ...base, name: `extra${i}`, display_name: `Extra bot number ${i} with a long name`, is_default: false, running: false });
        ws.send(JSON.stringify(msg));
        return;
      }
      ws.send(raw);
    });
  });
  await open(page);
  await expect(page.locator("[data-testid=side-bots] .bot")).toHaveCount(12);
  const geo = await page.evaluate(() => {
    const list = document.querySelector("[data-testid=side-bots] .bot-list")!.getBoundingClientRect();
    const rows = [...document.querySelectorAll("[data-testid=side-bots] .bot")].map((e) => e.getBoundingClientRect());
    const none = document.querySelector("[data-testid=session-none]")!.getBoundingClientRect();
    const sess = document.querySelector("[data-testid=side-sessions]")!.getBoundingClientRect();
    const foot = document.querySelector(".side-foot")!.getBoundingClientRect();
    return { whole: rows.filter((r) => r.top >= list.top - 0.5 && r.bottom <= list.bottom + 0.5).length, noneBottom: none.bottom, sessBottom: sess.bottom, footTop: foot.top, sessH: sess.height };
  });
  expect(geo.whole).toBeGreaterThanOrEqual(8); // it was 5
  // SESSIONS keeps its header, its button and its line of agents, whole, and no more than that
  expect(geo.noneBottom).toBeLessThanOrEqual(geo.sessBottom + 0.5);
  expect(geo.sessBottom).toBeLessThanOrEqual(geo.footTop + 0.5);
  expect(geo.sessH).toBeLessThan(140);
  // a name too long for the row is cut with an ellipsis, on one line
  const name = await page.locator('[data-testid="bot-extra0"] .bot-n').evaluate((e) => [getComputedStyle(e).textOverflow, e.scrollWidth > e.clientWidth, Math.round(e.getBoundingClientRect().height)]);
  expect(name[0]).toBe("ellipsis");
  expect(name[1]).toBe(true);
  expect(name[2]).toBeLessThanOrEqual(20);
});

test("+ lists the agent CLIs with their marks; missing ones are disabled", async ({ page }) => {
  await open(page, undefined, ["claude", "codex", "omh"]);
  await page.getByTestId("session-new").click();
  const menu = page.getByTestId("session-menu");
  await expect(menu).toBeVisible();
  const rows = menu.locator("[data-testid^=session-agent-]");
  await expect(rows).toHaveCount(6);
  expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")))).toEqual(
    ["claude", "codex", "omh", "pi", "omp", "grok"].map((a) => `session-agent-${a}`),
  );
  await expect(menu.getByTestId("session-agent-claude")).toContainText("Claude Code");
  await expect(menu.getByTestId("session-agent-claude").locator('svg[data-mark="claude"]')).toHaveCount(1);
  await expect(menu.getByTestId("session-agent-codex").locator('svg[data-mark="openai"]')).toHaveCount(1);
  await expect(menu.getByTestId("session-agent-omh").locator('[data-mark="omh"]')).toHaveCount(1);
  for (const a of ["claude", "codex", "omh"]) await expect(menu.getByTestId(`session-agent-${a}`)).toBeEnabled();
  for (const a of ["pi", "omp", "grok"]) {
    await expect(menu.getByTestId(`session-agent-${a}`)).toBeDisabled();
    await expect(menu.getByTestId(`session-agent-${a}`)).toContainText("Not installed");
  }
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
});

test("the menu says which account a new session uses; This computer says nothing", async ({ page }) => {
  // Claude: a second account signed in as work@example.com, chosen for new sessions. Codex: its "Work" account.
  await mock("accounts.add", { cli: "claude", label: "" });
  await mock("mock.accounts", { cli: "claude", signed_in: { id: "account-2", email: "work@example.com" } });
  await mock("accounts.set_active", { cli: "claude", account: "account-2" });
  await mock("accounts.set_active", { cli: "codex", account: "work" });
  await open(page);
  await page.getByTestId("session-new").click();
  const menu = page.getByTestId("session-menu");
  // the masked email when the account has no name, else its name
  await expect(menu.getByTestId("session-account-claude")).toHaveText("as work@…");
  await expect(menu.getByTestId("session-agent-claude")).toContainText(/Claude Code\s*as work@…/);
  await expect(menu.getByTestId("session-account-claude")).not.toContainText("example.com");
  await expect(menu.getByTestId("session-account-codex")).toHaveText("as Work");
  // the menu stays 8px inside both sidebar edges, so the account sits on its own muted line under the agent;
  // both are whole at the default sidebar width, and the row's tooltip names both
  const side = (await page.getByTestId("sidebar").boundingBox())!;
  const pop = (await menu.locator("..").boundingBox())!;
  expect(Math.round(pop.x - side.x)).toBe(8);
  expect(Math.round(side.x + side.width - (pop.x + pop.width))).toBe(8);
  for (const a of ["claude", "codex"]) {
    const fits = await menu.getByTestId(`session-agent-${a}`).evaluate((row) => {
      const as = row.querySelector(".ss-as")!;
      const r = as.getBoundingClientRect();
      const box = row.querySelector(".ss-n")!.getBoundingClientRect();
      const label = row.querySelector(".ss-l")!;
      const l = label.getBoundingClientRect();
      const cmd = row.querySelector(".ss-cmd")!.getBoundingClientRect();
      return {
        whole: as.scrollWidth <= as.clientWidth && r.right <= box.right + 0.5 && r.width > 0,
        label: label.scrollWidth <= label.clientWidth,
        under: r.top >= l.bottom - 1 && Math.abs(r.left - l.left) < 1,
        gap: Math.round(cmd.left - Math.max(r.right, l.right)),
        muted: getComputedStyle(as).color === getComputedStyle(row.querySelector(".ss-cmd")!).color,
        inRow: r.bottom <= row.getBoundingClientRect().bottom,
      };
    });
    expect(fits.whole, `${a} account cut off`).toBe(true);
    expect(fits.label, `${a} label cut off`).toBe(true);
    expect(fits.under, `${a} account on its own line`).toBe(true);
    expect(fits.gap, `${a} gap to the command`).toBeGreaterThanOrEqual(8);
    expect(fits.muted, `${a} account in --muted`).toBe(true);
    expect(fits.inRow, `${a} account inside its row`).toBe(true);
  }
  await expect(menu.getByTestId("session-agent-claude").locator(".ss-n")).toHaveAttribute("title", "Claude Code as work@…");
  // omh has no login; pi has one but its sessions do not take an account yet
  for (const a of ["omh", "pi", "omp", "grok"]) await expect(menu.getByTestId(`session-account-${a}`)).toHaveCount(0);
  if (SHOTS) {
    mkdirSync(SHOTS, { recursive: true });
    await page.mouse.move(900, 780);
    await page.waitForTimeout(350);
    await menu.screenshot({ path: join(SHOTS, "session-menu-account.png"), animations: "disabled" });
  }
  // back to This computer: the suffix goes (read-only: the menu itself never switches)
  await mock("accounts.set_active", { cli: "claude", account: "default" });
  await expect(menu.getByTestId("session-account-claude")).toHaveCount(0);
  await expect(menu.getByTestId("session-account-codex")).toHaveText("as Work");
  await page.keyboard.press("Escape");
});

/** WCAG contrast of each selector's text colour on `bg` (an rgb() string). */
async function contrast(page: Page, sels: string[], bg: string) {
  return page.evaluate(
    ([s, b]) => {
      const rgb = (c: string) => c.match(/[\d.]+/g)!.slice(0, 3).map(Number);
      const lum = (c: number[]) => {
        const [r, g, bl] = c.map((v) => {
          v /= 255;
          return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
      };
      const back = lum(rgb(b as string));
      return (s as string[]).map((sel) => {
        const el = document.querySelector(sel);
        if (!el) return [sel, 0] as const;
        const a = lum(rgb(getComputedStyle(el).color));
        return [sel, (Math.max(a, back) + 0.05) / (Math.min(a, back) + 0.05)] as const;
      });
    },
    [sels, bg] as const,
  );
}

for (const theme of ["dark", "light"] as const) {
  test(`empty SESSIONS: one New session button over the installed agents, the menu inset 8px (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
    await open(page, undefined, ["claude", "codex", "omh", "pi", "omp"]);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const none = page.getByTestId("session-none");
    const start = none.getByTestId("session-start");
    await expect(start).toHaveText("New session");
    await expect(start.locator("svg")).toHaveCount(1); // the + icon
    // the official marks of up to 4 installed agents; the first two carry their names, every name in the tooltip
    const ag = none.getByTestId("session-start-agents");
    expect(await ag.locator("[data-mark]").evaluateAll((els) => els.map((e) => e.getAttribute("data-mark")))).toEqual(["claude", "openai", "omh", "pi"]);
    await expect(ag).toHaveText(/^Claude Code\s*·\s*Codex/);
    await expect(ag).toHaveAttribute("title", "Claude Code · Codex · oh-my-hermes · pi");
    // no long hint: at most 2 lines tall (button + agent line), so BOTS and SESSIONS stay balanced
    expect((await none.boundingBox())!.height).toBeLessThanOrEqual(60);
    await expect(none).not.toContainText("Start Claude Code");

    // the header: the BOTS label colour, a --muted + with a 24px target and a gray hover fill
    const head = page.locator("[data-testid=side-sessions] .side-sh");
    const bots = page.locator("[data-testid=side-bots] .side-sh");
    const plus = page.getByTestId("session-new");
    expect(await head.evaluate((e) => getComputedStyle(e).color)).toBe(await bots.evaluate((e) => getComputedStyle(e).color));
    const muted = await page.evaluate(() => {
      const p = document.createElement("span");
      p.style.color = "var(--muted)";
      document.body.append(p);
      const c = getComputedStyle(p).color;
      p.remove();
      return c;
    });
    expect(await plus.evaluate((e) => getComputedStyle(e).color)).toBe(muted);
    const pb = (await plus.boundingBox())!;
    expect(pb.width).toBe(24);
    expect(pb.height).toBe(24);
    await expect(plus).toHaveAttribute("title", "New session");
    await plus.hover();
    await expect.poll(() => plus.evaluate((e) => getComputedStyle(e).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)");
    await page.mouse.move(900, 780);

    const side = (await page.getByTestId("sidebar").boundingBox())!;
    const sideBg = await page.getByTestId("sidebar").evaluate((e) => getComputedStyle(e).backgroundColor);
    for (const [sel, r] of await contrast(page, ["[data-testid=side-sessions] .side-sh", "[data-testid=session-new]", ".ss-start-n"], sideBg))
      expect(r, sel).toBeGreaterThanOrEqual(4.5);

    // the button opens the same menu, 8px in from both sidebar edges; its secondary labels meet 4.5:1
    for (const opener of [start, plus]) {
      await opener.click();
      const menu = page.getByTestId("session-menu");
      await expect(menu).toBeVisible();
      await expect(menu.locator("[data-testid^=session-agent-]")).toHaveCount(6);
      const pop = (await menu.locator("..").boundingBox())!;
      expect(Math.round(pop.x - side.x)).toBe(8);
      expect(Math.round(side.x + side.width - (pop.x + pop.width))).toBe(8);
      const popBg = await menu.locator("..").evaluate((e) => getComputedStyle(e).backgroundColor);
      const sec = await contrast(page, [".ss-pop .ss-h", ".ss-pop .ss-cmd", ".ss-pop .ss-missing", ".ss-pop .ss-item:disabled .ss-n"], popBg);
      for (const [sel, r] of sec) expect(r, sel).toBeGreaterThanOrEqual(4.5);
      await page.keyboard.press("Escape");
      await expect(menu).toHaveCount(0);
    }
    await page.mouse.move(900, 780);
    if (SHOTS) {
      mkdirSync(SHOTS, { recursive: true });
      await page.waitForTimeout(350);
      await page.screenshot({ path: join(SHOTS, `sessions-empty-${theme}.png`), clip: { x: 0, y: 380, width: 560, height: 220 } });
      await start.click();
      await page.screenshot({ path: join(SHOTS, `sessions-empty-menu-${theme}.png`), clip: { x: 0, y: 380, width: 560, height: 420 }, animations: "disabled" });
    }
  });
}

test("the empty section shows no agent line when no agent is installed", async ({ page }) => {
  await open(page, undefined, []);
  await expect(page.getByTestId("session-start")).toBeVisible();
  await expect(page.getByTestId("session-start-agents")).toHaveCount(0);
});

test("start a mock terminal session, type, see the echo, then switch to a bot chat and back", async ({ page }) => {
  await open(page);
  await startSession(page, "grok");
  const header = page.getByTestId("header");
  await expect(page.getByTestId("session-title")).toHaveText("Grok");
  await expect(page.getByTestId("session-cwd")).toHaveText("~/code/oh-my-hermes");
  await expect(header.locator("button")).toHaveCount(0); // no extra header icons
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  await expect(row).toContainText("oh-my-hermes");
  await expect(row.locator(".bot-p")).toHaveText("Grok");
  await expect(page.getByTestId("session-status")).toHaveText("Running");
  await expect(row.getByTestId("live-dot")).toBeVisible();
  await expect(row).toHaveClass(/active/);
  await expect(page.getByTestId("bot-kami")).not.toHaveAttribute("aria-current", "true");

  // only the agent id and folder went to the host: no command line
  const start = (await calls(page)).find((c) => c.op === "start")!;
  expect(start).toMatchObject({ agent: "grok", cwd: "/Users/you/code/oh-my-hermes" });
  expect(Object.keys(start).sort()).toEqual(["agent", "cols", "cwd", "id", "op", "rows"]);

  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("hello omher");
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText("you said: hello omher");
  // Ctrl+C passes through to the program
  await page.keyboard.press("Control+c");
  await expect.poll(async () => (await calls(page)).some((c) => c.op === "write" && c.data === "\x03")).toBe(true);
  await expect(page.locator(".xterm-rows")).toContainText("^C");

  // to the bot chat: the composer is back, the session keeps running
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("terminal")).toHaveCount(0);
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await expect(row).not.toHaveClass(/active/);
  await expect(row.getByTestId("live-dot")).toBeVisible();

  // and back: the same terminal, with what was typed before
  await row.locator(".ss-open").click();
  await expect(page.locator(".xterm-rows")).toContainText("you said: hello omher");
  expect((await calls(page)).filter((c) => c.op === "start")).toHaveLength(1);
});

test("a second session, recent folders, and exit ends a session", async ({ page }) => {
  await open(page);
  await startSession(page, "grok");
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/work/api"));
  await startSession(page, "grok");
  const rows = page.locator("[data-testid=session-list] .ss-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("api");
  await expect(rows.first()).toContainText("Grok");
  await expect(page.getByTestId("session-title")).toHaveText("Grok");

  // the + menu opens inside the sidebar; after the agent it offers the recent folders
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-recent")).toHaveCount(0);
  await page.getByTestId("session-agent-grok").click();
  await expect(page.getByTestId("session-recent")).toHaveCount(2);
  const pop = (await page.getByTestId("session-menu").locator("..").boundingBox())!;
  const side = (await page.getByTestId("sidebar").boundingBox())!;
  expect(pop.x).toBeGreaterThanOrEqual(side.x);
  expect(pop.x + pop.width).toBeLessThanOrEqual(side.x + side.width);
  await expect(page.getByTestId("session-recent").first()).toContainText("api");
  await expect(page.getByTestId("session-recent").first().locator(".ss-path")).toHaveText("~/work");
  await page.keyboard.press("Escape");

  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("exit");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ended");
  await expect(rows.first()).toContainText("Grok · Ended");
  await expect(rows.first().getByTestId("live-dot")).toHaveCount(0);
  await expect(page.locator(".xterm-rows")).toContainText("Grok ended");
});

test("loading the page stops sessions an earlier load left running, before anything starts", async ({ page }) => {
  await open(page);
  await expect.poll(async () => (await calls(page)).map((c) => c.op)).toEqual(["reset"]);
  await startSession(page, "grok");
  const ops = (await calls(page)).map((c) => c.op);
  expect(ops.filter((o) => o === "reset")).toHaveLength(1);
  expect(ops.indexOf("reset")).toBeLessThan(ops.indexOf("start"));
  // a reload is a new page load: it resets again
  await page.reload();
  await expect.poll(async () => (await calls(page)).map((c) => c.op)).toEqual(["reset"]);
});

test("xterm loads only when a session opens", async ({ page }) => {
  const scripts: string[] = [];
  page.on("request", (r) => {
    if (r.resourceType() === "script") scripts.push(r.url());
  });
  await open(page);
  await page.waitForLoadState("networkidle");
  expect(scripts.filter((u) => u.includes("xterm"))).toEqual([]);
  await startSession(page, "grok");
  expect(scripts.some((u) => u.includes("xterm"))).toBe(true);
});

test("the stop question is shown whole, and Esc cancels it", async ({ page }) => {
  await open(page);
  await startSession(page, "grok");
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  const id = (await row.getAttribute("data-testid"))!.replace("session-", "");
  await row.hover();
  await row.getByTestId("session-close").click();
  const confirm = page.getByTestId(`session-confirm-${id}`);
  const q = confirm.locator(".ss-q");
  await expect(q).toHaveText("Stop Grok?");
  expect(await q.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await expect(confirm.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(confirm).toHaveCount(0);
  await expect(row.locator(".ss-open")).toBeFocused();
  expect((await calls(page)).some((c) => c.op === "close")).toBe(false);
  await expect(page.getByTestId("session-status")).toHaveText("Running");
});

test("closing a running session asks first and stops the program", async ({ page }) => {
  await open(page);
  await startSession(page, "grok");
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  const id = (await row.getAttribute("data-testid"))!.replace("session-", "");
  await row.hover();
  await row.getByTestId("session-close").click();
  const confirm = page.getByTestId(`session-confirm-${id}`);
  await expect(confirm).toContainText("Stop Grok?");
  await confirm.getByRole("button", { name: "Cancel" }).click();
  await expect(row).toBeVisible();
  expect((await calls(page)).some((c) => c.op === "close")).toBe(false);

  // right-click is the other way to close
  await row.click({ button: "right" });
  await page.getByTestId("session-stop").click();
  await expect(page.locator("[data-testid=session-list] .ss-row")).toHaveCount(0);
  await expect.poll(async () => (await calls(page)).filter((c) => c.op === "close").length).toBe(1);
  // back to the bot chat, empty section hint again
  await expect(page.getByTestId("terminal")).toHaveCount(0);
  await expect(page.getByTestId("composer").or(page.locator("textarea")).first()).toBeVisible();
  await expect(page.getByTestId("session-none")).toBeVisible();
});

test("an ended session closes without asking", async ({ page }) => {
  await open(page);
  await startSession(page, "grok");
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("exit");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ended");
  const row = page.locator("[data-testid=session-list] .ss-row").first();
  await row.hover();
  await row.getByTestId("session-close").click();
  await expect(page.locator("[data-testid=session-list] .ss-row")).toHaveCount(0);
});

test("the terminal follows the light theme", async ({ page }) => {
  await open(page);
  await startSession(page, "grok");
  // what shows: the theme background on the scrollable element, through a transparent viewport
  expect(await page.locator(".xterm-viewport").evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
  const bg = () => page.locator(".xterm-scrollable-element").evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(await bg()).toBe("rgb(11, 9, 13)");
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ "/src/state/store.ts");
    m.getStore().actions.setTheme("light");
  });
  await expect.poll(bg).toBe("rgb(255, 255, 255)");
});

test("screenshots: sidebar with sessions and an open session, dark and light", async ({ page }) => {
  test.skip(!SHOTS, "set OMHER_SHOTS to a folder to save screenshots");
  mkdirSync(SHOTS, { recursive: true });
  await open(page, "/Users/you/code/oh-my-hermes");
  await startSession(page, "grok");
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/work/api-server"));
  await startSession(page, "grok");
  await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/omher"));
  await startSession(page, "grok");
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("explain the sessions feature");
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText("you said");
  await settle(page);
  await page.screenshot({ path: join(SHOTS, "session-dark.png") });
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await page.waitForTimeout(300); // the popover fades in
  await page.screenshot({ path: join(SHOTS, "menu-dark.png") });
  await page.keyboard.press("Escape");
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  await settle(page);
  await page.screenshot({ path: join(SHOTS, "chat-dark.png") });
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ "/src/state/store.ts");
    m.getStore().actions.setTheme("light");
  });
  await settle(page);
  await page.screenshot({ path: join(SHOTS, "chat-light.png") });
  await page.locator("[data-testid=session-list] .ss-row").first().locator(".ss-open").click();
  await expect(page.locator(".xterm-rows")).toContainText("you said");
  await settle(page);
  await page.screenshot({ path: join(SHOTS, "session-light.png") });
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
  await page.waitForTimeout(300); // the popover fades in
  await page.screenshot({ path: join(SHOTS, "menu-light.png") });
});
