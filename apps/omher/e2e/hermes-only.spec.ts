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

type Plan = { exit: number; lines: string[]; hold?: boolean };

/** Hermes without omh (or with it, `omh: true`), and a stand-in installer that plays `plan` and, on a clean exit,
 *  makes `omh` found from then on (the next agents look-up). */
async function open(page: Page, o: { omh?: boolean; plan?: Plan; onboarding?: boolean; lang?: string } = {}) {
  await page.addInitScript(
    ([omh, plan, onb, lang]) => {
      const w = window as unknown as Record<string, unknown>;
      localStorage.removeItem("omher.sessions.recent");
      if (!sessionStorage.getItem("kept")) {
        localStorage.removeItem("omher.omhOffer.hidden");
        sessionStorage.setItem("kept", "1");
      }
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
          if (p.hold) await new Promise(() => {});
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
  await expect
    .poll(async () => (await mock("mock.calls")).calls!.find((c) => c.op === "chat.send" && c.params.session)?.params.text)
    .toBe("What is in this folder?");
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

const LINES = Array.from({ length: 12 }, (_, i) => `step ${i + 1}: fetching part ${i + 1} of the oh-my-hermes wheel`);

/** The rectangles that matter in the sidebar's top row and the popover. */
const rects = (page: Page) =>
  page.evaluate(() => {
    const r = (sel: string) => {
      const e = document.querySelector(sel);
      if (!e) return null;
      const b = e.getBoundingClientRect();
      return { top: b.top, bottom: b.bottom, left: b.left, right: b.right };
    };
    return { icon: r("[data-testid=omh-notice]"), plus: r(".side-add > .ui-ib:last-child"), pop: r("[data-testid=omh-pop]")?.top !== undefined ? r(".omh-pop") : null, h: innerHeight, w: innerWidth };
  });

test("C. Hermes without omh: one quiet ! left of the top row's +, the +'s size, no fill, nothing overlapping", async ({ page }) => {
  await open(page);
  const icon = page.getByTestId("omh-notice");
  await expect(icon).toBeVisible();
  await expect(icon).toHaveAttribute("aria-label", "oh-my-hermes is not installed");
  await expect(icon).toHaveAttribute("title", "oh-my-hermes is not installed");
  const m = await rects(page);
  expect(m.icon && m.plus).toBeTruthy();
  // left of the +, same size, no overlap, same row
  expect(m.icon!.right).toBeLessThanOrEqual(m.plus!.left);
  expect(Math.round(m.icon!.right - m.icon!.left)).toBe(Math.round(m.plus!.right - m.plus!.left));
  expect(Math.round(m.icon!.bottom - m.icon!.top)).toBe(Math.round(m.plus!.bottom - m.plus!.top));
  expect(Math.abs(m.icon!.top - m.plus!.top)).toBeLessThanOrEqual(0.5);
  const look = await icon.evaluate((el) => {
    const cs = getComputedStyle(el);
    const plus = getComputedStyle(document.querySelector(".side-add > .ui-ib:last-child")!);
    return { bg: cs.backgroundColor, border: cs.borderTopWidth, shadow: cs.boxShadow, color: cs.color, plusColor: plus.color, badge: el.querySelectorAll(".badge, [data-count]").length };
  });
  expect(look.bg).toBe("rgba(0, 0, 0, 0)");
  expect(look.border).toBe("0px");
  expect(look.shadow).toBe("none");
  expect(look.color).toBe(look.plusColor);
  expect(look.badge).toBe(0);
});

test("C. with omh there is no ! at all", async ({ page }) => {
  await open(page, { omh: true });
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.waitForTimeout(300);
  await expect(page.getByTestId("omh-notice")).toHaveCount(0);
});

test("C. the popover: title, one sentence, Install and Don't show again; 12-13px text, 4-6px radius", async ({ page }) => {
  await open(page);
  await page.getByTestId("omh-notice").click();
  const pop = page.getByTestId("omh-pop");
  await expect(pop).toBeVisible();
  await expect(pop.locator(".omh-pop-t")).toHaveText("oh-my-hermes");
  await expect(pop).toContainText("plan big jobs in parts");
  await expect(pop).toContainText("Plans");
  await expect(pop).not.toContainText(/dag|delegate_task|omh_/);
  await expect(page.getByTestId("omh-pop-install")).toHaveText("Install");
  await expect(page.getByTestId("omh-pop-hide")).toHaveText("Don't show again");
  const look = await page.locator(".omh-pop").evaluate((el) => {
    const cs = getComputedStyle(el);
    const sizes = [...el.querySelectorAll("p, button, b")].map((e) => parseFloat(getComputedStyle(e).fontSize));
    return { radius: parseFloat(cs.borderTopLeftRadius), sizes };
  });
  expect(look.radius).toBeGreaterThanOrEqual(4);
  expect(look.radius).toBeLessThanOrEqual(6);
  for (const s of look.sizes) {
    expect(s).toBeGreaterThanOrEqual(12);
    expect(s).toBeLessThanOrEqual(13);
  }
  // it covers neither the ! nor the +
  const m = await rects(page);
  for (const b of [m.icon!, m.plus!]) expect(m.pop!.top >= b.bottom || m.pop!.bottom <= b.top).toBe(true);
});

test("C. running: the installer's output in the house style, as tall as its lines, then it scrolls; one run only", async ({ page }) => {
  await open(page, { plan: { exit: 0, lines: ["Installing oh-my-hermes 4.9.2"], hold: true } });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  await expect(page.getByTestId("omh-pop-running")).toContainText("Adding oh-my-hermes");
  await expect(page.getByTestId("omh-pop-install")).toBeDisabled();
  const log = page.getByTestId("omh-pop-log");
  await expect(log).toContainText("Installing oh-my-hermes");
  const look = await log.evaluate((el) => {
    const cs = getComputedStyle(el);
    const probe = document.createElement("div");
    probe.style.background = "var(--raise)";
    document.body.appendChild(probe);
    const raise = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return { bg: cs.backgroundColor, raise, radius: parseFloat(cs.borderTopLeftRadius), size: cs.fontSize, family: cs.fontFamily, sh: el.scrollHeight, ch: el.clientHeight };
  });
  expect(look.bg).not.toBe("rgb(0, 0, 0)");
  expect(look.bg).toBe(look.raise);
  expect(look.radius).toBeGreaterThanOrEqual(4);
  expect(look.radius).toBeLessThanOrEqual(6);
  expect(look.size).toBe("12px");
  expect(look.family).toMatch(/mono|Menlo/i);
  // one line, no dead space under it
  expect(look.sh).toBe(look.ch);
  expect(look.ch).toBeLessThanOrEqual(18 + 12);
  expect(await installs(page)).toBe(1);
});

test("C. a long output stops at five lines and scrolls, the newest line in view", async ({ page }) => {
  await open(page, { plan: { exit: 0, lines: LINES, hold: true } });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  const log = page.getByTestId("omh-pop-log");
  await expect(log).toContainText("step 12");
  const m = await log.evaluate((el) => ({ sh: el.scrollHeight, ch: el.clientHeight, top: el.scrollTop }));
  expect(m.ch).toBeLessThanOrEqual(5 * 18 + 12);
  expect(m.sh).toBeGreaterThan(m.ch);
  expect(m.top + m.ch).toBeGreaterThanOrEqual(m.sh - 1);
});

test("C. done: the ! and its popover go, the + row reads oh-my-hermes and its Add line is gone", async ({ page }) => {
  await open(page, { plan: { exit: 0, lines: ["Installing oh-my-hermes …", "[ok] omh installed"] } });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  await expect(page.getByTestId("omh-notice")).toHaveCount(0);
  await expect(page.getByTestId("omh-pop")).toHaveCount(0);
  expect(await installs(page)).toBe(1);
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-menu").getByTestId("session-agent-omh")).toContainText("oh-my-hermes");
  await expect(page.getByTestId("session-add-omh")).toHaveCount(0);
});

test("C. failed: the last line and Install again, which runs the same installer again", async ({ page }) => {
  await open(page, { plan: { exit: 1, lines: ["Installing oh-my-hermes …", "[failed] could not reach github.com"] } });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  await expect(page.getByTestId("omh-pop-error")).toHaveText("[failed] could not reach github.com");
  await expect(page.getByTestId("omh-pop-install")).toHaveText("Install again");
  await expect(page.getByTestId("omh-notice")).toBeVisible();
  await page.getByTestId("omh-pop-install").click();
  await expect.poll(() => installs(page)).toBe(2);
});

test("C. a silent failure says the exit code", async ({ page }) => {
  await open(page, { plan: { exit: 7, lines: [] } });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  await expect(page.getByTestId("omh-pop-error")).toHaveText("The installer stopped (exit 7).");
});

test("C+D. Don't show again hides the ! (also after a reload); the + menu's line closes the menu and opens the popover again", async ({ page }) => {
  await open(page);
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-hide").click();
  await expect(page.getByTestId("omh-notice")).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.waitForTimeout(300);
  await expect(page.getByTestId("omh-notice")).toHaveCount(0);
  await page.getByTestId("session-new").click();
  const line = page.getByTestId("session-add-omh");
  await expect(line).toHaveText("Add oh-my-hermes");
  await line.click();
  await expect(page.getByTestId("session-menu")).toHaveCount(0);
  await expect(page.getByTestId("omh-notice")).toBeVisible();
  await expect(page.getByTestId("omh-pop")).toBeVisible();
  // the menu prints no output of its own, and nothing was installed by picking the line
  await expect(page.locator("[data-testid=session-add-omh-log]")).toHaveCount(0);
  expect(await installs(page)).toBe(0);
});

test("D. the + menu's line is a quiet borderless row and never runs the installer itself", async ({ page }) => {
  await open(page);
  await page.getByTestId("session-new").click();
  const line = page.getByTestId("session-add-omh");
  const look = await line.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { border: cs.borderTopWidth, bg: cs.backgroundColor, size: parseFloat(cs.fontSize), align: cs.textAlign };
  });
  expect(look.border).toBe("0px");
  expect(look.bg).toBe("rgba(0, 0, 0, 0)");
  expect(look.size).toBeGreaterThanOrEqual(12);
  expect(look.size).toBeLessThanOrEqual(13);
  expect(look.align).toBe("left");
  await line.click();
  await expect(page.getByTestId("omh-pop")).toBeVisible();
  expect(await installs(page)).toBe(0);
});

for (const height of [600, 720, 820]) {
  test(`C. the popover with a long output stays inside a ${height}px window with air at both ends`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height });
    await open(page, { plan: { exit: 1, lines: [...LINES, "[failed] could not reach github.com (curl: (6)) after three tries"] } });
    await page.getByTestId("omh-notice").click();
    await page.getByTestId("omh-pop-install").click();
    await expect(page.getByTestId("omh-pop-install")).toHaveText("Install again");
    await page.waitForTimeout(250);
    const m = await rects(page);
    expect(m.pop!.top).toBeGreaterThanOrEqual(4);
    expect(m.pop!.bottom).toBeLessThanOrEqual(m.h - 4);
    expect(m.pop!.left).toBeGreaterThanOrEqual(4);
    expect(m.pop!.right).toBeLessThanOrEqual(m.w - 4);
  });
}

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

for (const [lang, line, row, tip] of [
  ["ko", "oh-my-hermes 추가", "Hermes", "oh-my-hermes가 설치되어 있지 않아요"],
  ["ja", "oh-my-hermes を追加", "Hermes", "oh-my-hermes がインストールされていません"],
  ["zh", "添加 oh-my-hermes", "Hermes", "未安装 oh-my-hermes"],
] as const) {
  test(`6. the new line in ${lang}`, async ({ page }) => {
    await open(page, { lang });
    await page.getByTestId("session-new").click();
    await expect(page.getByTestId("session-add-omh")).toHaveText(line);
    await expect(page.getByTestId("session-agent-omh")).toContainText(row);
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("omh-notice")).toHaveAttribute("aria-label", tip);
  });
}
