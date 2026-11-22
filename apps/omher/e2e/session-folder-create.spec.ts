// TERMINALS: a folder group made from the right-click menu ("New folder…").
// 1. the background menu lists New session, then New folder…; arrow keys, Home / End and Escape work on both;
// 2. New folder… opens the folder dialog (the mock host's `__omherPickFolder`) and the folder picked is a group at
//    once, with no session and nothing started: chevron, folder glyph, name, git branch, one quiet line;
// 3. it is kept in `omher.term.folders` (`added`) and is still there after a reload;
// 4. picking a listed folder again adds no second group (a collapsed one opens); Cancel changes nothing;
// 5. the group's header menu: New terminal here starts the Shell there, New folder… is the same action, Remove from
//    list is offered only for an added folder, takes it out of the list, and leaves a folder with a running session
//    listed.
// Shots: e2e/__shots__/ (git-ignored), or OMHER_SHOTS=<dir>: folder-create-menu-{en,ko}.png, folder-create-group.png,
// folder-create-header-menu.png.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || join(dirname(fileURLToPath(import.meta.url)), "__shots__");
const NEW = "/home/you/code/new-app";
const NOTES = "/home/you/notes";

async function mock(op: string): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "fc1", op }));
  });
  ws.close();
}

async function shot(page: Page, name: string) {
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled" });
}

/** The app as a returning person sees it, with no terminal session and no folder kept. A reload keeps what the page
 *  saved (the init script clears storage on the first load only). */
async function open(page: Page, lang = "en") {
  await page.addInitScript(
    ([lang, folder]) => {
      if (!sessionStorage.getItem("__kept")) {
        for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "omher.term.folders", "omher.side.split"]) localStorage.removeItem(k);
        localStorage.setItem("omher.lang", lang);
        sessionStorage.setItem("__kept", "1");
      }
      const w = window as unknown as Record<string, unknown>;
      w.__omherPickFolder = folder;
      w.__omherBranches = { "/home/you/code/new-app": "feature/checkout-flow" };
    },
    [lang, NEW] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

const pick = (page: Page, folder: string | null) => page.evaluate((f) => ((window as unknown as Record<string, unknown>).__omherPickFolder = f), folder);
/** Right-click TERMINALS where no row, header or control is (its own label's line). */
const background = (page: Page) => page.getByTestId("side-sessions").click({ button: "right", position: { x: 40, y: 8 } });
const groups = (page: Page) => page.getByTestId("term-group").evaluateAll((els) => els.map((e) => e.getAttribute("data-cwd")));
const group = (page: Page, cwd: string) => page.locator(`[data-testid=term-group][data-cwd="${cwd}"]`);
const saved = (page: Page) => page.evaluate(() => JSON.parse(localStorage.getItem("omher.term.folders") ?? "{}") as { added?: string[]; order?: string[]; collapsed?: string[] });
const starts = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __omherSessionCalls?: { op: string }[]; __omherShellCalls?: { op: string; cwd?: string }[] };
    return [...(w.__omherSessionCalls ?? []), ...(w.__omherShellCalls ?? [])].filter((c) => c.op === "start" || c.op === "chat.start");
  });

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("the background menu makes a folder group that survives a reload; the header menu starts a terminal in it and removes it", async ({ page }) => {
  test.setTimeout(90_000);
  await open(page);
  await expect(page.getByTestId("session-none")).toBeVisible();
  expect(await groups(page)).toEqual([]);

  // 1. the menu: New session, then New folder…
  await background(page);
  const menu = page.getByTestId("sessions-context-menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem")).toHaveText(["New session", "New folder…"]);
  await shot(page, "folder-create-menu-en");
  const newSession = menu.getByRole("menuitem", { name: "New session", exact: true });
  const newFolder = page.getByTestId("sessions-new-folder");
  await expect(newSession).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(newFolder).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(newSession).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(newFolder).toBeFocused();
  await page.keyboard.press("Home");
  await expect(newSession).toBeFocused();
  await page.keyboard.press("End");
  await expect(newFolder).toBeFocused();
  // the whole menu is inside the window
  const box = (await menu.boundingBox())!;
  const win = page.viewportSize()!;
  expect(box.x).toBeGreaterThanOrEqual(6);
  expect(box.y).toBeGreaterThanOrEqual(6);
  expect(box.x + box.width).toBeLessThanOrEqual(win.width - 6);
  expect(box.y + box.height).toBeLessThanOrEqual(win.height - 6);
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  expect(await groups(page)).toEqual([]);

  // Cancel in the dialog changes nothing
  await pick(page, null);
  await background(page);
  await newFolder.click();
  await expect(menu).toHaveCount(0);
  await expect(page.getByTestId("session-none")).toBeVisible();
  expect((await saved(page)).added ?? []).toEqual([]);

  // 2. the folder picked is a group at once, and nothing started
  await pick(page, NEW);
  await background(page);
  await page.keyboard.press("End");
  await page.keyboard.press("Enter");
  const made = group(page, NEW);
  await expect(made).toBeVisible();
  await expect(made.locator(".tg-n")).toHaveText("new-app");
  await expect(made.locator(".tg-chev svg")).toBeVisible();
  await expect(made.locator(".tg-ic svg")).toBeVisible();
  await expect(made.getByTestId("term-group-branch")).toHaveText("feature/checkout-flow");
  await expect(made.getByTestId("term-group-toggle")).toHaveAttribute("aria-expanded", "true");
  await expect(made.getByTestId("term-group-empty")).toHaveText("No terminals · right-click to add");
  await expect(made.locator(".ss-row")).toHaveCount(0);
  // the hint is one line and not cut
  const hint = await made.getByTestId("term-group-empty").evaluate((el) => ({ h: el.getBoundingClientRect().height, scroll: el.scrollWidth, client: el.clientWidth }));
  expect(hint.h).toBeLessThanOrEqual(18);
  expect(hint.scroll).toBeLessThanOrEqual(hint.client);
  expect(await starts(page)).toEqual([]);
  expect(await groups(page)).toEqual([NEW]);
  expect(await saved(page)).toMatchObject({ added: [NEW], order: [NEW] });
  await page.mouse.move(700, 500);
  await shot(page, "folder-create-group");

  // 3. still there after a reload
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await expect(group(page, NEW)).toBeVisible();
  await expect(group(page, NEW).getByTestId("term-group-empty")).toBeVisible();
  expect(await groups(page)).toEqual([NEW]);
  expect(await starts(page)).toEqual([]);

  // 4. picked again: no second group; a collapsed one opens
  await group(page, NEW).getByTestId("term-group-toggle").click();
  await expect(group(page, NEW)).toHaveAttribute("data-collapsed", "true");
  await expect(group(page, NEW).getByTestId("term-group-empty")).toHaveCount(0);
  await background(page);
  await page.getByTestId("sessions-new-folder").click();
  await expect(group(page, NEW)).not.toHaveAttribute("data-collapsed", "true");
  expect(await groups(page)).toEqual([NEW]);
  expect((await saved(page)).added).toEqual([NEW]);

  // 5. the header menu of an added folder: five items, arrow keys and Escape
  const head = group(page, NEW).getByTestId("term-group-head");
  await head.click({ button: "right" });
  const folderMenu = page.getByTestId("term-folder-menu");
  await expect(folderMenu).toBeVisible();
  await expect(folderMenu.getByRole("menuitem")).toHaveText(["New terminal here", "Collapse others", /^Show in /, "New folder…", "Remove from list"]);
  await shot(page, "folder-create-header-menu");
  await expect(page.getByTestId("term-folder-new")).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("term-folder-remove")).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("term-folder-add")).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("term-folder-new")).toBeFocused();
  const fbox = (await folderMenu.boundingBox())!;
  expect(fbox.y + fbox.height).toBeLessThanOrEqual(win.height - 6);
  await page.keyboard.press("Escape");
  await expect(folderMenu).toHaveCount(0);
  // the background menu did not open with it (the header owns its right-click, its quiet line included)
  await group(page, NEW).getByTestId("term-group-empty").click({ button: "right" });
  await expect(folderMenu).toBeVisible();
  await expect(page.getByTestId("sessions-context-menu")).toHaveCount(0);
  await page.keyboard.press("Escape");

  // New folder… from a header: the same action; the newest folder lists first
  await pick(page, NOTES);
  await head.click({ button: "right" });
  await page.getByTestId("term-folder-add").click();
  await expect(group(page, NOTES)).toBeVisible();
  expect(await groups(page)).toEqual([NOTES, NEW]);
  expect((await saved(page)).added).toEqual([NOTES, NEW]);

  // Remove from list: the empty folder leaves the list, the other stays
  await group(page, NOTES).getByTestId("term-group-head").click({ button: "right" });
  await page.getByTestId("term-folder-remove").click();
  await expect(group(page, NOTES)).toHaveCount(0);
  expect(await groups(page)).toEqual([NEW]);
  expect((await saved(page)).added).toEqual([NEW]);

  // New terminal here: the Shell starts in the added folder, and its row takes the quiet line's place
  await head.click({ button: "right" });
  await page.getByTestId("term-folder-new").click();
  await expect(group(page, NEW).locator(".ss-row.tr")).toHaveCount(1);
  await expect(group(page, NEW).getByTestId("term-group-empty")).toHaveCount(0);
  await expect(page.getByTestId("terminal")).toBeVisible();
  expect((await starts(page)).length).toBe(1);
  expect(await groups(page)).toEqual([NEW]);

  // removed while its session runs: the list forgets it, the session and its group go on
  await head.click({ button: "right" });
  await page.getByTestId("term-folder-remove").click();
  await expect(group(page, NEW)).toBeVisible();
  await expect(group(page, NEW).locator(".ss-row.tr")).toHaveCount(1);
  // the record is as it was before any folder was added: no `added` field
  expect("added" in (await saved(page))).toBe(false);
  // a folder that is listed only by its session offers no Remove
  await head.click({ button: "right" });
  await expect(folderMenu.getByRole("menuitem")).toHaveText(["New terminal here", "Collapse others", /^Show in /, "New folder…"]);
  await expect(page.getByTestId("term-folder-remove")).toHaveCount(0);
  await page.keyboard.press("Escape");
  // picking the folder its session lists adds nothing
  await pick(page, NEW);
  await background(page);
  await page.getByTestId("sessions-new-folder").click();
  expect(await groups(page)).toEqual([NEW]);
  expect("added" in (await saved(page))).toBe(false);
});

const WORDS: Record<string, { menu: string[]; remove: string; empty: string }> = {
  ko: { menu: ["새 세션", "새 폴더…"], remove: "목록에서 빼기", empty: "터미널이 없어요 · 우클릭해서 열어요" },
  ja: { menu: ["新しいセッション", "新しいフォルダ…"], remove: "リストから外す", empty: "ターミナルなし · 右クリックで追加" },
  zh: { menu: ["新建会话", "新建文件夹…"], remove: "从列表中移除", empty: "暂无终端 · 右键新建" },
};

for (const [lang, words] of Object.entries(WORDS)) {
  test(`the menu, the quiet line and Remove from list in ${lang}`, async ({ page }) => {
    await open(page, lang);
    await background(page);
    const menu = page.getByTestId("sessions-context-menu");
    await expect(menu.getByRole("menuitem")).toHaveText(words.menu);
    // neither label is cut in the 168px menu
    const cut = await menu.getByRole("menuitem").evaluateAll((els) => els.filter((e) => e.scrollWidth > e.clientWidth).map((e) => e.textContent));
    expect(cut).toEqual([]);
    if (lang === "ko") await shot(page, "folder-create-menu-ko");
    await page.getByTestId("sessions-new-folder").click();
    const made = group(page, NEW);
    await expect(made.getByTestId("term-group-empty")).toHaveText(words.empty);
    const hint = await made.getByTestId("term-group-empty").evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
    expect(hint.scroll).toBeLessThanOrEqual(hint.client);
    await made.getByTestId("term-group-head").click({ button: "right" });
    await expect(page.getByTestId("term-folder-add")).toHaveText(words.menu[1]);
    await expect(page.getByTestId("term-folder-remove")).toHaveText(words.remove);
    const cut2 = await page.getByTestId("term-folder-menu").getByRole("menuitem").evaluateAll((els) => els.filter((e) => e.scrollWidth > e.clientWidth).map((e) => e.textContent));
    expect(cut2).toEqual([]);
    await page.getByTestId("term-folder-remove").click();
    await expect(made).toHaveCount(0);
    await expect(page.getByTestId("session-none")).toBeVisible();
  });
}
