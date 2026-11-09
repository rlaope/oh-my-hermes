// Model picker: search field (focused on open, compact matching, Up/Down/Enter, Esc) and vendor chips.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS; // set to an absolute dir to save picker screenshots

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "ms1") res(msg);
    };
    ws.send(JSON.stringify({ id: "ms1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

const setModelCalls = async () =>
  ((await mock("mock.calls")).calls as { op: string; params: Record<string, unknown> }[])
    .filter((c) => c.op === "chat.set_model")
    .map((c) => c.params);

async function openPicker(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("model-pill").click();
  const pop = page.getByTestId("model-pop");
  await expect(pop.getByTestId("model-opt").first()).toBeVisible();
  return pop;
}

const names = (pop: ReturnType<Page["getByTestId"]>) => pop.getByTestId("model-opt").locator(".mp-n");

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("search is focused on open and filters by model and provider as you type", async ({ page }) => {
  const pop = await openPicker(page);
  const search = pop.getByTestId("model-search");
  await expect(search).toBeFocused();
  await expect(pop.getByTestId("model-opt")).toHaveCount(12);

  await page.keyboard.type("GPT");
  await expect(names(pop)).toHaveText(["gpt-5.5", "gpt-5.5-mini"]);
  await expect(pop.locator(".mp-g")).toHaveText(["OpenAI"]);

  // provider name matches every model it serves
  await search.fill("ollama");
  await expect(names(pop)).toHaveText(["llama-4-maverick", "my-local-model"]);

  // reasoning row and footer stay
  await expect(pop.getByRole("radiogroup", { name: "Reasoning" })).toBeVisible();
  await expect(pop.getByRole("button", { name: "Bot settings" })).toBeVisible();
});

test("compact match: 'opus55' finds claude-opus-5-5 and Opus 5.5", async ({ page }) => {
  const pop = await openPicker(page);
  await pop.getByTestId("model-search").fill("opus55");
  await expect(names(pop)).toHaveText(["Opus 5.5", "anthropic/claude-opus-5-5"]);
  await expect(pop.locator(".mp-g")).toHaveText(["Claude (proxy)", "OpenRouter"]);
});

test("vendor chips: only vendors with models, each with its mark; a chip filters the list", async ({ page }) => {
  const pop = await openPicker(page);
  const chips = pop.getByTestId("model-chips").getByRole("button");
  await expect(chips).toHaveText(["All", "Claude", "OpenAI", "Gemini", "DeepSeek", "Grok", "Qwen", "Llama", "Other"]);
  await expect(pop.getByTestId("model-chip-all")).toHaveAttribute("aria-pressed", "true");
  for (const id of ["claude", "openai", "gemini", "deepseek", "grok", "qwen", "meta"])
    await expect(pop.locator(`[data-testid="model-chip-${id}"] svg.model-ic[data-mark="${id}"]`)).toHaveCount(1);
  await expect(pop.locator('[data-testid="model-chip-kimi"], [data-testid="model-chip-mistral"]')).toHaveCount(0);

  await pop.getByTestId("model-chip-claude").click();
  await expect(names(pop)).toHaveText(["Opus 5.5", "Sonnet 5.5", "Haiku 5", "anthropic/claude-opus-5-5"]);
  const on = pop.getByTestId("model-chip-claude");
  await expect(on).toHaveAttribute("aria-pressed", "true");
  // the chosen chip is gray, never the brand gradient
  expect(await on.evaluate((el) => getComputedStyle(el).backgroundImage)).toBe("none");
  const [r, g, b] = (await on.evaluate((el) => getComputedStyle(el).backgroundColor)).match(/\d+(\.\d+)?/g)!.map(Number);
  expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThan(24);

  await pop.getByTestId("model-chip-other").click();
  await expect(names(pop)).toHaveText(["my-local-model"]);
  await pop.getByTestId("model-chip-all").click();
  await expect(pop.getByTestId("model-opt")).toHaveCount(12);
});

test("chip and search combine", async ({ page }) => {
  const pop = await openPicker(page);
  await pop.getByTestId("model-chip-claude").click();
  await pop.getByTestId("model-search").fill("opus");
  await expect(names(pop)).toHaveText(["Opus 5.5", "anthropic/claude-opus-5-5"]);
  await pop.getByTestId("model-chip-openai").click();
  await expect(pop.getByTestId("model-opt")).toHaveCount(0);
  await pop.getByTestId("model-search").fill("mini");
  await expect(names(pop)).toHaveText(["gpt-5.5-mini"]);
});

test("keyboard: Down/Up move the highlight, Enter picks, Esc closes", async ({ page }) => {
  const pop = await openPicker(page);
  await page.keyboard.type("gpt");
  const rows = pop.getByTestId("model-opt");
  await expect(rows.nth(0)).toHaveAttribute("data-active", "true");
  await page.keyboard.press("ArrowDown");
  await expect(rows.nth(1)).toHaveAttribute("data-active", "true");
  await page.keyboard.press("ArrowDown"); // wraps
  await expect(rows.nth(0)).toHaveAttribute("data-active", "true");
  await page.keyboard.press("ArrowUp");
  await expect(rows.nth(1)).toHaveAttribute("data-active", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("model-label")).toHaveText("gpt-5.5-mini");
  await expect.poll(setModelCalls).toEqual([{ bot: "kami", model: "gpt-5.5-mini", provider: "openai" }]);

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("model-pop")).toHaveCount(0);
  // reopening starts fresh: empty search, All, the current model highlighted
  await page.getByTestId("model-pill").click();
  const again = page.getByTestId("model-pop");
  await expect(again.getByTestId("model-search")).toHaveValue("");
  await expect(again.getByTestId("model-search")).toBeFocused();
  await expect(again.getByTestId("model-opt")).toHaveCount(12);
  await expect(again.locator('[data-active="true"]')).toContainText("gpt-5.5-mini");
});

test("Esc closes the picker and gives focus back to the model button", async ({ page }) => {
  const pop = await openPicker(page);
  await expect(pop.getByTestId("model-search")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("model-pop")).toHaveCount(0);
  await expect(page.getByTestId("model-pill")).toBeFocused();
  await expect(page.getByTestId("model-pill")).toHaveAttribute("aria-expanded", "false");
  // Enter on the focused button opens it again, search focused
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("model-search")).toBeFocused();
});

// The header at the Tauri minimum window (900x700) with Details open: the model button stays inside the
// header and off the panel, whatever the id length; a long id ellipsizes and keeps the full id in its title.
test("long model id ellipsizes and stays inside the header at 900x700 with the panel open", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 700 });
  const check = async (id: string) => {
    const label = page.getByTestId("model-label");
    await expect(label).toHaveText(id);
    await expect(label).toHaveAttribute("title", id);
    await expect.poll(async () => Math.round((await page.getByTestId("details").boundingBox())?.width ?? 0)).toBe(300);
    const head = (await page.getByTestId("header").boundingBox())!;
    const pill = (await page.getByTestId("model-pill").boundingBox())!;
    const panel = (await page.getByTestId("details").boundingBox())!;
    expect(pill.x + pill.width).toBeLessThanOrEqual(head.x + head.width + 0.5);
    expect(pill.x + pill.width).toBeLessThanOrEqual(panel.x + 0.5);
    expect((await label.boundingBox())!.width).toBeLessThanOrEqual(220.5);
    // the panel's top bar is what sits at its left edge, not the model button
    const hit = await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.closest("[data-testid]")?.getAttribute("data-testid"), [
      panel.x + 4,
      panel.y + 20,
    ]);
    // below 1100px the panel overlays the chat; what sits there may carry no test id, which is fine
    expect(hit ?? "").not.toMatch(/^(model-|reasoning-)/);
  };

  // the longest id the mock offers, picked through the UI
  await openPicker(page);
  await page.keyboard.type("anthropic/claude");
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
  await page.getByTestId("who").click();
  await check("anthropic/claude-opus-5-5");

  // an id far longer than the button: the text is cut with an ellipsis, not pushed past the header
  const long = "openrouter-preview/anthropic/claude-opus-5-5-thinking-extended-2026-11-01";
  await mock("chat.set_model", { bot: "kami", model: long });
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("who").click();
  await check(long);
  const label = page.getByTestId("model-label");
  expect(await label.evaluate((el) => getComputedStyle(el).textOverflow)).toBe("ellipsis");
  expect(await label.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
});

// Keyboard focus in the picker shows a 2px ring at ink 40%, 2px off the edge, in dark and light; the small
// gray labels in the popover meet 4.5:1 on the popover background in dark.
test("focus ring on search, chips and rows; small labels readable in dark", async ({ page }) => {
  const ring = (el: Element) => {
    const cs = getComputedStyle(el);
    return { style: cs.outlineStyle, width: cs.outlineWidth, offset: cs.outlineOffset, color: cs.outlineColor };
  };
  const expectRing = (r: { style: string; width: string; offset: string; color: string }) => {
    expect(r.style).toBe("solid");
    expect(r.width).toBe("2px");
    expect(r.offset).toBe("2px");
    const alpha = Number(r.color.match(/[\d.]+(?=\))/)?.[0]);
    expect(alpha).toBeGreaterThan(0.35);
    expect(alpha).toBeLessThan(0.45);
  };
  for (const theme of ["dark", "light"] as const) {
    await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
    const pop = await openPicker(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    expectRing(await pop.locator(".mp-search").evaluate(ring));
    await page.keyboard.press("Tab");
    await expect(pop.getByTestId("model-chip-all")).toBeFocused();
    expectRing(await pop.getByTestId("model-chip-all").evaluate(ring));
    const firstRow = pop.getByTestId("model-opt").first();
    await firstRow.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await expect(firstRow).toBeFocused();
    expectRing(await firstRow.evaluate(ring));

    if (theme === "dark") {
      const contrast = await pop.evaluate((root) => {
        const rgb = (c: string) => c.match(/[\d.]+/g)!.slice(0, 3).map(Number);
        const lum = (c: number[]) => {
          const [r, g, b] = c.map((v) => {
            v /= 255;
            return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
          });
          return 0.2126 * r + 0.7152 * g + 0.0722 * b;
        };
        const bg = rgb(getComputedStyle(root.closest(".ui-pop")!).backgroundColor);
        const ratio = (el: Element) => {
          const a = lum(rgb(getComputedStyle(el).color));
          const b = lum(bg);
          return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
        };
        return [".mp-g", ".mp-h", ".mp-f", ".mp-chip:not(.on)"].map((sel) => [sel, ratio(root.querySelector(sel)!)] as const);
      });
      for (const [sel, r] of contrast) expect(r, sel).toBeGreaterThanOrEqual(4.5);
    }
  }
});

test("empty result says 'No models match'; Enter does nothing", async ({ page }) => {
  const pop = await openPicker(page);
  await pop.getByTestId("model-search").fill("zzz-nothing");
  await expect(pop.getByTestId("model-empty")).toHaveText("No models match");
  await expect(pop.getByTestId("model-opt")).toHaveCount(0);
  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowDown");
  expect(await setModelCalls()).toEqual([]);
  await expect(page.getByTestId("model-label")).toHaveText("Opus 5.5");
});

test("picker screenshots, dark and light", async ({ page }) => {
  test.skip(!SHOTS, "set OMHER_SHOTS to save screenshots");
  mkdirSync(SHOTS!, { recursive: true });
  for (const theme of ["dark", "light"] as const) {
    await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
    const pop = await openPicker(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await page.waitForTimeout(400); // let the popover's fade-in finish
    await page.screenshot({ path: `${SHOTS}/picker-${theme}.png`, clip: { x: 720, y: 0, width: 560, height: 640 } });
    await pop.getByTestId("model-chip-claude").click();
    await pop.getByTestId("model-search").fill("opus");
    await page.keyboard.press("ArrowDown");
    await page.screenshot({ path: `${SHOTS}/picker-${theme}-filtered.png`, clip: { x: 720, y: 0, width: 560, height: 640 } });
    await pop.getByTestId("model-search").fill("zzz");
    await page.screenshot({ path: `${SHOTS}/picker-${theme}-empty.png`, clip: { x: 720, y: 0, width: 560, height: 640 } });
  }
});
