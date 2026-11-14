// After omher's own installer ends well, the app shows a bot's chat with ONE quiet line above the composer that puts
// the model-setup request in the composer (nothing is sent), once only. The mock host plays "Hermes, no omh"
// (`__omherMockNoOmh`); `__OMHER_GATE__` stands in for the shell's fixed installer (nothing installs); `mock.skills`
// adds oh-my-hermes' skills to `skills.list` the way the installer's `skills.external_dirs` entry does; and
// `__omherPromptDelays` shortens the minute of re-reads. With OMHER_SHOTS set, each case also saves its shot before
// its first assertion (OMHER_SHOT_TAG=before|after), so the same spec on the old tree writes the before shots.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<{ calls?: { op: string; params: Record<string, unknown> }[] }> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<{ result: unknown }>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "p1") res(msg);
    };
    ws.send(JSON.stringify({ id: "p1", op, ...params }));
  });
  ws.close();
  return reply.result as { calls?: { op: string; params: Record<string, unknown> }[] };
}

const MODEL_SETUP = { name: "omh-model-setup", description: "[omh] Model and provider configuration changes" };
const ASK = {
  en: "Set up my models from the providers this computer already has. Show me what will change before you apply anything.",
  ko: "이 컴퓨터에 이미 있는 프로바이더로 내 모델을 설정해 줘. 적용하기 전에 무엇이 바뀌는지 먼저 보여 줘.",
  ja: "このコンピューターにすでにあるプロバイダーで、私のモデルを設定して。適用する前に、何が変わるかを先に見せて。",
  zh: "用这台电脑上已有的提供商帮我设置模型。应用任何更改之前，先告诉我会改动什么。",
} as const;
const READY = {
  en: "oh-my-hermes is ready. Set up your models?",
  ko: "oh-my-hermes가 준비됐어요. 모델을 설정할까요?",
  ja: "oh-my-hermes の準備ができました。モデルを設定しますか？",
  zh: "oh-my-hermes 已就绪。要设置模型吗？",
} as const;
const NO_SKILLS = {
  en: "Kami does not list oh-my-hermes' skills yet.",
  ko: "Kami 봇에는 아직 oh-my-hermes 스킬이 보이지 않아요.",
  ja: "Kami にはまだ oh-my-hermes のスキルが見えません。",
  zh: "Kami 还没有列出 oh-my-hermes 的技能。",
} as const;
const TOOLS = {
  en: "Friren does not have oh-my-hermes' tools yet (subagent plans and the rest). Model setup works without them.",
} as const;
type Lang = keyof typeof ASK;

test.beforeEach(async () => {
  await mock("mock.reset");
});

/** One shot per case: the "before" run (the old tree) takes it right after the install, where the old app shows no
 *  line; the "after" run takes it where the feature is on screen. */
async function shot(page: Page, name: string, theme: string, at: "before" | "after") {
  if (!SHOTS || at !== TAG) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `omh-first-prompt-${name}-${TAG}-${theme}.png`) });
}

type Open = { omh?: boolean; lang?: Lang; theme?: string; gate?: "ready" | "missing" };

/** Hermes without omh (or with it), a stand-in installer that ends well and makes `omh` found from then on, and the
 *  first-run screen's "Hermes is missing" when `gate: "missing"`. Storage is cleared once per test, not on reload. */
async function open(page: Page, o: Open = {}) {
  await page.addInitScript(
    ([omh, lang, theme, gate]) => {
      const w = window as unknown as Record<string, unknown>;
      if (!sessionStorage.getItem("e2e.started")) {
        localStorage.removeItem("omher.omhPrompt");
        localStorage.removeItem("omher.sessions.recent");
        localStorage.removeItem("omher.resume");
        if (lang) localStorage.setItem("omher.lang", lang as string);
        if (theme) localStorage.setItem("omher.theme", theme as string);
        sessionStorage.setItem("e2e.started", "1");
      }
      w.__omherPromptDelays = [0, 150, 150, 150];
      w.__omherMockAgents = ["claude", "codex", ...(omh ? ["omh"] : [])];
      w.__omherMockNoOmh = !omh;
      let hermes = gate !== "missing";
      const calls: string[] = [];
      w.__installCalls = calls;
      w.__OMHER_GATE__ = {
        status: async () => (hermes ? { state: "ready" } : { state: "failed", error: "Hermes not found", missing: "hermes" }),
        retry: async () => {},
        installCommand: async () => "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh -s -- omher@beta",
        install: async (onEvent: (e: unknown) => void) => {
          calls.push("install");
          for (const text of ["[ok] Hermes Agent found", "[ok] omh installed to ~/.local/bin/omh", "[ok] OMH doctor: ok"]) {
            onEvent({ kind: "line", text });
            await new Promise((r) => setTimeout(r, 30));
          }
          onEvent({ kind: "exit", code: 0 });
          hermes = true;
          w.__omherMockNoOmh = false;
          (w.__omherMockAgents as string[]).push("omh");
          return 0;
        },
      };
    },
    [!!o.omh, o.lang ?? "", o.theme ?? "", o.gate ?? "ready"] as const,
  );
  await page.goto("/");
  if (o.gate !== "missing") await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** The installer run from the sidebar's "!" popover; `skills` is what the bot's skills.list gains. */
async function installFromPopover(page: Page, skills: "now" | "never" = "now") {
  if (skills === "now") await mock("mock.skills", { add: [MODEL_SETUP] });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  await expect(page.getByTestId("omh-notice")).toHaveCount(0);
}

const sends = async () => (await mock("mock.calls")).calls!.filter((c) => c.op === "chat.send" || c.op === "chat.attach");

/** The line's box against the composer's and the thread's last message: no overlap, all on screen. */
const geometry = (page: Page) =>
  page.evaluate(() => {
    const box = (e: Element | null) => {
      if (!e) return null;
      const b = e.getBoundingClientRect();
      return { top: b.top, bottom: b.bottom, left: b.left, right: b.right };
    };
    const line = document.querySelector("[data-testid=omh-prompt], [data-testid=omh-prompt-restart]");
    const thread = document.querySelector<HTMLElement>(".thread")!;
    const rows = [...thread.querySelectorAll(".row")];
    const last = rows.at(-1) ?? null;
    const cs = line ? getComputedStyle(line) : null;
    return {
      line: box(line),
      composer: box(document.querySelector("[data-testid=composer-box]")),
      thread: box(thread),
      last: box(last),
      atEnd: thread.scrollHeight - thread.scrollTop - thread.clientHeight < 2,
      fontSize: cs ? parseFloat(cs.fontSize) : 0,
      bg: cs?.backgroundColor,
      border: cs?.borderTopWidth,
      shadow: cs?.boxShadow,
      w: innerWidth,
      scrollW: document.documentElement.scrollWidth,
    };
  });

function noOverlap(g: Awaited<ReturnType<typeof geometry>>) {
  expect(g.line).toBeTruthy();
  // in the flow, between the thread and the composer: above the composer, below the thread's visible box
  expect(g.line!.bottom).toBeLessThanOrEqual(g.composer!.top + 0.5);
  expect(g.line!.top).toBeGreaterThanOrEqual(g.thread!.bottom - 0.5);
  // the last message is fully inside the thread's box (the thread sits at its end)
  expect(g.atEnd).toBe(true);
  expect(g.last!.bottom).toBeLessThanOrEqual(g.thread!.bottom + 0.5);
  // the line's width follows the composer's column, on screen, no page scroll
  expect(g.line!.left).toBeGreaterThanOrEqual(g.composer!.left - 0.5);
  expect(g.line!.right).toBeLessThanOrEqual(g.composer!.right + 0.5);
  expect(g.scrollW).toBeLessThanOrEqual(g.w);
}

for (const theme of ["dark", "light"]) {
  test(`the popover's install ends well: the chat of the bot in view and one quiet line (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width: 1180, height: 760 });
    await open(page, { theme });
    await page.getByTestId("bot-friren").click();
    await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
    // the person went to Settings before installing: the chat comes back
    await page.getByTestId("nav-settings").click();
    await expect(page.getByTestId("settings")).toBeVisible();
    // Friren's gateway was running during the install: it has the skills, not yet the plugin's tools
    await mock("mock.omhUnloaded", { bot: "friren" });
    await installFromPopover(page);
    await page.waitForTimeout(400);
    await shot(page, "line", theme, "before");
    const line = page.getByTestId("omh-prompt");
    await expect(line).toBeVisible();
    await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
    await expect(page.getByTestId("composer")).toBeVisible();
    await shot(page, "line", theme, "after");
    await expect(line).toContainText(READY.en);
    await expect(page.getByTestId("omh-prompt-fill")).toHaveText("Put it in the message box");
    const tools = page.getByTestId("omh-prompt-tools");
    await expect(tools.locator(".omhp-t")).toHaveText(TOOLS.en);
    // slot 14's action beside it: Hermes' reload-plugins, never one bot's restart (that loads no new plugin)
    await expect(tools.getByTestId("omh-load-now")).toHaveText("Load now");
    await expect(tools).not.toContainText("restart");
    await expect(tools.locator("code")).toHaveCount(0);
    const sub = await tools.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const a = document.querySelector("[data-testid=omh-prompt]")!.getBoundingClientRect();
      const c = document.querySelector("[data-testid=composer-box]")!.getBoundingClientRect();
      return { size: parseFloat(getComputedStyle(el).fontSize), under: r.top >= a.bottom - 0.5, above: r.bottom <= c.top + 0.5 };
    });
    expect(sub).toEqual({ size: 12.5, under: true, above: true });
    const g = await geometry(page);
    expect(g.fontSize).toBeGreaterThanOrEqual(12);
    expect(g.fontSize).toBeLessThanOrEqual(13);
    expect(g.bg).toBe("rgba(0, 0, 0, 0)");
    expect(g.border).toBe("0px");
    expect(g.shadow).toBe("none");
    noOverlap(g);
    const look = await page.getByTestId("omh-prompt-fill").evaluate((el) => {
      const cs = getComputedStyle(el);
      return { bg: cs.backgroundColor, border: cs.borderTopWidth, radius: parseFloat(cs.borderTopLeftRadius), size: parseFloat(cs.fontSize) };
    });
    expect(look).toMatchObject({ bg: "rgba(0, 0, 0, 0)", border: "0px" });
    expect(look.radius).toBeGreaterThanOrEqual(4);
    expect(look.radius).toBeLessThanOrEqual(6);
    expect(look.size).toBeLessThanOrEqual(13);
  });

  test(`the action puts the prompt in the composer, focused; nothing is sent; the line goes (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width: 1180, height: 760 });
    await open(page, { theme });
    await installFromPopover(page);
    await page.waitForTimeout(400);
    await shot(page, "filled", theme, "before");
    await expect(page.getByTestId("omh-prompt")).toBeVisible();
    const before = (await sends()).length;
    await page.getByTestId("omh-prompt-fill").click();
    const box = page.getByTestId("composer");
    await expect(box).toHaveValue(`/omh-model-setup ${ASK.en}`);
    await expect(box).toBeFocused();
    await expect(page.getByTestId("omh-prompt")).toHaveCount(0);
    await shot(page, "filled", theme, "after");
    await page.waitForTimeout(400);
    expect((await sends()).length).toBe(before);
    // the person may edit before sending: the text is theirs
    await box.press("End");
    await box.type(" Only Claude.");
    await expect(box).toHaveValue(`/omh-model-setup ${ASK.en} Only Claude.`);
    expect((await sends()).length).toBe(before);
  });

  test(`a bot whose skills never show the command: one quiet line says so, naming no command (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width: 1180, height: 760 });
    await open(page, { theme });
    await installFromPopover(page, "never");
    await page.waitForTimeout(1000);
    await shot(page, "restart", theme, "before");
    const line = page.getByTestId("omh-prompt-restart");
    await expect(line).toBeVisible();
    await shot(page, "restart", theme, "after");
    await expect(line.locator(".omhp-t")).toHaveText(NO_SKILLS.en);
    await expect(line.getByTestId("omh-load-now")).toHaveText("Load now");
    await expect(line.locator("code")).toHaveCount(0);
    await expect(page.getByTestId("omh-prompt")).toHaveCount(0);
    noOverlap(await geometry(page));
    const ops = (await mock("mock.calls")).calls!.map((c) => c.op);
    expect(ops.filter((o) => o === "skills.list").length).toBeGreaterThanOrEqual(4); // asked again, not once
    expect(ops.some((o) => /restart|gateway|setup/.test(o))).toBe(false); // omher restarts nothing
    expect((await sends()).length).toBe(0);
  });
}

test("a bot whose gateway loaded oh-my-hermes' plugin gets no restart line; one that did not keeps it after the action", async ({ page }) => {
  await open(page);
  await installFromPopover(page);
  await expect(page.getByTestId("omh-prompt")).toBeVisible();
  await page.waitForTimeout(300);
  await expect(page.getByTestId("omh-prompt-tools")).toHaveCount(0); // kami's mock plugin row has its tools

  await mock("mock.reset");
  await page.evaluate(() => sessionStorage.clear());
  await mock("mock.omhUnloaded", { bot: "kami" });
  await page.reload();
  await expect(page.getByTestId("omh-notice")).toBeVisible();
  await installFromPopover(page);
  await expect(page.getByTestId("omh-prompt-tools")).toBeVisible();
  await page.getByTestId("omh-prompt-fill").click();
  await expect(page.getByTestId("composer")).toHaveValue(`/omh-model-setup ${ASK.en}`);
  await expect(page.getByTestId("omh-prompt")).toHaveCount(0);
  const rest = page.getByTestId("omh-prompt-restart");
  await expect(rest.locator(".omhp-t")).toHaveText(TOOLS.en.replace("Friren", "Kami"));
  expect((await sends()).length).toBe(0);
  const ops = (await mock("mock.calls")).calls!.map((c) => c.op);
  expect(ops).toContain("plugins.list"); // the running gateway's own record was asked
  expect(ops.some((o) => /restart|gateway|setup|toggle|install/.test(o))).toBe(false);
  await page.getByTestId("omh-prompt-close").click();
  await expect(rest).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.waitForTimeout(600);
  await expect(page.locator("[data-testid^=omh-prompt]")).toHaveCount(0);
});

test("skills that arrive a little after the install still bring the line (asked again)", async ({ page }) => {
  await open(page);
  await mock("mock.skills", { add: [MODEL_SETUP], after: 2 });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  await expect(page.getByTestId("omh-prompt")).toBeVisible();
  await expect(page.getByTestId("omh-prompt-restart")).toHaveCount(0);
});

test("the command is the one skills.list names, never a guess", async ({ page }) => {
  await open(page);
  await mock("mock.skills", { add: [{ name: "model-setup", description: "a bot with OMH's skill under another name" }] });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  await page.getByTestId("omh-prompt-fill").click();
  await expect(page.getByTestId("composer")).toHaveValue(`/model-setup ${ASK.en}`);
});

test("the x closes it; a reload does not bring it back; neither does a second bot", async ({ page }) => {
  await open(page);
  await installFromPopover(page);
  await expect(page.getByTestId("omh-prompt")).toBeVisible();
  await page.getByTestId("omh-prompt-close").click();
  await expect(page.getByTestId("omh-prompt")).toHaveCount(0);
  await expect(page.getByTestId("composer")).toHaveValue("");
  expect((await sends()).length).toBe(0);
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.waitForTimeout(800);
  await expect(page.getByTestId("omh-prompt")).toHaveCount(0);
  await page.getByTestId("bot-friren").click();
  await page.waitForTimeout(500);
  await expect(page.getByTestId("omh-prompt")).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("omher.omhPrompt"))).toBe("done");
});

test("after the action a reload does not bring it back either", async ({ page }) => {
  await open(page);
  await installFromPopover(page);
  await page.getByTestId("omh-prompt-fill").click();
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.waitForTimeout(800);
  await expect(page.getByTestId("omh-prompt")).toHaveCount(0);
  await expect(page.getByTestId("omh-prompt-restart")).toHaveCount(0);
});

test("a reload before pressing anything keeps the one offer (it was not used yet)", async ({ page }) => {
  await open(page);
  await installFromPopover(page);
  await expect(page.getByTestId("omh-prompt")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("omh-prompt")).toBeVisible();
});

test("a person with oh-my-hermes from the start never sees it", async ({ page }) => {
  await mock("mock.skills", { add: [MODEL_SETUP] });
  await open(page, { omh: true });
  await page.waitForTimeout(1000);
  await expect(page.getByTestId("omh-prompt")).toHaveCount(0);
  await expect(page.getByTestId("omh-prompt-restart")).toHaveCount(0);
  const ops = (await mock("mock.calls")).calls!.map((c) => c.op);
  expect(ops).not.toContain("skills.list"); // nothing asked for it
});

test("the first-run screen's install (Hermes was missing) brings the same line", async ({ page }) => {
  await mock("mock.skills", { add: [MODEL_SETUP] });
  await open(page, { gate: "missing" });
  await expect(page.getByTestId("setup-screen")).toBeVisible();
  await page.getByTestId("setup-install").click();
  // Hermes was just installed: the installer's own default profile is the person's bot, and the app lands there
  await expect(page.getByTestId("bot-default")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("omh-prompt")).toBeVisible();
  await page.getByTestId("omh-prompt-fill").click();
  await expect(page.getByTestId("composer")).toHaveValue(`/omh-model-setup ${ASK.en}`);
  expect((await sends()).length).toBe(0);
});

for (const lang of ["ko", "ja", "zh"] as const) {
  test(`the line and the prompt in ${lang}`, async ({ page }) => {
    await open(page, { lang });
    await installFromPopover(page);
    await expect(page.getByTestId("omh-prompt")).toContainText(READY[lang]);
    await page.getByTestId("omh-prompt-fill").click();
    await expect(page.getByTestId("composer")).toHaveValue(`/omh-model-setup ${ASK[lang]}`);
  });
}

for (const lang of ["ko", "ja", "zh"] as const) {
  test(`the "not yet" lines in ${lang} name the bot and no command`, async ({ page }) => {
    await open(page, { lang });
    await installFromPopover(page, "never");
    await expect(page.getByTestId("omh-prompt-restart").locator(".omhp-t")).toHaveText(NO_SKILLS[lang]);
  });
}

for (const width of [900, 1280]) {
  test(`the line overlaps nothing at ${width}px, with a long chat and with the side panel open`, async ({ page }) => {
    await page.setViewportSize({ width, height: 700 });
    await open(page);
    await installFromPopover(page);
    await expect(page.getByTestId("omh-prompt")).toBeVisible();
    noOverlap(await geometry(page));
    await page.keyboard.press("ControlOrMeta+Period");
    await page.waitForTimeout(500);
    const a = await geometry(page);
    await page.waitForTimeout(80);
    const b = await geometry(page);
    expect(a.line).toEqual(b.line);
    noOverlap(b);
    // the action and the x stay on one line with the text, inside the column
    const row = await page.getByTestId("omh-prompt").evaluate((el) => {
      const r = el.getBoundingClientRect();
      const kids = [...el.children].map((c) => c.getBoundingClientRect());
      return { h: r.height, inside: kids.every((k) => k.left >= r.left - 0.5 && k.right <= r.right + 0.5) };
    });
    expect(row.inside).toBe(true);
    expect(row.h).toBeLessThanOrEqual(width < 1000 ? 44 : 24);
  });
}
