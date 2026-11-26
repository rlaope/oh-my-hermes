// Dragging the sidebar's right edge resizes it (SidebarResizer.tsx): the width stays after a reload; a double click
// goes back to the usual width (248px); the main column keeps its room; ←/→ on the focused handle step it.
// No bridge call is made for any of it.
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

  await dragBy(page, -140);
  await expect.poll(() => width(page)).toBe(208);
  expect(await saved(page)).toBe("208");

  await page.getByTestId("sidebar-resizer").dblclick();
  await expect.poll(() => width(page)).toBe(248);
  expect(await saved(page)).toBeNull();
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
  await expect.poll(() => width(page)).toBe(180);
});

test("keyboard: ←/→ on the focused handle steps the width, Enter resets it", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("sidebar-resizer").focus();
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => width(page)).toBe(264);
  await page.keyboard.press("Shift+ArrowRight");
  await expect.poll(() => width(page)).toBe(328);
  await page.keyboard.press("ArrowLeft");
  await expect.poll(() => width(page)).toBe(312);
  await page.keyboard.press("Enter");
  await expect.poll(() => width(page)).toBe(248);
});

test("resizing the sidebar makes no bridge call", async ({ page }) => {
  await openApp(page);
  await dragBy(page, 80);
  const ops = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(ops.filter((op: string) => /side|width|resize/i.test(op))).toEqual([]);
});
