// Settings node: model + reasoning pill/popover, the settings view, and the add-bot popover.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = join(dirname(fileURLToPath(import.meta.url)), "__shots__");

test.use({ colorScheme: "dark" });

/** One request to the mock bridge over its own websocket (mock.reset, mock.calls). */
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

const callsOf = async (op: string) =>
  ((await mock("mock.calls")).calls as { op: string; params: Record<string, unknown> }[]).filter((c) => c.op === op);

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("model pill: the model control plus the panel button, popover lists providers and models with the current one checked", async ({ page }) => {
  await open(page);
  const right = page.getByTestId("head-right");
  await expect(right.locator(":scope > *")).toHaveCount(2);
  expect(await right.locator("button, a, [role=button], input, select").count()).toBe(2);
  const pill = page.getByTestId("model-pill");
  // the model's company mark sits before the name (Opus -> Claude)
  await expect(pill.locator('svg.model-ic[data-mark="claude"]')).toBeVisible();
  await expect(pill).toContainText("Opus 5.5");
  await expect(pill).toContainText("high");

  await pill.click();
  const pop = page.getByTestId("model-pop");
  await expect(pop).toBeVisible();
  await expect(pop.locator(".mp-g")).toHaveText(["Claude (proxy)", "OpenAI", "OpenRouter", "Ollama"]);
  const opts = pop.getByTestId("model-opt");
  await expect(opts).toHaveCount(12);
  const on = pop.locator(".mp-opt.on");
  await expect(on).toHaveCount(1);
  await expect(on).toContainText("Opus 5.5");
  // selection is gray, never the brand gradient
  expect(await on.evaluate((el) => getComputedStyle(el).backgroundImage)).toBe("none");
  await expect(pop.getByRole("radio", { name: "high", exact: true })).toHaveAttribute("aria-checked", "true");
  // only the levels the bot's route sends, in Hermes' order: a Claude route has no ultra next to max (Hermes clamps it
  // to max there). Seven do not fit one row, so they sit in rows of four, no label clipped
  const levels = pop.getByTestId("reasoning-seg").getByRole("radio");
  await expect(levels).toHaveText(["none", "minimal", "low", "medium", "high", "xhigh", "max"]);
  const boxes = await levels.evaluateAll((bs) =>
    bs.map((b) => {
      const r = b.getBoundingClientRect();
      return { top: Math.round(r.top), left: r.left, right: r.right, fits: b.scrollWidth <= b.clientWidth };
    }),
  );
  expect(new Set(boxes.map((b) => b.top)).size).toBe(2);
  expect(boxes.slice(0, 4).every((b) => b.top === boxes[0].top) && boxes.slice(4).every((b) => b.top === boxes[4].top)).toBe(true);
  // the three-button last row stretches the full width: its edges line up with the first row's
  expect(Math.abs(boxes[4].left - boxes[0].left)).toBeLessThanOrEqual(1);
  expect(Math.abs(boxes[6].right - boxes[3].right)).toBeLessThanOrEqual(1);
  expect(boxes.every((b) => b.fits)).toBe(true);

  // Escape closes
  await page.keyboard.press("Escape");
  await expect(pop).toHaveCount(0);
});

test("changing reasoning and model calls chat.set_model and updates the pill", async ({ page }) => {
  await open(page);
  await page.getByTestId("model-pill").click();
  const pop = page.getByTestId("model-pop");
  await pop.getByRole("radio", { name: "xhigh", exact: true }).click();
  await expect(page.getByTestId("reasoning-label")).toHaveText("xhigh");
  await expect(pop.getByRole("radio", { name: "xhigh", exact: true })).toHaveAttribute("aria-checked", "true");
  await expect(pop.getByTestId("reasoning-sent")).toHaveCount(0); // sent as picked: nothing more to say
  await expect.poll(async () => (await callsOf("chat.set_model")).map((c) => c.params)).toEqual([
    { bot: "kami", reasoning: "xhigh" },
  ]);

  await pop.getByRole("radio", { name: "max", exact: true }).click();
  await expect(page.getByTestId("reasoning-label")).toHaveText("max");
  await expect(pop.getByRole("radio", { name: "ultra", exact: true })).toHaveCount(0);
  await expect.poll(async () => (await callsOf("chat.set_model")).map((c) => c.params)).toEqual([
    { bot: "kami", reasoning: "xhigh" },
    { bot: "kami", reasoning: "max" },
  ]);

  await pop.getByTestId("model-opt").filter({ hasText: "GPT-6.1 Terra" }).click();
  await expect(page.getByTestId("model-label")).toHaveText("GPT-6.1 Terra");
  await expect(pop.locator(".mp-opt.on")).toContainText("GPT-6.1 Terra");
  const calls = await callsOf("chat.set_model");
  expect(calls[2].params).toEqual({ bot: "kami", model: "gpt-6.1-terra", provider: "openai" });
  await expect(page.getByTestId("model-note")).toHaveCount(0);
});

test("a saved level the route clamps reads as the level sent, in the pill, the picker and the bot's Settings page", async ({ page }) => {
  // `ultra` saved from elsewhere (Hermes' own /reasoning, an older omher): a Claude route sends max
  expect(await mock("chat.set_model", { bot: "kami", reasoning: "ultra" })).toMatchObject({ reasoning: "ultra", reasoning_wire: "max" });
  await open(page);
  await expect(page.getByTestId("reasoning-label")).toHaveText("max");
  await page.getByTestId("model-pill").click();
  const pop = page.getByTestId("model-pop");
  const seg = pop.getByTestId("reasoning-seg");
  await expect(seg.getByRole("radio")).toHaveText(["none", "minimal", "low", "medium", "high", "xhigh", "max"]);
  await expect(seg.getByRole("radio", { name: "max", exact: true })).toHaveAttribute("aria-checked", "true");
  await expect(pop).not.toContainText("ultra");
  // picking the level shown replaces the saved one
  await seg.getByRole("radio", { name: "max", exact: true }).click();
  await expect.poll(async () => (await callsOf("chat.set_model")).map((c) => c.params).at(-1)).toEqual({ bot: "kami", reasoning: "max" });
  await expect(page.getByTestId("reasoning-label")).toHaveText("max");
  await page.getByRole("button", { name: "Bot settings" }).click(); // the popover's link to the bot's page
  const body = page.getByTestId("settings-page-bot-kami");
  const row = body.locator(".st-row").filter({ hasText: /^Reasoning/ });
  await expect(row).toContainText("max");
  await expect(row).not.toContainText("ultra");
});

test("a codex app-server route offers ultra, and switching to a Claude model takes it away at once", async ({ page }) => {
  await mock("mock.codex", { bot: "kami" });
  await open(page);
  await expect(page.getByTestId("reasoning-label")).toHaveText("ultra");
  await page.getByTestId("model-pill").click();
  const pop = page.getByTestId("model-pop");
  const seg = pop.getByTestId("reasoning-seg");
  // codex's own harness mode: sent as picked there, so it is a level of this route (no minimal on codex)
  await expect(seg.getByRole("radio")).toHaveText(["none", "low", "medium", "high", "xhigh", "max", "ultra"]);
  await expect(seg.getByRole("radio", { name: "ultra", exact: true })).toHaveAttribute("aria-checked", "true");
  await pop.getByTestId("model-opt").filter({ hasText: "Sonnet 5.5" }).click();
  await expect(page.getByTestId("model-label")).toHaveText("Sonnet 5.5");
  await expect(seg.getByRole("radio")).toHaveText(["none", "minimal", "low", "medium", "high", "xhigh", "max"]);
  await expect(seg.getByRole("radio", { name: "max", exact: true })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("reasoning-label")).toHaveText("max");
});

test("unsupported: one gray note, the old value stays", async ({ page }) => {
  // The mock always accepts chat.set_model; answer it `unsupported` in the page's socket instead.
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (msg.op === "chat.set_model") {
        ws.send(JSON.stringify({ id: msg.id, ok: false, error: { code: "unsupported", message: "Hermes cannot change this yet" } }));
        return;
      }
      server.send(raw);
    });
  });
  await open(page);
  await page.getByTestId("model-pill").click();
  const pop = page.getByTestId("model-pop");
  await pop.getByRole("radio", { name: "Low" }).click();
  const note = page.getByTestId("model-note");
  await expect(note).toHaveText("Change it in Hermes for now");
  await expect(page.getByTestId("reasoning-label")).toHaveText("high");
  await expect(pop.getByRole("radio", { name: "high", exact: true })).toHaveAttribute("aria-checked", "true");
  const color = await note.evaluate((el) => getComputedStyle(el).color);
  const [r, g, b] = color.match(/\d+/g)!.map(Number);
  expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThan(24); // gray, not a colour
});

test("settings opens and closes; theme Light sets data-theme; bot and provider pages", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => localStorage.removeItem("omher.theme"));
  await open(page);
  await page.getByTestId("nav-settings").click();
  const view = page.getByTestId("settings-view");
  await expect(view).toBeVisible();
  await expect(page.getByTestId("composer")).toHaveCount(0);
  for (const label of ["Kami", "Friren", "Hermes", "General", "Providers"])
    await expect(view.locator(".st-nav").getByRole("button", { name: label, exact: true })).toBeVisible();
  // Computer is not built yet, and its nav entry says so
  await expect(view.locator(".st-nav").getByRole("button", { name: "Computer Soon", exact: true })).toBeVisible();

  // General: theme
  await expect(page.getByTestId("settings-nav-general")).toHaveAttribute("aria-current", "page");
  const theme = page.getByTestId("theme-seg");
  await expect(theme.getByRole("radio", { name: "System" })).toHaveAttribute("aria-checked", "true");
  await theme.getByRole("radio", { name: "Light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(await page.evaluate(() => localStorage.getItem("omher.theme"))).toBe("light");
  await theme.getByRole("radio", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  // Bot page: its messaging platforms (e2e/platforms.spec.ts), who it is (persona, memory, automations, elsewhere,
  // open threads; e2e/bot-page.spec.ts), then Profile, Model, Work
  await page.getByTestId("settings-nav-bot-friren").click();
  const body = page.getByTestId("settings-page-bot-friren");
  await expect(body.locator(".st-gh")).toHaveText(["Messaging", /^Persona/, "Memory", /^Automations/, "Elsewhere", "Open threads", "Profile", "Model", "Work"]);
  await expect(body).toContainText("Sonnet 5.5");
  await expect(body).toContainText("medium");
  await expect(body).toContainText("friren");

  // Providers: read-only list from models.options
  await page.getByTestId("settings-nav-providers").click();
  const list = page.getByTestId("providers-list");
  await expect(list).toContainText("Claude (proxy)");
  await expect(list).toContainText("OpenAI");
  await expect(list.locator("input, select, textarea")).toHaveCount(0);

  await page.getByTestId("settings-nav-computer").click();
  await expect(page.getByTestId("settings-page-computer")).toContainText("Soon");

  // close with the header button
  await page.getByRole("button", { name: "Close settings" }).click();
  await expect(view).toHaveCount(0);
  await expect(page.getByTestId("composer")).toBeVisible();

  // the popover's "Bot settings" link opens the bot's page
  await page.getByTestId("model-pill").click();
  await page.getByRole("button", { name: "Bot settings" }).click();
  await expect(page.getByTestId("settings-page-bot-kami")).toBeVisible();
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("settings-view")).toHaveCount(0);
});

test("add bot: lists the profiles not in the list; Add attaches one, re-reads bots.list and opens it", async ({ page }) => {
  // Kami alone in the list; the default profile shows as not connected until something attaches it (models.options).
  await page.addInitScript(() => {
    if (sessionStorage.getItem("addbot-e2e")) return;
    sessionStorage.setItem("addbot-e2e", "1");
    localStorage.setItem("omher.roster", JSON.stringify(["kami"]));
  });
  let attached = false;
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    const ops = new Map<string, string>();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      ops.set(msg.id, msg.op);
      if (msg.op === "models.options" && msg.bot === "default") attached = true;
      server.send(raw);
    });
    server.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (ops.get(msg.id) === "bots.list" && msg.ok && !attached) {
        for (const b of msg.result.bots) if (b.name === "default") b.status = "offline";
        ws.send(JSON.stringify(msg));
        return;
      }
      ws.send(raw);
    });
  });
  await open(page);
  const before = (await callsOf("bots.list")).length;
  await page.getByRole("button", { name: "Add a bot" }).click();
  const pop = page.getByTestId("addbot");
  await expect(pop).toBeVisible();
  await expect(pop.locator(".ab-h")).toHaveText("Add a bot");
  for (const name of ["Friren", "Hermes", "OMH TUI"]) await expect(pop.getByText(name, { exact: true })).toBeVisible();
  // Kami is in the list already: not offered; no "Create a new bot (soon)" row
  await expect(page.getByTestId("addbot-kami")).toHaveCount(0);
  await expect(page.getByTestId("addbot-create")).toHaveCount(0);
  await expect(page.getByTestId("addbot-default")).toContainText("Haiku 5");

  await page.getByTestId("addbot-default").getByRole("button", { name: "Add" }).click();
  await expect(pop).toHaveCount(0);
  await expect(page.getByTestId("bot-default")).toHaveAttribute("aria-current", "true");
  await expect.poll(() => attached).toBe(true);
  await expect.poll(async () => (await callsOf("bots.list")).length).toBeGreaterThan(before);
  // no file copied, no chat written: only reads were sent
  const ops = new Set(((await mock("mock.calls")).calls as { op: string }[]).map((c) => c.op));
  for (const op of ["chat.send", "chat.set_model"]) expect(ops.has(op)).toBe(false);
});

test("screenshots: settings in dark and light", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => localStorage.removeItem("omher.theme"));
  await open(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-bot-kami").click();
  await expect(page.getByTestId("settings-page-bot-kami")).toContainText("Opus 5.5");
  await expect(page.getByTestId("settings-page-bot-kami")).toContainText("2 routines");
  await page.mouse.move(700, 600);
  await page.screenshot({ path: join(SHOTS, "settings-dark.png") });

  await page.getByTestId("settings-nav-general").click();
  await page.getByTestId("theme-seg").getByRole("radio", { name: "Light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByTestId("settings-nav-bot-kami").click();
  await page.mouse.move(700, 600);
  await page.waitForTimeout(400); // let colour transitions settle
  await page.screenshot({ path: join(SHOTS, "settings-light.png") });
});
