// The bot's face stays in the face column from send to the answer: one face, never none, never two, in the same
// column, ringed while the bot works, through typing dots -> a status line ("OMH — recalled 2 memories") -> a tool
// step -> streamed text -> done. Every DOM change is sampled (a MutationObserver runs after each React commit,
// before paint), so a commit with no face fails even if the next one puts it back. The same in a SESSIONS chat,
// where the agent's mark is the face.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
// Screenshots stay out of the repo (FACE_SHOTS dir, else Playwright's ignored test-results).
const SHOTS = process.env.FACE_SHOTS || "test-results/face-shots";
const TAG = process.env.FACE_TAG || "after";
const STATUS = "🧠 OMH — recalled 2 memories";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "f1") res(msg);
    };
    ws.send(JSON.stringify({ id: "f1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}
const emit = (...events: Record<string, unknown>[]) => mock("mock.emit", { events });

type Face = { left: number; top: number; ok: boolean; ring: boolean };
/** `line`: the live activity line's top, measured from the bottom of the person's last bubble. */
type Sample = { phase: string; faces: Face[]; line: number | null };

/** Records the faces in the live run (the rows after the last message the person sent) on every DOM change. */
async function watchFaces(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __faces: Sample[]; __faceObs?: MutationObserver };
    w.__faceObs?.disconnect();
    w.__faces = [];
    const tl = document.querySelector("[data-testid=timeline]")!;
    const sample = () => {
      const rows = [...tl.querySelectorAll(":scope > .row")];
      let lastUser = -1;
      rows.forEach((r, i) => {
        if (r.classList.contains("row-user")) lastUser = i;
      });
      const faces: Face[] = [];
      for (const r of rows.slice(lastUser + 1))
        for (const f of r.querySelectorAll<HTMLElement>("img.msg-face, [data-testid=session-face]")) {
          if (f.closest(".blank")) continue;
          const b = f.getBoundingClientRect();
          const img = f instanceof HTMLImageElement ? f : null;
          const ok = b.width > 0 && b.height > 0 && getComputedStyle(f).visibility !== "hidden" && (!img || (img.complete && img.naturalWidth > 0));
          faces.push({ left: b.left, top: b.top, ok, ring: !!f.closest(".ui-ring-w")?.querySelector(":scope > .ui-ring") });
        }
      const phase = tl.querySelector("[data-kind=streaming]")
        ? "streaming"
        : tl.querySelector("[data-kind=typing]")
          ? "typing"
          : tl.querySelector("[data-testid=activity][data-state=live]")
            ? "status"
            : "other";
      const act = tl.querySelector("[data-testid=activity][data-state=live]");
      const you = rows[lastUser]?.getBoundingClientRect().bottom;
      const line = act && you !== undefined ? Math.round((act.getBoundingClientRect().top - you) * 2) / 2 : null;
      w.__faces.push({ phase, faces, line });
    };
    sample();
    w.__faceObs = new MutationObserver(sample);
    w.__faceObs.observe(tl, { subtree: true, childList: true, attributes: true, characterData: true });
  });
}
const faceLog = (page: Page): Promise<Sample[]> => page.evaluate(() => (window as unknown as { __faces: Sample[] }).__faces);

/** Every sample of the live turn holds exactly one visible, ringed face, always at the same left edge. */
async function expectSteadyFace(page: Page) {
  const log = await faceLog(page);
  const live = log.filter((s) => s.phase !== "other");
  expect(new Set(live.map((s) => s.phase))).toEqual(new Set(["typing", "status", "streaming"]));
  const bad = live.filter((s) => s.faces.length !== 1 || !s.faces[0].ok || !s.faces[0].ring);
  expect(bad.map((s) => `${s.phase}: ${s.faces.length} face(s) ${JSON.stringify(s.faces)}`), "a live sample without exactly one ringed face").toEqual([]);
  const lefts = new Set(live.map((s) => Math.round(s.faces[0].left * 2) / 2));
  expect([...lefts], "the face's left edge moved").toHaveLength(1);
  // typing dots -> status line: the line takes the typing bubble's height, so the face and the rows stay put
  const before = live.filter((s) => s.phase !== "streaming").map((s) => s.faces[0].top);
  expect(Math.max(...before) - Math.min(...before), "the face moved up or down when the status line came").toBeLessThan(0.75);
  // status line -> streaming: the line itself does not move when the answer starts under it
  const lines = new Set(live.filter((s) => s.line !== null).map((s) => s.line));
  expect([...lines], "the activity line moved").toHaveLength(1);
  return [...lefts][0];
}

async function settled(page: Page) {
  await page.mouse.move(700, 120);
  await page.waitForTimeout(260); // the activity ticker's slide (220 ms)
}

test.beforeEach(async () => {
  await mock("mock.reset");
  await mock("mock.manual", { bot: "kami" });
});

test("a bot's face stays put from send to answer: typing, a recalled-memories status, a tool, streaming, done", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  const tl = page.getByTestId("timeline");
  // the column every finished answer's face sits in
  const column = (await tl.getByTestId("bubble-bot").first().locator("img.msg-face").boundingBox())!.x;
  await watchFaces(page);

  await page.getByTestId("composer").fill("why do the 502s come back?");
  await page.keyboard.press("Enter");
  await expect(tl.getByTestId("typing")).toBeVisible();

  await emit({ event: "status", bot: "kami", text: STATUS });
  await expect(tl.locator("[data-testid=activity][data-state=live]").getByTestId("activity-text")).toHaveText(STATUS);
  await expect(tl.getByTestId("typing")).toHaveCount(0);
  await settled(page);

  await emit({ event: "tool.start", bot: "kami", tool_id: "fb1", name: "terminal", detail: "grep 502 gateway.log" });
  await expect(tl.locator("[data-testid=activity][data-state=live]").getByTestId("activity-text")).toContainText("grep 502 gateway.log");
  await emit({ event: "tool.end", bot: "kami", tool_id: "fb1", name: "terminal", ok: true }, { event: "thinking", bot: "kami" });
  await settled(page);

  await emit({ event: "delta", bot: "kami", text: "The idle timeout on the upstream" });
  await expect(tl.getByTestId("bubble-streaming")).toContainText("idle timeout");
  await emit({ event: "delta", bot: "kami", text: " pool is shorter than the gateway's." });
  await expect(tl.getByTestId("bubble-streaming")).toContainText("gateway's.");
  await settled(page);

  const left = await expectSteadyFace(page);
  expect(Math.abs(left - column)).toBeLessThan(0.75);

  // done: as before, the collapsed summary line, then the answer with the face beside it, no ring left
  await emit(
    { event: "message", bot: "kami", id: "fb-a1", text: "The idle timeout on the upstream pool is shorter than the gateway's." },
    { event: "turn.end", bot: "kami", outcome: "done" },
  );
  const act = tl.getByTestId("activity").last();
  await expect(act).toHaveAttribute("data-state", "done");
  await expect(act.getByTestId("activity-text")).toHaveText(/^Worked for \d+s · 1 step$/);
  const answer = tl.getByTestId("bubble-bot").last();
  await expect(answer).toContainText("idle timeout");
  await expect(answer.locator("img.msg-face:not(.blank)")).toBeVisible();
  await expect(tl.locator("[data-testid=face-ring], [data-testid=typing-ring]")).toHaveCount(0);
  await expect(act.locator("img.msg-face")).toHaveCount(0);
  const log = await faceLog(page);
  const end = log[log.length - 1];
  expect(end.phase).toBe("other");
  expect(end.faces).toHaveLength(1);
  expect(Math.abs(end.faces[0].left - column)).toBeLessThan(0.75);
});

test("a SESSIONS chat keeps the agent's mark in the face column the same way", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/work/api";
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-omh").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  const chat = page.getByTestId("session-chat");
  const tl = chat.getByTestId("timeline");
  await page.getByTestId("composer").fill("what is here?");
  await page.keyboard.press("Enter");
  await expect(tl.getByTestId("typing")).toBeVisible();
  await watchFaces(page);
  const calls: { op: string; params: { session?: string } }[] = (await mock("mock.calls")).calls;
  const session = calls.find((c) => c.op === "chat.send" && c.params.session)!.params.session!;
  const ev = (event: string, extra: Record<string, unknown> = {}) => ({ event, bot: "kami", session, ...extra });

  await emit(ev("status", { text: STATUS }));
  await expect(tl.locator("[data-testid=activity][data-state=live]").getByTestId("activity-text")).toHaveText(STATUS);
  await emit(ev("tool.start", { tool_id: "fs1", name: "terminal", detail: "ls /Users/you/work/api" }));
  await expect(tl.locator("[data-testid=activity][data-state=live]").getByTestId("activity-text")).toContainText("ls /Users/you/work/api");
  await emit(ev("tool.end", { tool_id: "fs1", name: "terminal", ok: true }));
  await emit(ev("delta", { text: "A small API server." }));
  await expect(tl.getByTestId("bubble-streaming")).toContainText("A small API server.");
  await settled(page);
  await expectSteadyFace(page);

  await emit(ev("message", { id: "fs-a1", text: "A small API server." }), ev("turn.end", { outcome: "done" }));
  await expect(tl.getByTestId("activity").last()).toHaveAttribute("data-state", "done");
  await expect(tl.getByTestId("bubble-bot").last().getByTestId("session-face")).toBeVisible();
  await expect(tl.locator("[data-testid=face-ring], [data-testid=typing-ring]")).toHaveCount(0);
});

// Retina, like the Macs omher runs on. The three moments of one turn, each theme.
test.describe("screenshots", () => {
  test.use({ deviceScaleFactor: 2 });
  for (const theme of ["dark", "light"] as const) {
    test(`screenshot face-blink-${theme}: typing, status line, streaming`, async ({ page }) => {
      mkdirSync(SHOTS, { recursive: true });
      await page.emulateMedia({ colorScheme: theme });
      await page.goto("/");
      await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
      const tl = page.getByTestId("timeline");
      await expect(tl.getByTestId("bubble-user").first()).toBeVisible();
      const shot = async (name: string) => {
        await settled(page);
        // hold the ring part-way round and the dots mid-hop
        await page.evaluate(() => {
          for (const a of document.getAnimations()) {
            const name = (a as CSSAnimation).animationName ?? "";
            a.pause();
            if (name === "ui-ring-turn") a.currentTime = 2850 + Number(a.effect?.getTiming().delay ?? 0);
            else if (name === "ui-typing-hop") a.currentTime = 300;
          }
        });
        const box = (await tl.boundingBox())!;
        await page.screenshot({
          path: join(SHOTS, `face-blink-${TAG}-${name}-${theme}.png`),
          clip: { x: box.x, y: box.y + box.height - 300, width: box.width, height: 300 },
        });
        await page.evaluate(() => document.getAnimations().forEach((a) => a.play()));
      };
      await page.getByTestId("composer").fill("why do the 502s come back?");
      await page.keyboard.press("Enter");
      await expect(tl.getByTestId("typing")).toBeVisible();
      await shot("1-typing");
      await emit({ event: "status", bot: "kami", text: STATUS });
      await expect(tl.locator("[data-testid=activity][data-state=live]").getByTestId("activity-text")).toHaveText(STATUS);
      await shot("2-status");
      await emit(
        { event: "tool.start", bot: "kami", tool_id: "fx1", name: "terminal", detail: "grep 502 gateway.log" },
        { event: "tool.end", bot: "kami", tool_id: "fx1", name: "terminal", ok: true },
        { event: "delta", bot: "kami", text: "The idle timeout on the upstream pool is shorter than the gateway's." },
      );
      await expect(tl.getByTestId("bubble-streaming")).toContainText("gateway's.");
      await shot("3-streaming");
      await emit({ event: "message", bot: "kami", id: "fx-a1", text: "The idle timeout on the upstream pool is shorter than the gateway's." }, { event: "turn.end", bot: "kami", outcome: "done" });
    });
  }
});
