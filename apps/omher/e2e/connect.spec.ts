// The chat's connect block: when Hermes says a bot cannot answer (`bots.ready` -> its `setup.runtime_check`), the
// bot's timeline shows one quiet line with ChatGPT / Codex, Nous Portal and "API key…" (no Claude). A sign-in opens the
// system terminal with exactly `hermes auth add <id>` (`__omherSignInHost` stands in for the shell here); the block
// then says to finish there, asks the bot again every 3 s and on focus, sets the provider's cost-safe model through
// chat.set_model once the strict check for it passes, and goes away. A ready bot (the existing user) shows nothing
// and costs one bots.ready. `mock.ready {bot, ok, signIn?}` switches the mock between those answers.
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
      if (msg.id === "c1") res(msg);
    };
    ws.send(JSON.stringify({ id: "c1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

const calls = async (op: string): Promise<Record<string, unknown>[]> =>
  ((await mock("mock.calls")).calls as { op: string; params: Record<string, unknown> }[]).filter((c) => c.op === op).map((c) => c.params);

async function open(page: Page, lang?: string) {
  await page.addInitScript((l) => {
    (window as any).__signIns = [];
    (window as any).__omherSignInHost = {
      open: async (provider: string) => {
        (window as any).__signIns.push(provider);
      },
    };
    if (l) localStorage.setItem("omher.lang", l);
  }, lang ?? "");
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});
test.afterAll(async () => {
  await mock("mock.reset");
});

test("a ready bot shows no block and is asked once", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("timeline")).toBeVisible();
  await expect.poll(async () => (await calls("bots.ready")).filter((p) => p.bot === "kami").length).toBe(1);
  await expect(page.getByTestId("connect-block")).toHaveCount(0);
  // back and forth between bots: still one ask per bot, no block on either
  await page.getByTestId("bot-friren").click();
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("connect-block")).toHaveCount(0);
  const asked = (await calls("bots.ready")).map((p) => p.bot);
  expect(asked.filter((b) => b === "kami").length).toBe(1);
  expect(asked.filter((b) => b === "friren").length).toBe(1);
  expect(asked.every((b) => typeof b === "string")).toBe(true);
});

test("a bot with no AI account shows one quiet line; sign in clears it and focuses the composer", async ({ page }) => {
  await mock("mock.ready", { bot: "kami", ok: false });
  await open(page);
  const block = page.getByTestId("connect-block");
  await expect(block).toBeVisible();
  await expect(page.getByTestId("connect-text")).toHaveText("Kami needs an AI account to answer.");
  await expect(block.getByRole("button")).toHaveText(["ChatGPT / Codex", "Nous Portal", "API key…"]);
  await expect(page.getByTestId("connect-nous")).toHaveAttribute("title", "hermes auth add nous");
  await expect(page.getByTestId("connect-anthropic")).toHaveCount(0);
  // quiet: no filled card
  const bg = await block.evaluate((e) => getComputedStyle(e).backgroundColor);
  expect(bg === "rgba(0, 0, 0, 0)" || bg === "transparent").toBe(true);
  // the composer stays usable
  await expect(page.getByTestId("composer")).toBeEnabled();
  // the no-model note does not stack under it
  await expect(page.getByTestId("chat-no-model")).toHaveCount(0);

  await page.getByTestId("connect-nous").click();
  expect(await page.evaluate(() => (window as any).__signIns)).toEqual(["nous"]);
  await expect(page.getByTestId("connect-text")).toHaveText("Finish signing in in the terminal window.");
  await page.getByTestId("composer").blur();

  // the terminal finished `hermes auth add nous`: the strict check passes, no model is set yet
  await mock("mock.ready", { bot: "kami", ok: false, signIn: "nous" });
  await expect(block).toHaveCount(0, { timeout: 8_000 });
  await expect(page.getByTestId("composer")).toBeFocused();
  // the main chat got nous' first model that is not an Opus or Fable tier, through the model menu's own op
  const sets = await calls("chat.set_model");
  expect(sets).toEqual([{ bot: "kami", provider: "nous", model: "moonshotai/kimi-k3" }]);
  expect((await calls("bots.ready")).some((p) => p.provider === "nous")).toBe(true);
});

test("window focus asks a waiting sign-in at once", async ({ page }) => {
  await mock("mock.ready", { bot: "kami", ok: false });
  await open(page);
  await page.getByTestId("connect-openai-codex").click();
  await expect(page.getByTestId("connect-text")).toHaveText("Finish signing in in the terminal window.");
  await mock("mock.ready", { bot: "kami", ok: true });
  const before = (await calls("bots.ready")).length;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByTestId("connect-block")).toHaveCount(0, { timeout: 2_500 });
  expect((await calls("bots.ready")).length).toBeGreaterThan(before);
});

test("multi-bot: the block shows only on the bot that cannot answer", async ({ page }) => {
  await mock("mock.ready", { bot: "friren", ok: false });
  await open(page);
  await expect(page.getByTestId("connect-block")).toHaveCount(0);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("connect-block")).toHaveAttribute("data-bot", "friren");
  await expect(page.getByTestId("connect-text")).toHaveText("Friren needs an AI account to answer.");
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("connect-block")).toHaveCount(0);
});

test("API key… opens Settings › Providers, whose Add key is the --type api-key form", async ({ page }) => {
  await mock("mock.ready", { bot: "kami", ok: false });
  await open(page);
  await page.getByTestId("connect-key").click();
  await expect(page.getByTestId("settings-page-providers")).toBeVisible();
  await expect(page.getByTestId("providers-add-key")).toBeVisible();
});

test("with no desktop shell the block names the command to run", async ({ page }) => {
  await mock("mock.ready", { bot: "kami", ok: false });
  await page.goto("/");
  await expect(page.getByTestId("connect-block")).toBeVisible();
  await page.getByTestId("connect-nous").click();
  await expect(page.getByTestId("connect-problem")).toHaveText("Run hermes auth add nous in a terminal.");
  await expect(page.getByTestId("connect-text")).toHaveText("Kami needs an AI account to answer.");
});

test("the OMH model-setup line waits while the bot cannot answer, and shows once it can", async ({ page }) => {
  await mock("mock.ready", { bot: "kami", ok: false });
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("e2e.started")) {
      localStorage.setItem("omher.omhPrompt", "pending");
      sessionStorage.setItem("e2e.started", "1");
    }
    (window as any).__omherPromptDelays = [0, 150, 150, 150];
  });
  await mock("mock.skills", { add: [{ name: "omh-model-setup", description: "[omh] Model and provider configuration changes" }] });
  await open(page);
  await expect(page.getByTestId("connect-block")).toBeVisible();
  await page.waitForTimeout(800);
  await expect(page.getByTestId("omh-prompt")).toHaveCount(0);
  await mock("mock.ready", { bot: "kami", ok: true });
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.getByTestId("bot-friren").click();
  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("connect-block")).toHaveCount(0);
  await expect(page.getByTestId("omh-prompt")).toBeVisible();
});

test("the first-run install of Hermes lands in the default bot's chat, where the block shows when it has no account", async ({ page }) => {
  await mock("mock.ready", { bot: "default", ok: false });
  await page.addInitScript(() => {
    let hermes = false;
    (window as any).__OMHER_GATE__ = {
      status: async () => (hermes ? { state: "ready" } : { state: "failed", error: "Hermes not found", missing: "hermes" }),
      retry: async () => {},
      installCommand: async () => "curl -fsSL https://omher.app/install.sh | sh -s -- omher@beta --no-app",
      install: async (on: (e: unknown) => void) => {
        on({ kind: "line", text: "[ok] Hermes Agent installed" });
        hermes = true;
        return 0;
      },
    };
  });
  await page.goto("/");
  await page.getByTestId("setup-install").click();
  await expect(page.getByTestId("bot-default")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("connect-block")).toHaveAttribute("data-bot", "default");
  await expect(page.getByTestId("connect-text")).toHaveText("Hermes needs an AI account to answer.");
});

for (const [lang, needs, finish] of [
  ["ko", "Kami이(가) 답하려면 AI 계정이 필요해요.", "터미널 창에서 로그인을 마치세요."],
  ["ja", "Kami が答えるには AI アカウントが必要です。", "ターミナルのウィンドウでサインインを完了してください。"],
  ["zh", "Kami 需要一个 AI 账户才能回答。", "请在终端里完成登录。"],
] as const) {
  test(`the block in ${lang}`, async ({ page }) => {
    await mock("mock.ready", { bot: "kami", ok: false });
    await open(page, lang);
    await expect(page.getByTestId("connect-text")).toHaveText(needs);
    await page.getByTestId("connect-nous").click();
    await expect(page.getByTestId("connect-text")).toHaveText(finish);
  });
}

test("in a long chat the block sits above the composer, visible without scrolling", async ({ page }) => {
  await mock("mock.ready", { bot: "kami", ok: false });
  await open(page);
  const block = page.getByTestId("connect-block");
  await expect(block).toBeVisible();
  const events = Array.from({ length: 40 }, (_, i) => ({
    event: "message", bot: "kami", id: `long-${i}`, text: `Line ${i}: ${"a long answer ".repeat(12)}`,
  }));
  await mock("mock.emit", { events });
  await expect(page.locator(".thread").first().getByText("Line 39:", { exact: false })).toBeVisible();
  // the thread really scrolls: its content is taller than its box
  expect(await page.locator(".thread").first().evaluate((e) => e.scrollHeight > e.clientHeight + 200)).toBe(true);
  await expect(block).toBeInViewport();
  const b = await block.boundingBox();
  const c = await page.getByTestId("composer").boundingBox();
  expect(b && c && b.y + b.height <= c.y + 1).toBe(true);
  // not inside the scrolling thread
  expect(await block.evaluate((e) => !!e.closest(".thread"))).toBe(false);
});
