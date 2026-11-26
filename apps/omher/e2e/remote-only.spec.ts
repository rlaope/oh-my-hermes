// Remote-only mode (BOUNDARY rule 46), the page side: the first screen's two choices, Check that lists the server's bots
// before anything is saved, a refused key that names ssh-copy-id, Connect landing in the app with the server's bots,
// Settings › Server (Use this computer goes back to the first screen), a lost link said in the bar, no Hand to <bot>
// on a server, and the update button on the gate. On a server nothing of this computer goes out: no saved folder chat
// is resumed, no file is attached, no installer runs (the WebSocket frames are checked), and a Check that answers after
// its form is gone is closed.
// `window.__OMHER_GATE__` stands in for the shell (bridge_status, remote_check, remote_use, remote_leave, remote_status,
// peers_hosts); its mode lives in localStorage so a reload keeps it, as the mode file does. The "server" is the mock
// bridge itself: Check returns its URL, and after Connect the page dials it as it would the forwarded port.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_REMOTE_SHOTS || "";
const URL_ = `ws://127.0.0.1:${MOCK}/?token=e2e`;

type Start = { mode: "local" | "remote"; host?: string; label?: string; update?: string; linkLost?: boolean; checkMs?: number };

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
        install: async () => (calls.push(["install_engine"]), 1),
        hosts: async () => ["vps", "build-box"],
        remoteCheck: async (host: string, port?: number) => {
          calls.push(["remote_check", host, port ?? null]);
          await new Promise((r) => setTimeout(r, start.checkMs ?? 80));
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

/** Every op the page sends over any WebSocket (the app's bridge and a Check's probe), in order. */
function sentOps(page: Page): { op: string; params: Record<string, unknown> }[] {
  const ops: { op: string; params: Record<string, unknown> }[] = [];
  page.on("websocket", (ws) =>
    ws.on("framesent", (f) => {
      try {
        const m = JSON.parse(String(f.payload));
        if (m && typeof m.op === "string") ops.push({ op: m.op, params: m });
      } catch {
        /* not JSON */
      }
    }),
  );
  return ops;
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

test("on a server a saved folder chat of this computer is not resumed, by itself or by Resume; it stays saved", async ({ page }) => {
  await stub(page, { mode: "remote", host: "demo@vps", label: "VPS" });
  const ops = sentOps(page);
  await page.addInitScript(() => {
    if (sessionStorage.getItem("e2e.resumeSeeded")) return;
    sessionStorage.setItem("e2e.resumeSeeded", "1");
    for (const k of ["omher.sessions.recent", "omher.sessions.open", "__omherMockHistory"]) localStorage.removeItem(k);
    localStorage.setItem(
      "omher.resume",
      JSON.stringify({
        v: 1,
        at: Date.now(),
        bot: "friren",
        view: "session",
        session: "s47",
        drafts: {},
        sessions: [{ id: "s47", agent: "omh", cwd: "/fixture/this-computer/project", startedAt: 1000, view: "chat", running: true, bot: "friren", agentSession: "20261126_120000_local001" }],
      }),
    );
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  // the saved chat opens as it was left: paused, saying why, never attached
  const paused = page.getByTestId("session-paused");
  await expect(paused).toContainText("omher uses a server");
  await page.getByTestId("session-resume").click();
  await expect(paused).toBeVisible();
  await page.waitForTimeout(500);
  expect(ops.filter((o) => o.op.startsWith("folder.")).map((o) => o.op)).toEqual([]);
  expect(JSON.stringify(ops)).not.toContain("/fixture/this-computer/project");
  // the row is kept as it was saved, for when this computer is used again
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("omher.resume") || "null"));
  expect(saved.sessions.find((x: { id: string }) => x.id === "s47")).toMatchObject({ cwd: "/fixture/this-computer/project", agentSession: "20261126_120000_local001", running: true });
});

test("on a server a chat takes no file from this computer: no +, drop or paste, one line says why", async ({ page }) => {
  await stub(page, { mode: "remote", host: "demo@vps", label: "VPS" });
  const ops = sentOps(page);
  await page.goto("/");
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("composer")).toBeEnabled();
  await expect(page.getByTestId("attach")).toHaveCount(0);
  await expect(page.getByTestId("composer-no-files")).toHaveText("omher uses a server: files from this computer can’t be sent to its bots.");
  const dt = await page.evaluateHandle(() => {
    const d = new DataTransfer();
    d.items.add(new File(["verify-fixture"], "this-computer.txt", { type: "text/plain" }));
    return d;
  });
  const pane = page.locator(".pane");
  await pane.dispatchEvent("dragenter", { dataTransfer: dt });
  await pane.dispatchEvent("dragover", { dataTransfer: dt });
  await expect(page.getByTestId("attach-drop")).toHaveCount(0);
  await pane.dispatchEvent("drop", { dataTransfer: dt });
  await page.getByTestId("composer").dispatchEvent("paste", { clipboardData: dt });
  await expect(page.getByTestId("attach-chips")).toHaveCount(0);
  await page.getByTestId("composer").fill("hello server");
  await page.getByTestId("send").click();
  await expect.poll(() => ops.filter((o) => o.op === "chat.send").length).toBe(1);
  expect(ops.filter((o) => o.op === "chat.attach")).toEqual([]);
  expect(JSON.stringify(ops)).not.toContain("this-computer.txt");
});

test("on a server no oh-my-hermes install is offered and the installer is never asked for", async ({ page }) => {
  await stub(page, { mode: "remote", host: "demo@vps", label: "VPS" });
  await page.addInitScript(() => {
    const w = window as unknown as Record<string, unknown>;
    localStorage.removeItem("omher.omhOffer.hidden");
    w.__omherMockAgents = ["claude", "codex"];
    w.__omherMockNoOmh = true;
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.getByTestId("session-new").or(page.getByTestId("session-start")).first().click();
  await expect(page.getByTestId("session-agent-claude")).toBeVisible();
  await expect(page.getByTestId("session-add-omh")).toHaveCount(0);
  await expect(page.getByTestId("omh-notice")).toHaveCount(0);
  expect((await calls(page)).filter((c) => (c as string[])[0] === "install_engine")).toEqual([]);
});

test("a Check that answers after its form is gone closes its link", async ({ page }) => {
  await stub(page, { mode: "local", checkMs: 600 });
  const ops = sentOps(page);
  await page.goto("/");
  await page.getByTestId("gate-choice-remote").click();
  await page.getByTestId("remote-host").fill("demo@vps");
  await page.getByTestId("remote-check").click();
  await page.getByTestId("gate-choice-install").click();
  await expect(page.getByTestId("setup-install")).toBeVisible();
  await expect.poll(() => calls(page)).toEqual([
    ["remote_check", "demo@vps", null],
    ["peers_check_close", "c1"],
  ]);
  // nothing reads the server through the closed check
  expect(ops.filter((o) => o.op === "hello" || o.op === "bots.list")).toEqual([]);
});

// ---- round 2: the page's one outgoing filter and the shell's local-Hermes refusal (rule 46) ----

/** A control op to the mock bridge on its own socket (not the page's). */
async function mockOp(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "m1", op, ...params }));
  });
  ws.close();
}

type HostCall = { op: string; agent?: string; id?: number; data?: string; cwd?: string };
const sessionCalls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: HostCall[] }).__omherSessionCalls ?? []));
const shellCalls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherShellCalls?: HostCall[] }).__omherShellCalls ?? []));

/** Seed `omher.resume` once (a reload keeps what the page made of it). */
async function seedResume(page: Page, resume: Record<string, unknown>, agents: string[]) {
  await page.addInitScript(
    ({ resume, agents }) => {
      const w = window as unknown as Record<string, unknown>;
      w.__omherMockAgents = agents;
      if (sessionStorage.getItem("e2e.r2Seeded")) return;
      sessionStorage.setItem("e2e.r2Seeded", "1");
      for (const k of ["omher.sessions.recent", "omher.sessions.open", "__omherMockHistory", "__omherMockClaudeConvs"]) localStorage.removeItem(k);
      localStorage.setItem("omher.resume", JSON.stringify({ v: 1, at: Date.now(), drafts: {}, ...resume }));
    },
    { resume, agents },
  );
}

test("on a server a saved local terminal's Plans panel reads nothing: no runs.cli, no cwd of this computer on the wire", async ({ page }) => {
  await stub(page, { mode: "remote", host: "demo@vps", label: "VPS" });
  const ops = sentOps(page);
  // verify.md finding 1: the last bot is also on the server, a Claude Code terminal is selected with Plans open
  await seedResume(
    page,
    {
      bot: "friren",
      view: "session",
      session: "s83",
      panelOpen: true,
      panelTab: "runs",
      sessions: [{ id: "s83", agent: "claude", open: "terminal", view: "terminal", running: true, agentSession: "11111111-2222-4333-8444-555555555555", cwd: "/fixture/local/private-worktree", startedAt: 100000 }],
    },
    ["claude", "codex"],
  );
  await page.goto("/");
  await expect(page.getByTestId("session-s83")).toBeVisible();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await page.waitForTimeout(1_500);
  // no Plans panel or its button for a session of this computer
  await expect(page.getByTestId("details-panel")).toHaveCount(0);
  await expect(page.getByTestId("panel-button")).toHaveCount(0);
  expect(ops.filter((o) => o.op === "runs.cli" || o.op === "cli.title")).toEqual([]);
  expect(JSON.stringify(ops)).not.toContain("/fixture/local/private-worktree");
  // the page was talking to the server all along
  expect(ops.some((o) => o.op === "bots.list")).toBe(true);
});

test("on a server a bot's picture is not changed from this computer: no picker, no drop, no bots.set_avatar", async ({ page }) => {
  await stub(page, { mode: "remote", host: "demo@vps", label: "VPS" });
  const ops = sentOps(page);
  await page.goto("/");
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-bot-kami").click();
  await expect(page.getByTestId("bot-head")).toBeVisible();
  // verify.md finding 2: Change picture, the clickable/droppable picture and its file input are all gone
  await expect(page.getByTestId("avatar-view")).toBeVisible();
  await expect(page.getByTestId("avatar-change")).toHaveCount(0);
  await expect(page.getByTestId("avatar-edit")).toHaveCount(0);
  await expect(page.getByTestId("avatar-file")).toHaveCount(0);
  const dt = await page.evaluateHandle(() => {
    const d = new DataTransfer();
    d.items.add(new File([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])], "this-computer.png", { type: "image/png" }));
    return d;
  });
  await page.getByTestId("avatar-view").dispatchEvent("drop", { dataTransfer: dt });
  await page.waitForTimeout(500);
  expect(ops.filter((o) => o.op === "bots.set_avatar")).toEqual([]);
  // the rest of the bot page still reads from the server
  expect(ops.some((o) => o.op === "bots.info" || o.op === "models.options")).toBe(true);
});

test("on a server provider sign-in is the server's: no Add key or Nous button, this computer's hermes is never asked", async ({ page }) => {
  await stub(page, { mode: "remote", host: "demo@vps", label: "VPS" });
  await page.addInitScript(() => {
    const w = window as unknown as Record<string, unknown>;
    const hostCalls: string[][] = [];
    w.__authCalls = hostCalls;
    w.__omherAuthHost = { open: async (p: string) => void hostCalls.push(["open_hermes_auth", p]) };
    w.__omherSignInHost = { open: async (p: string) => void hostCalls.push(["open_hermes_sign_in", p]) };
  });
  await mockOp("mock.reset");
  try {
    // verify.md finding 3: a remote bot that reports not ready
    await mockOp("mock.ready", { bot: "friren", ok: false });
    await page.goto("/");
    await page.getByTestId("bot-friren").click();
    const block = page.getByTestId("connect-block");
    await expect(block).toBeVisible();
    await expect(block.getByTestId("connect-on-server")).toContainText("hermes auth add nous");
    await expect(block.getByTestId("connect-nous")).toHaveCount(0);
    await expect(block.getByTestId("connect-openai-codex")).toHaveCount(0);
    // Settings › Providers: the line says where to sign in; there is no Add key anywhere
    await page.getByTestId("nav-settings").click();
    await page.getByTestId("settings-nav-providers").click();
    await expect(page.getByTestId("providers-on-server")).toContainText("hermes auth add <provider>");
    await expect(page.getByTestId("providers-add-key")).toHaveCount(0);
    await expect(page.locator('[data-testid^="provider-key-"]')).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __authCalls: string[][] }).__authCalls)).toEqual([]);
  } finally {
    await mockOp("mock.reset");
  }
});

test("on a server a saved oh-my-hermes terminal is not started, by itself or by Resume; a Shell row never types omh", async ({ page }) => {
  await stub(page, { mode: "remote", host: "demo@vps", label: "VPS" });
  // verify.md finding 4: OMH installed here, a running TERMINALS omh row, and a Shell row that had omh in front
  await seedResume(
    page,
    {
      bot: "kami",
      view: "session",
      session: "s91",
      sessions: [
        { id: "s91", agent: "omh", open: "terminal", view: "terminal", running: true, cwd: "/fixture/local/omh-work", startedAt: 100000, linkId: "abcdefgh23" },
        { id: "s92", agent: "shell", view: "terminal", running: true, cwd: "/fixture/local/shell-work", startedAt: 100001, fgCli: "omh", linkId: "abcdefgh24" },
      ],
    },
    ["claude", "codex", "omh"],
  );
  await page.goto("/");
  await expect(page.getByTestId("session-s91")).toBeVisible();
  // the omh row is paused, saying why
  await expect(page.getByTestId("session-paused")).toContainText("oh-my-hermes on this computer isn’t started");
  await page.getByTestId("session-resume").click();
  await expect(page.getByTestId("session-paused")).toBeVisible();
  // the Shell row's own shell is this computer's terminal and starts; nothing is typed into it
  await expect.poll(async () => (await shellCalls(page)).filter((c) => c.op === "start").length, { timeout: 10_000 }).toBe(1);
  await page.waitForTimeout(4_000);
  expect((await sessionCalls(page)).filter((c) => c.op === "start")).toEqual([]);
  expect((await shellCalls(page)).filter((c) => c.op === "write")).toEqual([]);
  // the rows are kept as saved, for when this computer is used again
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("omher.resume") || "null"));
  expect(saved.sessions.find((x: { id: string }) => x.id === "s91")).toMatchObject({ agent: "omh", cwd: "/fixture/local/omh-work" });
});
