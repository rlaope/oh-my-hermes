// SSH peers in the UI, against the mock bridge and the browser's mock peers host (BOUNDARY rule 31):
// 1. sidebar `+` -> Connect over SSH: host suggestions from ~/.ssh/config, Check shows the exact ssh command, the
//    remote Hermes and its bots; Cancel comes first; only Connect adds the computer, and its bots join the list;
// 2. the SSH marker on the sidebar row, the chat header, the bot card and the bot page, with the host in the tooltip,
//    and the link state (reconnecting / failed) on the header marker;
// 3. a bot asked "connect the Mac mini" answers with an omher-peer block: a Connect over SSH chip under the reply opens
//    the same card prefilled with "Proposed by"; an invalid draft shows a disabled chip with the reason;
// 4. errors in plain words: key refused (with ssh-copy-id), unreachable, Hermes missing;
// 5. folder chats and Restart refuse a bot on another computer; Settings › Remote machines removes one after asking.
// Shots (dark and light, animations off): OMHER_SHOTS=<dir>.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  return reply;
}
const calls = async (): Promise<{ op: string; params: Record<string, unknown> }[]> => (await mock("mock.calls")).result.calls;

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, name), animations: "disabled" });
}

async function open(page: Page, theme: "dark" | "light" = "dark") {
  await page.emulateMedia({ colorScheme: theme });
  await page.goto("/");
  await page.evaluate(() => localStorage.removeItem("omher.mockPeers"));
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

/** The whole attach flow through the sidebar `+`, ending with the remote bot in the list. */
async function attachMini(page: Page) {
  await page.getByRole("button", { name: "Add a bot" }).click();
  await page.getByTestId("addbot-ssh").click();
  const card = page.getByTestId("peer-card");
  await expect(card).toBeVisible();
  await card.getByTestId("peer-host").fill("sionic@10.1.145.204");
  await card.getByTestId("peer-label").fill("Mac mini");
  await card.getByTestId("peer-check").click();
  await expect(card.getByTestId("peer-found")).toBeVisible();
  await card.getByTestId("peer-connect").click();
  await expect(card).toHaveCount(0);
  await expect(page.getByTestId("bot-mac-mini:mini")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("sidebar + → Connect over SSH: suggestions, Check, the exact command, Cancel first, then Connect", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "Add a bot" }).click();
  const pop = page.getByTestId("addbot");
  await expect(pop.getByTestId("addbot-ssh")).toContainText("Connect over SSH");
  await shot(page, "peer-popover-dark.png");
  await pop.getByTestId("addbot-ssh").click();
  const card = page.getByTestId("peer-card");
  // suggestions from ~/.ssh/config (the mock host's: no wildcard patterns)
  await expect(card.getByTestId("peer-suggestions")).toContainText("mini");
  await card.getByRole("button", { name: "build-box" }).click();
  await expect(card.getByTestId("peer-host")).toHaveValue("build-box");
  await expect(card.getByTestId("peer-label")).toHaveValue("build-box");
  // a host the shell refuses cannot be checked
  await card.getByTestId("peer-host").fill("-oProxyCommand=sh");
  await expect(card.getByTestId("peer-host-bad")).toBeVisible();
  await expect(card.getByTestId("peer-check")).toBeDisabled();
  await card.getByTestId("peer-host").fill("sionic@10.1.145.204");
  await card.getByTestId("peer-label").fill("Mac mini");
  await card.getByTestId("peer-check").click();
  const found = card.getByTestId("peer-found");
  await expect(found).toBeVisible();
  // shown one option per line; read back as one line it is the shell's exact argv
  const shown = (await card.getByTestId("peer-command").innerText()).replace(/ \\\n\s*/g, " ");
  expect(shown).toMatch(/^ssh -o BatchMode=yes -o ConnectTimeout=10 .* -L 127\.0\.0\.1:\d+:127\.0\.0\.1:\d+ -- sionic@10\.1\.145\.204 sh -c '<remote script>'$/);
  await expect(card.getByTestId("peer-command")).toContainText("-o BatchMode=yes \\\n");
  await expect(card.getByTestId("peer-hermes")).toContainText("Hermes 0.23.1 · Python 3.14.9");
  await expect(card.getByTestId("peer-bots")).toContainText("mini");
  // Cancel first, Connect second
  const buttons = card.locator(".upd-dlg-f button");
  await expect(buttons.nth(0)).toHaveText("Cancel");
  await expect(buttons.nth(1)).toHaveText("Connect");
  await card.locator("#peer-card-t").click();
  await shot(page, "peer-confirm-dark.png");
  // the probe read hello and bots.list only; nothing attached before Connect
  expect((await calls()).map((c) => c.op).filter((op) => op.startsWith("peers."))).toEqual(["peers.probe"]);
  await card.getByTestId("peer-connect").click();
  await expect(card).toHaveCount(0);
  await expect(page.getByTestId("bot-mac-mini:mini")).toBeVisible();
  const attach = (await calls()).filter((c) => c.op === "peers.attach");
  expect(attach.map((c) => [c.params.peer, c.params.label, c.params.host])).toEqual([["mac-mini", "Mac mini", "sionic@10.1.145.204"]]);
});

test("the SSH marker: sidebar row, chat header, bot card and page; link state on the header", async ({ page }) => {
  await open(page);
  await attachMini(page);
  const row = page.getByTestId("ssh-mark-mac-mini:mini");
  await expect(row).toContainText("SSH");
  await expect(row).toContainText("Mac mini");
  await expect(row).toHaveAttribute("title", /sionic@10\.1\.145\.204/);
  // the local bots carry none
  await expect(page.getByTestId("ssh-mark-kami")).toHaveCount(0);
  await page.getByTestId("bot-mac-mini:mini").click();
  const head = page.getByTestId("head-ssh");
  await expect(head).toContainText("SSH · Mac mini");
  await expect(page.getByTestId("timeline")).toContainText("All 412 tests passed");
  await shot(page, "peer-marker-dark.png");
  // the link drops: the header says so, then it comes back
  await page.evaluate(() => (window as any).__omherPeerState("mac-mini", { state: "reconnecting", attempt: 1, kind: "dropped" }));
  await expect(head).toHaveAttribute("data-state", "reconnecting");
  await expect(head).toContainText("reconnecting");
  await page.evaluate(() => (window as any).__omherPeerState("mac-mini", { state: "failed", kind: "auth", reason: "Permission denied (publickey)." }));
  await expect(head).toContainText("key refused");
  await expect(head).toHaveAttribute("title", /did not accept your ssh key/);
  await shot(page, "peer-marker-failed-dark.png");
  await page.evaluate(() => (window as any).__omherPeerState("mac-mini", { state: "connected", kind: undefined, reason: "" }));
  await expect(head).toHaveAttribute("data-state", "connected");
  // Settings: the bot card and the bot's page
  await page.keyboard.press(process.platform === "darwin" ? "Meta+," : "Control+,");
  await page.getByTestId("settings-nav-bots").click();
  await expect(page.getByTestId("card-ssh-mac-mini:mini")).toContainText("Mac mini");
  await page.getByTestId("bot-card-mac-mini:mini").click();
  await expect(page.getByTestId("page-ssh")).toContainText("SSH · Mac mini");
  await page.emulateMedia({ colorScheme: "light" });
  await page.getByTestId("bot-mac-mini:mini").click();
  await expect(page.getByTestId("head-ssh")).toBeVisible();
  await shot(page, "peer-marker-light.png");
});

for (const theme of ["dark", "light"] as const) {
test(`a bot asked to connect the Mac mini drafts it (${theme}): the chip opens the same card, prefilled, Proposed by`, async ({ page }) => {
  await open(page, theme);
  await page.getByTestId("bot-friren").click();
  await page.getByTestId("composer").fill("맥미니 헤르메스 붙여줘");
  await page.getByTestId("send").click();
  // the bridge added its one note to the turn; the person's bubble shows only what they typed
  await expect.poll(async () => (await mock("mock.submits")).result.submits.at(-1)?.text ?? "").toContain("```omher-peer");
  await expect(page.getByTestId("bubble-user").last()).toHaveText("맥미니 헤르메스 붙여줘");
  const chip = page.getByTestId("peer-chip");
  await expect(chip).toBeVisible();
  await expect(chip).toContainText("Connect over SSH");
  await expect(chip).toContainText("Mac mini");
  await shot(page, `peer-chip-${theme}.png`);
  expect((await calls()).some((c) => c.op === "peers.attach")).toBe(false); // the chip alone connects nothing
  await chip.click();
  const card = page.getByTestId("peer-card");
  await expect(card.getByTestId("peer-by")).toHaveText("Proposed by Friren");
  await expect(card.getByTestId("peer-host")).toHaveValue("sionic@10.1.145.204");
  await expect(card.getByTestId("peer-label")).toHaveValue("Mac mini");
  await card.getByTestId("peer-check").click();
  await expect(card.getByTestId("peer-found")).toBeVisible();
  await card.locator("#peer-card-t").click();
  await shot(page, `peer-chip-card-${theme}.png`);
  await card.getByTestId("peer-cancel").click();
  await expect(card).toHaveCount(0);
  expect((await calls()).some((c) => c.op === "peers.attach")).toBe(false);
});
}

test("an invalid draft shows a disabled chip with its reason", async ({ page }) => {
  await open(page);
  await page.getByTestId("bot-kami").click();
  const text = 'Try this.\n\n```omher-peer\n{"host": "-oProxyCommand=sh", "label": "x"}\n```\n\n```omher-peer\n{not json}\n```';
  await mock("mock.emit", { events: [{ event: "turn.start", bot: "kami" }, { event: "message", bot: "kami", id: "bad-draft", text }, { event: "turn.end", bot: "kami", outcome: "done" }] });
  const chips = page.getByTestId("peer-chip");
  await expect(chips).toHaveCount(2);
  await expect(chips.nth(0)).toBeDisabled();
  await expect(chips.nth(0)).toHaveAttribute("data-why", "host");
  await expect(chips.nth(0)).toContainText("not a host omher can use");
  await expect(chips.nth(1)).toHaveAttribute("data-why", "json");
});

for (const theme of ["dark", "light"] as const) {
  test(`errors in plain words (${theme}): key refused, unreachable, Hermes missing`, async ({ page }) => {
    await open(page, theme);
    await page.getByRole("button", { name: "Add a bot" }).click();
    await page.getByTestId("addbot-ssh").click();
    const card = page.getByTestId("peer-card");
    await card.getByTestId("peer-host").fill("sionic@denied");
    await card.getByTestId("peer-label").fill("Mac mini");
    await card.getByTestId("peer-check").click();
    const fail = card.getByTestId("peer-fail");
    await expect(fail).toHaveAttribute("data-kind", "auth");
    await expect(fail).toContainText("did not accept your ssh key");
    await expect(fail).toContainText("ssh-copy-id sionic@denied");
    await expect(card.getByTestId("peer-check")).toHaveText("Check again");
    await expect(card.getByTestId("peer-connect")).toHaveCount(0);
    await card.locator("#peer-card-t").click();
    await shot(page, `peer-error-${theme}.png`);
    await card.getByTestId("peer-host").fill("nowhere");
    await card.getByTestId("peer-check").click();
    await expect(fail).toHaveAttribute("data-kind", "unreachable");
    await expect(fail).toContainText("Could not reach nowhere");
    await card.getByTestId("peer-host").fill("bare");
    await card.getByTestId("peer-check").click();
    await expect(fail).toHaveAttribute("data-kind", "no_hermes");
    await expect(fail).toContainText("Hermes is not installed on bare");
    expect((await calls()).some((c) => c.op.startsWith("peers."))).toBe(false);
  });
}

test("a remote bot: folder chats and Restart refuse it; Settings removes the computer after asking once", async ({ page }) => {
  await open(page);
  await attachMini(page);
  const restart = await mock("bots.restart", { bot: "mac-mini:mini" });
  expect(restart.ok).toBe(false);
  expect(restart.error.code).toBe("remote_bot");
  const folder = await mock("folder.open", { bot: "mac-mini:mini", cwd: "/tmp" });
  expect(folder.error.code).toBe("remote_bot");
  await page.keyboard.press(process.platform === "darwin" ? "Meta+," : "Control+,");
  await page.getByTestId("settings-nav-general").click();
  const section = page.getByTestId("remote-machines");
  await expect(section.getByTestId("remote-mac-mini")).toContainText("sionic@10.1.145.204");
  await section.getByTestId("remote-remove-mac-mini").click();
  await expect(section).toContainText("Remove Mac mini?");
  await section.getByTestId("remote-remove-yes-mac-mini").click();
  await expect(section.getByTestId("remote-mac-mini")).toHaveCount(0);
  await expect(page.getByTestId("bot-mac-mini:mini")).toHaveCount(0);
  expect((await calls()).some((c) => c.op === "peers.detach")).toBe(true);
});

test("ko: the card and the marker read in Korean", async ({ page }) => {
  await open(page);
  await page.evaluate(() => localStorage.setItem("omher.lang", "ko"));
  await page.reload();
  await page.getByRole("button", { name: "봇 추가" }).click();
  await expect(page.getByTestId("addbot-ssh")).toContainText("SSH로 연결");
  await page.getByTestId("addbot-ssh").click();
  await expect(page.getByTestId("peer-card")).toContainText("다른 컴퓨터의 Hermes");
  await expect(page.getByTestId("peer-card")).not.toContainText("peer.");
});
