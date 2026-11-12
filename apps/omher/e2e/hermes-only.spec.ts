// A person who has Hermes but not oh-my-hermes (`omh`). The mock host reports that with `__omherMockNoOmh` (the
// shell's `via: "hermes"` row); `__OMHER_GATE__` stands in for the shell's one fixed installer, so nothing installs.
// One test per item of the brief: (1) the + row reads Hermes and opens a Hermes chat in the folder on the bot in view,
// (2) with `omh` nothing changes, (3) that session has no dead Terminal toggle, (4) one quiet "Add oh-my-hermes" line
// runs the same installer and the row then reads oh-my-hermes, (4a) a third first-run card recommends it,
// (5) Plans says what is missing in plain words, (6) the new strings come in every language.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string, params: Record<string, unknown> = {}): Promise<{ calls?: { op: string; params: Record<string, unknown> }[] }> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<{ result: unknown }>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "h1") res(msg);
    };
    ws.send(JSON.stringify({ id: "h1", op, ...params }));
  });
  ws.close();
  return reply.result as { calls?: { op: string; params: Record<string, unknown> }[] };
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

type Plan = { exit: number; lines: string[] };

/** Hermes without omh (or with it, `omh: true`), and a stand-in installer that plays `plan` and, on a clean exit,
 *  makes `omh` found from then on (the next agents look-up). */
async function open(page: Page, o: { omh?: boolean; plan?: Plan; onboarding?: boolean; lang?: string } = {}) {
  await page.addInitScript(
    ([omh, plan, onb, lang]) => {
      const w = window as unknown as Record<string, unknown>;
      localStorage.removeItem("omher.sessions.recent");
      if (onb) localStorage.removeItem("omher.onboarded");
      if (lang) localStorage.setItem("omher.lang", lang as string);
      w.__omherPickFolder = "/Users/you/code/web-app";
      w.__omherMockAgents = ["claude", "codex", ...(omh ? ["omh"] : [])];
      w.__omherMockNoOmh = !omh;
      const calls: string[] = [];
      w.__installCalls = calls;
      const p = plan as Plan;
      w.__OMHER_GATE__ = {
        status: async () => ({ state: "ready" }),
        retry: async () => {},
        installCommand: async () => "",
        install: async (onEvent: (e: unknown) => void) => {
          calls.push("install");
          for (const text of p.lines) {
            onEvent({ kind: "line", text });
            await new Promise((r) => setTimeout(r, 30));
          }
          await new Promise((r) => setTimeout(r, 300));
          onEvent({ kind: "exit", code: p.exit });
          if (p.exit === 0) {
            w.__omherMockNoOmh = false;
            (w.__omherMockAgents as string[]).push("omh");
          }
          return p.exit;
        },
      };
    },
    [!!o.omh, o.plan ?? { exit: 0, lines: ["[ok] omh installed"] }, !!o.onboarding, o.lang ?? ""] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

const installs = (page: Page) => page.evaluate(() => ((window as unknown as { __installCalls: string[] }).__installCalls ?? []).length);

test("1. Hermes without omh: the + row reads Hermes with Hermes' mark and opens a Hermes chat in the folder, on the bot in view", async ({ page }) => {
  await open(page);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("session-new").click();
  const row = page.getByTestId("session-menu").getByTestId("session-agent-omh");
  await expect(row).toContainText("Hermes");
  await expect(row).not.toContainText("oh-my-hermes");
  await expect(row).not.toHaveAttribute("aria-disabled", "true");
  await expect(row).not.toContainText("Not installed");
  await expect(row.locator('[data-mark="hermes"]')).toHaveCount(1);
  await row.click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("What is in this folder?");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-agent")).toHaveText("Hermes");
  await expect(page.getByTestId("session-cwd")).toHaveText("~/code/web-app");
  const opened = (await mock("mock.calls")).calls!.find((c) => c.op === "folder.open")!;
  expect(opened.params).toMatchObject({ bot: "friren", cwd: "/Users/you/code/web-app" });
  const sent = (await mock("mock.calls")).calls!.find((c) => c.op === "chat.send" && c.params.session);
  expect(sent?.params.text).toBe("What is in this folder?");
  await expect(page.getByTestId("session-list").getByTestId("session-sub").first()).toContainText("Hermes");
});

test("2. Hermes and omh: the row reads oh-my-hermes as before, and nothing offers to add it", async ({ page }) => {
  await open(page, { omh: true });
  await page.getByTestId("session-new").click();
  const row = page.getByTestId("session-menu").getByTestId("session-agent-omh");
  await expect(row).toContainText("oh-my-hermes");
  await expect(row.locator('[data-mark="omh"]')).toHaveCount(1);
  await expect(page.getByTestId("session-add-omh")).toHaveCount(0);
});

test("3. a Hermes session without omh has no Terminal toggle (it would start omh); its model and panel stay", async ({ page }) => {
  await open(page);
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-omh").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("hello");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-agent")).toHaveText("Hermes");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("session-terminal-toggle")).toHaveCount(0);
  await expect(page.getByTestId("head-right").getByTestId("panel-button")).toBeVisible();
  // no terminal was ever started for it
  const ops = await page.evaluate(() => ((window as unknown as { __omherSessionCalls?: { op: string }[] }).__omherSessionCalls ?? []).map((c) => c.op));
  expect(ops).not.toContain("start");
});

test("3b. with omh the same session keeps its Terminal toggle", async ({ page }) => {
  await open(page, { omh: true });
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-omh").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("hello");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-agent")).toHaveText("oh-my-hermes");
  await expect(page.getByTestId("session-terminal-toggle")).toBeVisible();
});

test("4. one quiet line offers oh-my-hermes, runs the same installer once, shows its output, and the row then reads oh-my-hermes", async ({ page }) => {
  await open(page, { plan: { exit: 0, lines: ["[ok] Hermes Agent found", "Installing oh-my-hermes …", "[ok] omh installed"] } });
  await page.getByTestId("session-new").click();
  const line = page.getByTestId("session-add-omh");
  await expect(line).toHaveText("Add oh-my-hermes");
  // a borderless left-aligned row, 12-13px, no fill at rest
  const look = await line.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { border: cs.borderTopWidth, bg: cs.backgroundColor, size: parseFloat(cs.fontSize), align: cs.textAlign, radius: parseFloat(cs.borderTopLeftRadius) };
  });
  expect(look.border).toBe("0px");
  expect(look.bg).toBe("rgba(0, 0, 0, 0)");
  expect(look.size).toBeGreaterThanOrEqual(12);
  expect(look.size).toBeLessThanOrEqual(13);
  expect(look.align).toBe("left");
  expect(look.radius).toBeGreaterThanOrEqual(4);
  expect(look.radius).toBeLessThanOrEqual(6);
  await line.click();
  await line.click(); // a second press while it runs starts nothing
  await expect(page.getByTestId("session-add-omh-log")).toContainText("Installing oh-my-hermes");
  await expect(line).toContainText("Adding oh-my-hermes");
  await expect(page.getByTestId("session-add-omh")).toHaveCount(0);
  expect(await installs(page)).toBe(1);
  await expect(page.getByTestId("session-menu").getByTestId("session-agent-omh")).toContainText("oh-my-hermes");
});

test("4. a failed run keeps the line with the installer's last line and Install again", async ({ page }) => {
  await open(page, { plan: { exit: 1, lines: ["Installing oh-my-hermes …", "[failed] could not reach github.com"] } });
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-add-omh").click();
  await expect(page.getByTestId("session-add-omh-error")).toHaveText("[failed] could not reach github.com");
  await expect(page.getByTestId("session-add-omh")).toHaveText("Install again");
  await expect(page.getByTestId("session-menu").getByTestId("session-agent-omh")).toContainText("Hermes");
  await page.getByTestId("session-add-omh").click();
  await expect.poll(() => installs(page)).toBe(2);
});

test("4a. first run: a third card recommends oh-my-hermes and installs it; with omh only two cards", async ({ page }) => {
  await mock("mock.clearHistory", { bot: "friren" });
  await open(page, { onboarding: true, plan: { exit: 0, lines: ["Installing oh-my-hermes …", "[ok] omh installed"] } });
  await page.getByTestId("bot-friren").click();
  const onb = page.getByTestId("onboarding");
  await expect(onb).toBeVisible();
  await expect(onb.locator(".onb-card")).toHaveCount(3);
  const card = page.getByTestId("onb-omh");
  await expect(card).toContainText("oh-my-hermes");
  await expect(card.getByTestId("onb-omh-rec")).toHaveText("Recommended");
  await expect(card).toContainText("plan big jobs in parts");
  await expect(card).not.toContainText(/dag|delegate_task|omh_/);
  await card.getByTestId("onb-omh-install").click();
  await expect(card.getByTestId("onb-omh-log")).toContainText("Installing oh-my-hermes");
  await expect(card.getByTestId("onb-omh-install")).toBeDisabled();
  await expect(page.getByTestId("onb-omh")).toHaveCount(0);
  await expect(onb.locator(".onb-card")).toHaveCount(2);
  expect(await installs(page)).toBe(1);
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-menu").getByTestId("session-agent-omh")).toContainText("oh-my-hermes");
});

test("4a. a failed card keeps its last line and Install again; the × leaves the + line as the way back", async ({ page }) => {
  await mock("mock.clearHistory", { bot: "friren" });
  await open(page, { onboarding: true, plan: { exit: 7, lines: [] } });
  await page.getByTestId("bot-friren").click();
  const card = page.getByTestId("onb-omh");
  await card.getByTestId("onb-omh-install").click();
  await expect(card.getByTestId("onb-omh-error")).toHaveText("The installer stopped (exit 7).");
  await expect(card.getByTestId("onb-omh-install")).toHaveText("Install again");
  await page.getByTestId("onb-dismiss").click();
  await expect(page.getByTestId("onboarding")).toHaveCount(0);
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-add-omh")).toHaveText("Install again");
});

test("4a. with omh the first run is the two cards it always was", async ({ page }) => {
  await mock("mock.clearHistory", { bot: "friren" });
  await open(page, { omh: true, onboarding: true });
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("onboarding").locator(".onb-card")).toHaveCount(2);
  await expect(page.getByTestId("onb-omh")).toHaveCount(0);
});

test("5. Plans without omh: the plain empty state says what adds plans, no error and no spinner", async ({ page }) => {
  await open(page);
  await page.getByTestId("bot-friren").click();
  await page.getByTestId("panel-button").click();
  const empty = page.getByTestId("plans-empty");
  await expect(empty).toContainText("No plans yet.");
  await expect(page.getByTestId("plans-none-how")).toHaveText(/oh-my-hermes, which isn't on this computer/);
  await expect(page.getByTestId("plans-none-how")).not.toContainText("dag ulw");
  await expect(page.getByTestId("panel-runs").locator(".pn-empty.bad, .ui-spin")).toHaveCount(0);
});

for (const [lang, line, row] of [
  ["ko", "oh-my-hermes 추가", "Hermes"],
  ["ja", "oh-my-hermes を追加", "Hermes"],
  ["zh", "添加 oh-my-hermes", "Hermes"],
] as const) {
  test(`6. the new line in ${lang}`, async ({ page }) => {
    await open(page, { lang });
    await page.getByTestId("session-new").click();
    await expect(page.getByTestId("session-add-omh")).toHaveText(line);
    await expect(page.getByTestId("session-agent-omh")).toContainText(row);
  });
}
