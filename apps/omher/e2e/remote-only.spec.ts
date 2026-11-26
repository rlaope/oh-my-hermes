// Remote-only mode (BOUNDARY rule 46), the page side: the first screen's two choices, Check that lists the server's bots
// before anything is saved, a refused key that names ssh-copy-id, Connect landing in the app with the server's bots,
// Settings › Server (Use this computer goes back to the first screen), a lost link said in the bar, no Hand to <bot>
// on a server, and the update button on the gate.
// `window.__OMHER_GATE__` stands in for the shell (bridge_status, remote_check, remote_use, remote_leave, remote_status,
// peers_hosts); its mode lives in localStorage so a reload keeps it, as the mode file does. The "server" is the mock
// bridge itself: Check returns its URL, and after Connect the page dials it as it would the forwarded port.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_REMOTE_SHOTS || "";
const URL_ = `ws://127.0.0.1:${MOCK}/?token=e2e`;

type Start = { mode: "local" | "remote"; host?: string; label?: string; update?: string; linkLost?: boolean };

async function stub(page: Page, start: Start) {
  await page.addInitScript(
    ({ start, url }) => {
      const w = window as unknown as Record<string, unknown>;
      const KEY = "e2e.remoteMode";
      // the first load seeds the "mode file"; a reload reads what the page last made of it
      if (!sessionStorage.getItem("e2e.seeded")) {
        sessionStorage.setItem("e2e.seeded", "1");
        if (start.mode === "remote") localStorage.setItem(KEY, JSON.stringify({ host: start.host, label: start.label }));
        else localStorage.removeItem(KEY);
      }
      const file = () => JSON.parse(localStorage.getItem(KEY) || "null") as { host: string; label: string } | null;
      const calls: unknown[] = [];
      w.__gateCalls = calls;
      let lost = false;
      w.__loseLink = (v: boolean) => (lost = v);
      w.__OMHER_GATE__ = {
        status: async () => {
          const f = file();
          if (!f) return { state: "failed", error: "Hermes not found: install Hermes Agent first", missing: "hermes", mode: "local" };
          return lost ? { state: "starting", error: "ssh: connect to host vps port 22: Connection refused", mode: "remote", host: f.host } : { state: "ready", mode: "remote", host: f.host };
        },
        retry: async () => {},
        installCommand: async () => "curl -fsSL https://example.invalid/install.sh | sh",
        install: async () => 1,
        hosts: async () => ["vps", "build-box"],
        remoteCheck: async (host: string, port?: number) => {
          calls.push(["remote_check", host, port ?? null]);
          await new Promise((r) => setTimeout(r, 80));
          const word = host.split("@").pop();
          if (word === "denied") throw { kind: "auth", line: `${host}: Permission denied (publickey).` };
          if (word === "nowhere") throw { kind: "unreachable", line: "ssh: Could not resolve hostname nowhere" };
          return {
            check: "c1",
            url,
            found: { python: "/home/demo/.hermes/venv/bin/python3", pyver: "3.12.9", command: `ssh -o BatchMode=yes -T -L 127.0.0.1:53005:127.0.0.1:41873 -- ${host} sh -c '<remote script>'`, script: "" },
          };
        },
        remoteCheckClose: async (check: string) => void calls.push(["peers_check_close", check]),
        remoteUse: async (label: string, host: string, port: number | undefined, check: string | undefined) => {
          calls.push(["remote_use", label, host, port ?? null, check ?? null]);
          localStorage.setItem(KEY, JSON.stringify({ host, label }));
          return { mode: "remote", host, label, state: "connected" };
        },
        remoteLeave: async () => {
          calls.push(["remote_leave"]);
          localStorage.removeItem(KEY);
          return { mode: "local" };
        },
        remoteStatus: async () => {
          const f = file();
          return f ? { mode: "remote", host: f.host, label: f.label, state: "connected" } : { mode: "local" };
        },
      };
      if (start.update)
        w.__omherUpdateHost = {
          check: async () => ({ version: start.update, install: async () => {} }),
          relaunch: async () => {},
        };
    },
    { start, url: URL_ },
  );
}

const calls = (page: Page) => page.evaluate(() => (window as unknown as { __gateCalls: unknown[] }).__gateCalls);

async function shots(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  for (const theme of ["dark", "light"]) {
    await page.evaluate((th) => (document.documentElement.dataset.theme = th), theme);
    await page.screenshot({ path: join(SHOTS, `omher-remote-${name}-${theme}.png`) });
  }
  await page.evaluate(() => (document.documentElement.dataset.theme = "dark"));
}

test.use({ colorScheme: "dark" });

test("the first screen offers both: install here, or connect to a server over SSH", async ({ page }) => {
  await stub(page, { mode: "local" });
  await page.goto("/");
  const choices = page.getByTestId("gate-choices");
  await expect(choices.getByTestId("gate-choice-install")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("setup-install")).toBeVisible();
  await shots(page, "gate-install");
  await choices.getByTestId("gate-choice-remote").click();
  await expect(page.getByTestId("setup-head")).toHaveText("Use Hermes on a server");
  await expect(page.getByTestId("setup-install")).toHaveCount(0);
  await expect(page.getByTestId("remote-host")).toBeFocused();
  // ~/.ssh/config names, as the peer card offers them
  await expect(page.getByTestId("remote-suggestions")).toContainText("vps");
  await expect(page.getByTestId("remote-check")).toBeDisabled();
  await page.getByTestId("remote-port").fill("70000");
  await expect(page.getByTestId("remote-port-bad")).toBeVisible();
  await page.getByTestId("remote-port").fill("");
  await shots(page, "gate-connect");
});

test("Check lists the server's bots before anything is saved; Connect lands in the app with them", async ({ page }) => {
  await stub(page, { mode: "local" });
  await page.goto("/");
  await page.getByTestId("gate-choice-remote").click();
  await page.getByTestId("remote-host").fill("demo@vps");
  await page.getByTestId("remote-port").fill("2222");
  await expect(page.getByTestId("remote-label")).toHaveValue("vps");
  await page.getByTestId("remote-label").fill("VPS");
  await page.getByTestId("remote-check").click();
  const found = page.getByTestId("remote-found");
  await expect(found).toBeVisible();
  await expect(page.getByTestId("remote-bots")).toContainText("Kami");
  await expect(page.getByTestId("remote-bots")).toContainText("Friren");
  await expect(page.getByTestId("remote-command")).toContainText("demo@vps");
  await expect(page.getByTestId("remote-hermes")).toContainText("Python 3.12.9");
  expect(await calls(page)).toEqual([["remote_check", "demo@vps", 2222]]);
  await shots(page, "gate-found");
  await page.getByTestId("remote-use").click();
  await expect(page.getByTestId("bridge-gate")).toHaveCount(0);
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  expect(await calls(page)).toEqual([
    ["remote_check", "demo@vps", 2222],
    ["remote_use", "VPS", "demo@vps", 2222, "c1"],
  ]);
});

test("a key the server refuses names ssh-copy-id; an unknown host says so with ssh's line", async ({ page }) => {
  await stub(page, { mode: "local" });
  await page.goto("/");
  await page.getByTestId("gate-choice-remote").click();
  await page.getByTestId("remote-host").fill("demo@denied");
  await page.getByTestId("remote-check").click();
  const fail = page.getByTestId("remote-fail");
  await expect(fail).toHaveAttribute("data-kind", "auth");
  await expect(fail).toContainText("did not accept your ssh key");
  await expect(page.getByTestId("remote-fix")).toHaveText("ssh-copy-id demo@denied");
  await expect(page.getByTestId("remote-use")).toHaveCount(0);
  await expect(page.getByTestId("remote-check")).toHaveText("Check again");
  await shots(page, "gate-fail");
  await page.getByTestId("remote-host").fill("nowhere");
  await page.getByTestId("remote-check").click();
  await expect(fail).toHaveAttribute("data-kind", "unreachable");
  await expect(fail).toContainText("Could not resolve hostname nowhere");
  expect((await calls(page)).filter((c) => (c as string[])[0] === "remote_use")).toEqual([]);
});

test("on a server: Settings shows the Server block; Use this computer goes back to the first screen", async ({ page }) => {
  await stub(page, { mode: "remote", host: "demo@vps", label: "VPS" });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.keyboard.press(process.platform === "darwin" ? "Meta+," : "Control+,");
  await page.getByTestId("settings-nav-general").click();
  const block = page.getByTestId("server-block");
  await expect(block).toContainText("VPS");
  await expect(page.getByTestId("server-host")).toHaveText("demo@vps");
  // other computers are the server's to reach: no peer link starts from here
  await expect(page.getByTestId("remote-add")).toHaveCount(0);
  await expect(page.getByTestId("remote-add-off")).toBeVisible();
  await page.getByTestId("server-change").click();
  await expect(page.getByTestId("change-server").getByTestId("remote-host")).toBeFocused();
  await page.getByTestId("remote-cancel").click();
  await expect(page.getByTestId("change-server")).toHaveCount(0);
  await page.getByTestId("server-leave").click();
  await expect(page.getByTestId("gate-choices")).toBeVisible();
  await expect(page.getByTestId("setup-install")).toBeVisible();
  expect(await calls(page)).toEqual([]); // a fresh page after the reload; the leave was asked before it
  expect(await page.evaluate(() => localStorage.getItem("e2e.remoteMode"))).toBeNull();
});

test("a link lost after the app was up is said in the bar, not the install screen", async ({ page }) => {
  await stub(page, { mode: "remote", host: "demo@vps", label: "VPS" });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.evaluate(() => (window as unknown as { __loseLink: (v: boolean) => void }).__loseLink(true));
  const bar = page.getByTestId("bridge-bar");
  await expect(bar).toContainText("Connection to VPS lost, reconnecting", { timeout: 5000 });
  await expect(page.getByTestId("setup-screen")).toHaveCount(0);
  await page.evaluate(() => (window as unknown as { __loseLink: (v: boolean) => void }).__loseLink(false));
  await expect(bar).toHaveCount(0, { timeout: 5000 });
});

test("before the app was up, a server still connecting says so by name", async ({ page }) => {
  await stub(page, { mode: "remote", host: "demo@vps", label: "VPS" });
  await page.addInitScript(() => (window as unknown as { __loseLink: (v: boolean) => void }).__loseLink(true));
  await page.goto("/");
  await expect(page.getByTestId("remote-head")).toHaveText("Connecting to VPS…");
  await expect(page.getByTestId("bridge-error")).toContainText("Connection refused");
  await expect(page.getByTestId("remote-leave")).toBeVisible();
  await expect(page.getByTestId("setup-install")).toHaveCount(0);
  await shots(page, "gate-connecting");
});

test("on a server a terminal row offers no Hand to <bot>", async ({ page }) => {
  await stub(page, { mode: "remote", host: "demo@vps", label: "VPS" });
  await page.addInitScript(() => {
    for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume", "__omherMockHistory"]) localStorage.removeItem(k);
    const w = window as unknown as Record<string, unknown>;
    w.__omherPickFolder = "/w/here";
    w.__omherMockAgents = ["claude", "codex", "omh"];
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  // no Hermes chat in a folder of this computer either
  await expect(page.getByTestId("session-agent-claude")).toBeVisible();
  await expect(page.getByTestId("session-agent-omh")).toHaveCount(0);
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-agent-shell").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  const id = (await page.getByTestId("terminal").getAttribute("data-session"))!;
  await page.getByTestId(`session-${id}`).click({ button: "right" });
  const menu = page.getByTestId("session-row-menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByTestId("session-hand")).toHaveCount(0);
});

test("the update button shows on the gate, so a person stuck there can update in place", async ({ page }) => {
  await stub(page, { mode: "local", update: "9.9.9" });
  await page.goto("/");
  const upd = page.getByTestId("gate-update").getByTestId("update-btn");
  await expect(upd).toHaveText("Update to 9.9.9");
  await page.getByTestId("gate-choice-remote").click();
  await expect(upd).toBeVisible();
  await upd.click();
  await expect(page.getByTestId("update-confirm")).toBeVisible();
});
