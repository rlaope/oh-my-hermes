// Shots of a message sent while the bot answers (ko, dark/light, 1280x820, Retina): BUSY_SEND_SHOTS=<dir>.
// `steer`: the default, steered in at once (a plain sent bubble, Read beside it, the live dots under it).
// `refused`: Hermes refused the steer, so it waits with its ↵ ↓ × buttons and no text line.
import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const DIR = process.env.BUSY_SEND_SHOTS || "";
const TAG = process.env.BUSY_SEND_TAG || "after";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const out = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  return out.result;
}

test.describe("busy send shots", () => {
  test.use({ deviceScaleFactor: 2, viewport: { width: 1280, height: 820 } });
  for (const mode of ["steer", "refused"] as const) {
    for (const theme of ["dark", "light"] as const) {
      test(`shot busy-send-${mode}-ko-${theme}`, async ({ page }) => {
        test.skip(!DIR, "BUSY_SEND_SHOTS not set");
        mkdirSync(DIR, { recursive: true });
        await mock("mock.reset");
        await mock("mock.manual", { bot: "kami" });
        if (mode === "refused") await mock("mock.steerMode", { bot: "kami", mode: "reject" });
        await page.addInitScript(([t]) => {
          localStorage.setItem("omher.theme", t);
          localStorage.setItem("omher.lang", "ko");
        }, [theme]);
        await page.goto("/");
        await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
        await expect(page.getByTestId("bubble-user").first()).toBeVisible();
        const say = async (text: string) => {
          await page.getByTestId("composer").fill(text);
          await page.getByTestId("composer").press("Enter");
        };
        await say("게이트웨이 재시도 코드 리팩터링해줘");
        await expect(page.getByTestId("stop")).toBeVisible();
        await mock("mock.emit", { events: [
          { event: "tool.start", bot: "kami", tool_id: "bs1", name: "read_file", detail: "gateway/retry.py" },
        ] });
        await say("기존 타임아웃 값은 그대로 둬");
        // steered (or refused), or held without a steer (origin/main's default, for the before shots)
        await expect
          .poll(async () => ((await mock("mock.calls")).calls as { op: string }[]).some((c) => c.op === "chat.steer") || (await page.locator("[data-held]").count()) > 0)
          .toBe(true);
        await page.waitForTimeout(500);
        await page.mouse.move(640, 60);
        await page.evaluate(() => {
          for (const a of document.getAnimations()) {
            const name = (a as CSSAnimation).animationName ?? "";
            a.pause();
            if (name === "ui-typing-hop") a.currentTime = 300;
          }
        });
        await page.screenshot({ path: join(DIR, `busy-send-${TAG}-${mode}-ko-${theme}.png`) });
      });
    }
  }
});
