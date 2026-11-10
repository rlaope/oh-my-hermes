// Bot mentions: `@name` of a known bot in a chat opens that bot's chat (click, Enter, Space) and moves the sidebar
// selection; it never sends. The open chat's own bot is not a link, and unknown names stay text.
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
      if (msg.id === "mn1") res(msg);
    };
    ws.send(JSON.stringify({ id: "mn1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

const sends = async () => (await mock("mock.calls")).calls.filter((c: any) => c.op === "chat.send").length;

async function openKami(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  const bubble = page.getByTestId("bubble-bot").filter({ hasText: "keep-alive 문서는" });
  await expect(bubble).toBeVisible();
  return bubble;
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a mention in a bot bubble opens that bot's chat and moves the sidebar selection", async ({ page }) => {
  const bubble = await openKami(page);
  const m = bubble.getByTestId("mention");
  await expect(m).toHaveText(["@friren", "@hermes", "@omh-tui", "@kami"]);
  await expect(bubble.locator('[data-bot="default"]')).toHaveAttribute("title", "Open Hermes");

  // ink, weight 500, no pill
  const look = await m.first().evaluate((el) => {
    const s = getComputedStyle(el);
    return { weight: s.fontWeight, bg: s.backgroundColor, cursor: s.cursor };
  });
  expect(look).toEqual({ weight: "500", bg: "rgba(0, 0, 0, 0)", cursor: "pointer" });

  const before = await sends();
  await bubble.locator('[data-bot="friren"]').click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bot-kami")).not.toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("timeline")).toContainText("The updater checks a signed manifest");
  expect(await sends()).toBe(before);
});

test("Enter and Space on a focused mention open the chat; the composer sends nothing", async ({ page }) => {
  const bubble = await openKami(page);
  const before = await sends();
  await page.getByTestId("composer").fill("draft stays");
  const hermes = bubble.locator('[data-bot="default"]');
  await hermes.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bot-default")).toHaveAttribute("aria-current", "true");

  await page.getByTestId("bot-kami").click();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("bubble-bot").filter({ hasText: "keep-alive 문서는" }).locator('[data-bot="omh-tui"]').focus();
  await page.keyboard.press("Space");
  await expect(page.getByTestId("bot-omh-tui")).toHaveAttribute("aria-current", "true");
  expect(await sends()).toBe(before);
});

test("the open chat's own bot is not a link; unknown names and code stay text", async ({ page }) => {
  const bubble = await openKami(page);
  const self = bubble.locator('[data-bot="kami"]');
  await expect(self).toHaveClass(/self/);
  await expect(self).not.toHaveAttribute("tabindex", /.*/);
  await self.click();
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");

  await mock("mock.emit", {
    events: [{ event: "message", bot: "kami", id: "mn-unknown", text: "Ask @foo, mail kami@friren.dev, run `@friren`, or @file:notes.md." }],
  });
  const last = page.getByTestId("bubble-bot").filter({ hasText: "Ask @foo" });
  await expect(last).toBeVisible();
  await expect(last.getByTestId("mention")).toHaveCount(0);
});

test("mentions in your own bubble open the chat too", async ({ page }) => {
  await openKami(page);
  await page.getByTestId("composer").fill("@friren 이거 같이 봐줘");
  await page.getByTestId("composer").press("Enter");
  const mine = page.getByTestId("bubble-user").filter({ hasText: "이거 같이 봐줘" });
  await expect(mine.getByTestId("mention")).toHaveText("@friren");
  await mine.getByTestId("mention").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
});
