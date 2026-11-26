// Dragging the sidebar's right edge resizes it (SidebarResizer.tsx): the width stays after a reload; a double click
// goes back to the usual width (248px); the main column and right panel keep their room (including panelMax and narrow
// overlay viewports); ←/→ on the focused handle step cleanly even during transitions. No bridge call is made.
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
      if (msg.id === "r1") res(msg);
    };
    ws.send(JSON.stringify({ id: "r1", op, ...params }));
  });
  ws.close();
  return reply.result;
}

const width = async (page: Page) => Math.round((await page.getByTestId("sidebar").boundingBox())?.width ?? 0);
const panelWidth = async (page: Page) => Math.round((await page.getByTestId("details").boundingBox())?.width ?? 0);
const saved = (page: Page) => page.evaluate(() => localStorage.getItem("omher.sideWidth"));

async function openApp(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect.poll(() => width(page)).toBe(248);
}

/** Press on the handle and move the pointer `dx` px (positive = right = wider), then let go. */
async function dragBy(page: Page, dx: number) {
  const h = (await page.getByTestId("sidebar-resizer").boundingBox())!;
  const x = h.x + h.width / 2;
  const y = h.y + 200;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx, y, { steps: 6 });
  await page.mouse.up();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("drag the sidebar's edge wider and narrower, it stays after a reload, and double-click resets it", async ({ page }) => {
  await openApp(page);
  await expect(page.getByTestId("sidebar-resizer")).toHaveCSS("cursor", "col-resize");
  await dragBy(page, 100);
  await expect.poll(() => width(page)).toBe(348);
  expect(await saved(page)).toBe("348");
  await expect(page.getByTestId("window")).not.toHaveClass(/side-dragging/);

  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await expect.poll(() => width(page)).toBe(348);

  await dragBy(page, -120);
  await expect.poll(() => width(page)).toBe(228);
  expect(await saved(page)).toBe("228");

  await page.getByTestId("sidebar-resizer").dblclick();
  await expect.poll(() => width(page)).toBe(248);
  expect(await saved(page)).toBeNull();
  await expect(page.getByTestId("sidebar-resizer")).toHaveAttribute("aria-valuenow", "248");
});

test("clamps to min and max while keeping the main column its room", async ({ page }) => {
  await openApp(page);
  await dragBy(page, 2000);
  await expect.poll(() => width(page)).toBe(480);
  const main = (await page.locator("main.main").boundingBox())!;
  expect(Math.round(main.width)).toBeGreaterThanOrEqual(359);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);

  await dragBy(page, -2000);
  await expect.poll(() => width(page)).toBe(204);
});

test("keyboard: rapid ←/→ presses step cleanly during transition, Enter resets width and aria-valuenow", async ({ page }) => {
  await openApp(page);
  const handle = page.getByTestId("sidebar-resizer");
  await handle.focus();
  // rapid consecutive presses without waiting for the 250ms CSS transition
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Shift+ArrowRight");
  await expect.poll(() => width(page)).toBe(248 + 16 + 16 + 64);
  await expect(handle).toHaveAttribute("aria-valuenow", "344");
  await page.keyboard.press("ArrowLeft");
  await expect.poll(() => width(page)).toBe(328);
  await page.keyboard.press("Enter");
  await expect.poll(() => width(page)).toBe(248);
  await expect(handle).toHaveAttribute("aria-valuenow", "248");
});

test("wide saved sidebar and right panel coexist without crushing main, including across reloads", async ({ page }) => {
  await page.setViewportSize({ width: 1120, height: 800 });
  await openApp(page);
  await dragBy(page, 2000);
  await expect.poll(() => width(page)).toBe(480);
  expect(await saved(page)).toBe("480");

  // opening Details or Diff at 1120px clamps the panel to 280px so sidebar (480) + main (>= 360) + panel fit with no overflow
  await page.getByTestId("places").click();
  await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", "details");
  await expect.poll(() => panelWidth(page)).toBe(280);
  await expect.poll(async () => Math.round((await page.locator("main.main").boundingBox())!.width)).toBeGreaterThanOrEqual(359);

  await page.getByTestId("panel-tab-diff").click();
  await expect.poll(() => panelWidth(page)).toBe(280);
  await expect.poll(async () => Math.round((await page.locator("main.main").boundingBox())!.width)).toBeGreaterThanOrEqual(359);

  // reload keeps both widths consistent (no mount-order race clipping or main crush)
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await expect.poll(() => width(page)).toBe(480);
  await expect.poll(() => panelWidth(page)).toBe(280);
  await expect.poll(async () => Math.round((await page.locator("main.main").boundingBox())!.width)).toBeGreaterThanOrEqual(359);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);

  // conversely, with a wide panel already open (400px Diff), dragging the sidebar clamps to keep main >= 360px
  await page.getByTestId("sidebar-resizer").dblclick();
  await expect.poll(() => width(page)).toBe(248);
  await expect.poll(() => panelWidth(page)).toBe(400);
  await dragBy(page, 2000);
  await expect.poll(() => width(page)).toBe(1120 - 400 - 360);
  await expect.poll(async () => Math.round((await page.locator("main.main").boundingBox())!.width)).toBeGreaterThanOrEqual(359);
});

test("maximised right panel tracks keyboard and double-click sidebar resizes without clipping or gaps", async ({ page }) => {
  await openApp(page);
  const vw = page.viewportSize()!.width;
  await page.getByTestId("places").click();
  await expect(page.getByTestId("details-panel")).toBeVisible();
  await page.getByTestId("panel-max").click();
  await expect(page.getByTestId("window")).toHaveClass(/panel-max/);
  await expect.poll(() => panelWidth(page)).toBe(vw - 248);

  const handle = page.getByTestId("sidebar-resizer");
  await handle.focus();
  await page.keyboard.press("Shift+ArrowRight");
  await expect.poll(() => width(page)).toBe(312);
  await expect.poll(() => panelWidth(page)).toBe(vw - 312);
  const box = (await page.getByTestId("details").boundingBox())!;
  expect(Math.round(box.x + box.width)).toBe(vw);

  // reload while maximised keeps panel flush with viewport right edge
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await expect.poll(() => width(page)).toBe(312);
  await expect.poll(() => panelWidth(page)).toBe(vw - 312);

  // double-click reset expands maximised panel back with no blank gap
  await handle.dblclick();
  await expect.poll(() => width(page)).toBe(248);
  await expect.poll(() => panelWidth(page)).toBe(vw - 248);
});

test("narrow viewport overlay panel stays clear of a wide sidebar", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 700 });
  await openApp(page);
  await dragBy(page, 2000);
  await expect.poll(() => width(page)).toBe(480);

  await page.getByTestId("places").click();
  await expect(page.getByTestId("details-panel")).toBeVisible();
  await page.getByTestId("panel-tab-diff").click();
  await expect.poll(async () => {
    const sb = (await page.getByTestId("sidebar").boundingBox())!;
    const dt = (await page.getByTestId("details").boundingBox())!;
    return Math.round(dt.x - (sb.x + sb.width));
  }).toBeGreaterThanOrEqual(50);
});

test("resizing the sidebar makes no bridge call", async ({ page }) => {
  await openApp(page);
  await dragBy(page, 80);
  const ops = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(ops.filter((op: string) => /side|width|resize/i.test(op))).toEqual([]);
});
