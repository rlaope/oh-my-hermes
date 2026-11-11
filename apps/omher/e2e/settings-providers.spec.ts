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
