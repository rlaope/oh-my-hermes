// Settings › Providers with long catalogs (Nous Portal 58, OpenRouter 60): compact rows, one open provider,
// vendor-grouped models, a filter for long lists, and no horizontal overflow at the 900px minimum width.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

test.use({ colorScheme: "dark" });

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

async function openProviders(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-providers").click();
  await expect(page.getByTestId("provider-row-nous")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
  await mock("mock.providers", { fixture: "long" });
});
test.afterAll(async () => {
  await mock("mock.reset");
});

test("compact rows: mark, name, slug, in use, count; only the provider in use is open, current model first", async ({ page }) => {
  await openProviders(page);
  const nous = page.getByTestId("provider-row-nous");
  await expect(nous).toContainText("Nous Portal");
  await expect(nous.locator(".pv-slug")).toHaveText("nous");
  await expect(nous).toContainText("in use");
  await expect(nous).toContainText("58 models");
  await expect(nous.locator('[data-mark="nous"]')).toHaveCount(1);
  await expect(page.getByTestId("provider-row-openrouter").locator('[data-mark="openrouter"]')).toHaveCount(1);
  await expect(page.getByTestId("provider-row-openrouter")).toContainText("60 models");

  // only Nous starts open
  await expect(page.locator(".pv-row[aria-expanded=true]")).toHaveCount(1);
  await expect(nous).toHaveAttribute("aria-expanded", "true");
  const models = page.getByTestId("provider-models-nous");
  const first = models.getByTestId("provider-model").first();
  await expect(first).toHaveAttribute("data-id", "anthropic/claude-opus-5.5");
  await expect(first).toHaveClass(/\bon\b/);
  // the vendor prefix is shown once per group, not inside every name
  await expect(models.getByTestId("provider-group").first().locator(".pv-v")).toHaveText("anthropic");
  await expect(first).toHaveText("claude-opus-5.5");

  // the old wall of ids is gone: no row holds the joined list
  await expect(page.getByTestId("providers-list")).not.toContainText("anthropic/claude-opus-5.5 ·");
  // the setup line replaces the read-only note
  await expect(page.getByTestId("providers-setup")).toContainText("Set up in Hermes · hermes auth add <provider>");
});

test("a row opens and closes; long lists get a filter and :free shows as a tag", async ({ page }) => {
  await openProviders(page);
  const or = page.getByTestId("provider-row-openrouter");
  await expect(page.getByTestId("provider-models-openrouter")).toHaveCount(0);
  await or.click();
  await expect(or).toHaveAttribute("aria-expanded", "true");
  const body = page.getByTestId("provider-models-openrouter");
  const filter = page.getByTestId("provider-filter-openrouter");
  await filter.fill("free");
  const hits = body.getByTestId("provider-model");
  await expect(hits.first()).toBeVisible();
  for (const el of await hits.all()) await expect(el.locator(".pv-sfx")).toHaveText("free");
  await filter.fill("no-such-model-xyz");
  await expect(body).toContainText("No model matches");
  await or.click();
  await expect(page.getByTestId("provider-models-openrouter")).toHaveCount(0);

  // short lists have no filter
  await page.getByTestId("provider-row-claude-proxy").click();
  await expect(page.getByTestId("provider-models-claude-proxy").locator("input")).toHaveCount(0);
});

test("900px: no horizontal overflow, collapsed rows under 40px", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 820 });
  await openProviders(page);
  await page.getByTestId("provider-row-openrouter").click();
  await expect(page.getByTestId("provider-models-openrouter")).toBeVisible();
  const m = await page.evaluate(() => {
    const list = document.querySelector('[data-testid="providers-list"]') as HTMLElement;
    const body = document.querySelector(".st-body") as HTMLElement;
    const lr = list.getBoundingClientRect();
    const out = [...list.querySelectorAll("*")].filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && (r.right > lr.right + 0.5 || r.left < lr.left - 0.5);
    }).length;
    return {
      list: [list.scrollWidth, list.clientWidth],
      body: [body.scrollWidth, body.clientWidth],
      doc: [document.documentElement.scrollWidth, window.innerWidth],
      out,
    };
  });
  expect(m.list[0]).toBeLessThanOrEqual(m.list[1]);
  expect(m.body[0]).toBeLessThanOrEqual(m.body[1]);
  expect(m.doc[0]).toBeLessThanOrEqual(m.doc[1]);
  expect(m.out).toBe(0);
  await page.getByTestId("provider-row-openrouter").click();
  for (const row of await page.locator(".pv-row[aria-expanded=false]").all()) {
    const box = await row.boundingBox();
    expect(box!.height).toBeLessThan(40);
  }
});

test("Add key: the menu and a row's action ask the host for exactly that provider; the list re-reads on focus", async ({ page }) => {
  // stand-in for the desktop app's open_hermes_auth (the e2e page is a plain browser)
  await page.addInitScript(() => {
    (window as any).__authCalls = [];
    (window as any).__omherAuthHost = {
      open: async (provider: string) => {
        (window as any).__authCalls.push(provider);
      },
    };
  });
  await openProviders(page);
  const calls = () => page.evaluate(() => (window as any).__authCalls as string[]);

  await page.getByTestId("providers-add-key").click();
  const menu = page.getByTestId("providers-key-menu");
  await expect(menu).toBeVisible();
  const ids = await menu.getByRole("menuitem").locator("code").allTextContents();
  // Hermes' own ids first, then the bot's custom providers, each once
  expect(ids.slice(0, 7)).toEqual(["anthropic", "openai", "openrouter", "nous", "gemini", "xai", "deepseek"]);
  for (const custom of ["claude-proxy", "og", "openai-codex"]) expect(ids).toContain(custom);
  expect(new Set(ids).size).toBe(ids.length);
  await page.getByTestId("providers-key-openrouter").click();
  await expect(menu).toHaveCount(0);
  expect(await calls()).toEqual(["openrouter"]);
  await expect(page.getByTestId("providers-key-note")).toContainText("hermes auth add openrouter --type api-key");
  // omher never offers a place to type a key
  await expect(page.locator('input[type="password"]')).toHaveCount(0);

  // a provider row's own action
  await page.getByTestId("provider-row-og").hover();
  await page.getByTestId("provider-key-og").click();
  expect(await calls()).toEqual(["openrouter", "og"]);

  // coming back to the window reads the providers again
  const before = (await mock("mock.calls")).calls.filter((c: { op: string }) => c.op === "models.options").length;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect
    .poll(async () => (await mock("mock.calls")).calls.filter((c: { op: string }) => c.op === "models.options").length)
    .toBeGreaterThan(before);
});

test("Add key without the desktop app shows the command to run", async ({ page }) => {
  await openProviders(page);
  await page.getByTestId("providers-add-key").click();
  await page.getByTestId("providers-key-nous").click();
  await expect(page.getByTestId("providers-key-note")).toHaveText("Run hermes auth add nous --type api-key in a terminal.");
});

test("a long open list scrolls in its own box (≤340px) under a filter that stays visible; vendor gutter is tight", async ({ page }) => {
  await openProviders(page);
  const box = page.getByTestId("provider-scroll-nous");
  const filter = page.getByTestId("provider-filter-nous");
  await expect(box.getByTestId("provider-model").first()).toBeVisible();
  const m = await box.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { h: el.getBoundingClientRect().height, sh: el.scrollHeight, overflow: cs.overflowY, shadow: cs.boxShadow };
  });
  expect(m.h).toBeLessThanOrEqual(340);
  expect(m.sh).toBeGreaterThan(m.h); // 58 models do not fit: the box scrolls
  expect(m.overflow).toBe("auto");
  expect(m.shadow).toBe("none");
  // the filter sits outside (above) the scrolling box
  expect(await filter.evaluate((f) => !!f.closest('[data-testid="provider-scroll-nous"]'))).toBe(false);

  // scroll the list to its end: the filter is still on screen and the page itself did not move
  const pageTop = await page.locator(".st-body").evaluate((el) => el.scrollTop);
  await box.hover();
  await page.mouse.wheel(0, 4000);
  await expect.poll(() => box.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
  await expect(box.getByTestId("provider-model").last()).toBeInViewport();
  await expect(filter).toBeInViewport();
  const fb = (await filter.boundingBox())!;
  const bb = (await box.boundingBox())!;
  expect(fb.y + fb.height).toBeLessThanOrEqual(bb.y + 0.5);
  expect(await page.locator(".st-body").evaluate((el) => el.scrollTop)).toBe(pageTop);

  // vendor gutter: chips start within 110px of the body's left edge (was 140)
  const g = await page.getByTestId("provider-models-nous").evaluate((body) => {
    const b = body.getBoundingClientRect();
    const chips = body.querySelector(".pv-ms")!.getBoundingClientRect();
    return chips.left - b.left;
  });
  expect(g).toBeLessThanOrEqual(110);

  // the filter still narrows the scrolled list
  await filter.fill("grok");
  await expect(box.getByTestId("provider-model")).toHaveCount(2);
});
