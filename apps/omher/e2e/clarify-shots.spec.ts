// Screenshots of the clarify card (one question) and the interview card (several), light and dark, with long
// Korean choices. They stay out of the repo (CLARIFY_SHOTS dir, else Playwright's ignored test-results).
import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.CLARIFY_SHOTS || "test-results";
const TAG = process.env.CLARIFY_TAG || "after";

const LONG = [
  "Slack 실패 스레드에 남기기 — 원인 요약(11-19부터 같은 모델 실패, #1188 무관)을 #deploy-common 스레드에 카미가 답글로 (Recommended)",
  "재시도 — 같은 모델로 한 번 더 돌려 보고 결과만 알려 주기",
  "건너뛰기",
  "이슈로 등록 — 담당자 없이 백로그에 올리기 (권장)",
];

async function setup(page: Page, rewrite: (msg: any) => void, kind: string, theme: "light" | "dark") {
  await page.routeWebSocket(new RegExp(`127\\.0\\.0\\.1:${MOCK}`), (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((m) => server.send(m));
    server.onMessage((m) => {
      const msg = JSON.parse(String(m));
      if (msg.event === "clarify.request") rewrite(msg);
      ws.send(JSON.stringify(msg));
    });
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.evaluate(async (th) => {
    const m = await import(/* @vite-ignore */ "/src/state/store.ts");
    m.getStore().actions.setTheme(th as "light" | "dark");
  }, theme);
  if (kind === "interview") {
    // asked by the mock bridge on another bot, opened from the Needs-you strip
    await page.evaluate(async (port) => {
      const ws = new WebSocket(`ws://127.0.0.1:${port}/?token=e2e`);
      await new Promise<void>((res) => (ws.onopen = () => res()));
      await new Promise<void>((res) => {
        ws.onmessage = () => res();
        ws.send(JSON.stringify({ id: "x1", op: "mock.ask", bot: "friren", kind: "interview" }));
      });
      ws.close();
    }, MOCK);
    await page.getByTestId("needs-strip").click();
    await page.getByTestId("needs-item").first().click();
    return;
  }
  const c = page.getByTestId("composer");
  await c.fill("/clarify");
  await c.press("Enter");
}

// the mock bridge keeps pending asks between tests
test.beforeEach(async () => {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res) => (ws.onopen = () => res()));
  await new Promise<void>((res) => {
    ws.onmessage = (m) => JSON.parse(String(m.data)).id === "x1" && res();
    ws.send(JSON.stringify({ id: "x1", op: "mock.reset" }));
  });
  ws.close();
});

for (const theme of ["dark", "light"] as const) {
  test(`shot: one question, ${theme}`, async ({ page }) => {
    await setup(page, (m) => { m.question = "실패한 배포 건을 어떻게 처리할까요?"; m.choices = LONG; }, "clarify", theme);
    const card = page.getByTestId("card-clarify");
    await expect(card).toBeVisible();
    await card.scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(SHOTS, `clarify-single-${theme}-${TAG}.png`), animations: "disabled" });
  });

  test(`shot: interview, ${theme}`, async ({ page }) => {
    await setup(page, (m) => {
      if (!m.questions) return; // the mock's own socket sees the broadcast too
      m.questions[0].question = "실패한 배포 건을 어떻게 처리할까요?";
      m.questions[0].choices = LONG;
    }, "interview", theme);
    const card = page.getByTestId("card-interview");
    await expect(card).toBeVisible();
    await card.scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(SHOTS, `clarify-interview-${theme}-${TAG}.png`), animations: "disabled" });
  });
}
