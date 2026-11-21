// WebKit is the macOS webview's engine, and it does not focus a <button> on a mouse click (focus lands on the
// card). The question card's digit keys must work after a click there too.
import { expect, test } from "@playwright/test";

test.use({ browserName: "webkit" });

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res) => (ws.onopen = () => res()));
  await new Promise<void>((res) => {
    ws.onmessage = (m) => JSON.parse(String(m.data)).id === "x1" && res();
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("interview in WebKit: click a row, press a digit, the right row is checked", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await mock("mock.ask", { bot: "friren", kind: "interview" });
  await page.getByTestId("needs-strip").click();
  await page.getByTestId("needs-item").first().click();
  const card = page.getByTestId("card-interview");
  await expect(card).toBeVisible();
  const q1 = card.getByRole("radiogroup", { name: "Who is the release note for?" });
  const q2 = card.getByRole("group", { name: "Which sections should it have?" });
  await q1.getByRole("radio", { name: "Users" }).click();
  await page.keyboard.press("2");
  await expect(q1.getByRole("radio", { name: "Developers" })).toHaveAttribute("aria-checked", "true");
  await expect(q1.getByRole("radio", { name: "Users" })).toHaveAttribute("aria-checked", "false");
  await q2.getByRole("checkbox", { name: "Fixes" }).click();
  await page.keyboard.press("4");
  await expect(q2.getByRole("checkbox", { name: "Thanks" })).toHaveAttribute("aria-checked", "true");
  await expect(q1.getByRole("radio", { name: "Developers" })).toHaveAttribute("aria-checked", "true");
});
