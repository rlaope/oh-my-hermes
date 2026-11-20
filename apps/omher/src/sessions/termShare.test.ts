import { describe, expect, it, vi } from "vitest";
import { cleanPrompt, createTermShare, MockShare, statusOf, type ShareRequest, type ShareStatus } from "./termShare";
import type { SessionRec } from "./agents";
import type { getSessions } from "./sessions";

const rec = (over: Partial<SessionRec> = {}): SessionRec => ({ id: "s1", linkId: "abcdefgh23", agent: "shell", cwd: "/home/you/code/web-app", startedAt: 1_700_000_000_000, status: "running", view: "terminal", ...over });

function world(list: SessionRec[], o: { canType?: boolean; types?: boolean } = {}) {
  const typed: { id: string; text: string }[] = [];
  const io = { canType: o.canType ?? true, types: o.types ?? true };
  const files: Record<string, ShareStatus> = {};
  const inbox: ShareRequest[] = [];
  const g = { __omherShareFiles: files, __omherMockInbox: inbox };
  const host = new MockShare(g);
  const st = { list, agents: null, unseen: {} };
  const sessions = {
    getState: () => st,
    byLink: (l: string) => st.list.find((r) => r.linkId === l) ?? null,
    typeAllowed: vi.fn(async (id: string, text: string) => {
      if (!io.types) return false;
      typed.push({ id, text });
      return true;
    }),
    canType: () => io.canType,
  } as unknown as ReturnType<typeof getSessions>;
  const share = createTermShare(host, () => sessions);
  const ask = (prompt: string, link = "abcdefgh23", from = "Kami") => g.__omherMockInbox.push({ id: `${g.__omherMockInbox.length}`, link, prompt, from, session: "x" });
  return { share, typed, g, st, ask, io };
}

describe("a bot's request to type into a terminal", () => {
  it("types nothing until the person allows it, and nothing at all when they deny it", async () => {
    const w = world([rec()]);
    await w.share.publish();
    w.ask("rm -rf build\n");
    await w.share.poll();
    expect(w.share.pending()).toHaveLength(1);
    expect(w.typed).toEqual([]);
    // more looks, more time: still nothing typed
    await w.share.publish();
    await w.share.poll();
    expect(w.typed).toEqual([]);
    await w.share.answer(w.share.pending()[0]!.key, "deny");
    expect(w.share.pending()).toEqual([]);
    expect(w.typed).toEqual([]);
  });

  it("Allow once types that one prompt; the next request asks again", async () => {
    const w = world([rec()]);
    await w.share.publish();
    w.ask("run the tests");
    await w.share.poll();
    await w.share.answer(w.share.pending()[0]!.key, "once");
    expect(w.typed).toEqual([{ id: "s1", text: "run the tests" }]);
    w.ask("again");
    await w.share.poll();
    expect(w.share.pending()).toHaveLength(1);
    expect(w.typed).toHaveLength(1);
  });

  it("every request asks on its own card: two from Kami are two cards, and the second types nothing until its own Allow", async () => {
    const w = world([rec()]);
    await w.share.publish();
    w.ask("one", "abcdefgh23", "Kami");
    await w.share.poll();
    await w.share.answer(w.share.pending()[0]!.key, "once");
    expect(w.typed.map((x) => x.text)).toEqual(["one"]);
    w.ask("two", "abcdefgh23", "Kami");
    w.ask("three", "abcdefgh23", "Kami");
    await w.share.poll();
    expect(w.share.pending().map((p) => [p.from, p.prompt])).toEqual([["Kami", "two"], ["Kami", "three"]]);
    // more looks: nothing more typed
    await w.share.publish();
    await w.share.poll();
    expect(w.typed.map((x) => x.text)).toEqual(["one"]);
    await w.share.answer(w.share.pending()[0]!.key, "once");
    expect(w.typed.map((x) => x.text)).toEqual(["one", "two"]);
    expect(w.share.pending().map((p) => p.prompt)).toEqual(["three"]);
    // there is no standing grant to give
    expect("granted" in w.share).toBe(false);
  });

  it("drops requests for unknown links, chat sessions and drafts, and takes control characters out", async () => {
    const w = world([rec(), rec({ id: "s3", linkId: "cccccccccc", agent: "claude", view: "chat" }), rec({ id: "s4", linkId: "dddddddddd", status: "draft" })]);
    await w.share.publish();
    w.share.arrive([
      { id: "a", link: "qqqqqqqqqq", prompt: "x", from: "b", session: "" },
      { id: "b", link: "../../etc", prompt: "x", from: "b", session: "" },
      { id: "c", link: "cccccccccc", prompt: "x", from: "b", session: "" },
      { id: "d", link: "dddddddddd", prompt: "x", from: "b", session: "" },
      { id: "e", link: "abcdefgh23", prompt: "\x07\x1b", from: "b", session: "" },
      { id: "f", link: "abcdefgh23", prompt: "go\x1b[2J\r\nnow\x9b", from: "b", session: "" },
    ]);
    expect(w.share.pending().map((p) => [p.id, p.prompt])).toEqual([["f", "go[2J\nnow"]]);
    expect(cleanPrompt("a\tb\x00c\x7fd\ne")).toBe("abcd\ne");
  });

  it("an Allow that types nothing keeps the card with its line", async () => {
    const w = world([rec()], { types: false });
    await w.share.publish();
    w.ask("run the tests");
    await w.share.poll();
    const key = w.share.pending()[0]!.key;
    await w.share.answer(key, "once");
    expect(w.typed).toEqual([]);
    expect(w.share.pending()).toHaveLength(1);
    expect(w.share.pending()[0]).toMatchObject({ key, failed: true });
    await w.share.answer(key, "once");
    expect(w.share.pending()).toHaveLength(1);
    // it types once the terminal takes input again
    w.io.types = true;
    await w.share.answer(key, "once");
    expect(w.typed.map((x) => x.text)).toEqual(["run the tests"]);
    expect(w.share.pending()).toEqual([]);
  });

  it("Allow on a terminal that takes no input now types nothing and keeps the card", async () => {
    const w = world([rec()]);
    await w.share.publish();
    w.io.canType = false;
    w.ask("two");
    await w.share.poll();
    expect(w.share.pending().map((p) => p.prompt)).toEqual(["two"]);
    await w.share.answer(w.share.pending()[0]!.key, "once");
    expect(w.typed).toEqual([]);
    expect(w.share.pending()[0]?.failed).toBe(true);
  });

  it("a request that waits goes when its session is closed", async () => {
    const w = world([rec()]);
    await w.share.publish();
    w.ask("x");
    await w.share.poll();
    expect(w.share.pending()).toHaveLength(1);
    w.st.list = [];
    await w.share.publish();
    expect(w.share.pending()).toEqual([]);
    expect(w.typed).toEqual([]);
  });
});

describe("the status file", () => {
  it("is written for each TERMINALS session, rewritten only on change, removed when it is gone", async () => {
    const w = world([rec(), rec({ id: "s9", linkId: "eeeeeeeeee", status: "draft" })]);
    await w.share.publish(1_700_000_005_000);
    expect(Object.keys(w.g.__omherShareFiles)).toEqual(["abcdefgh23"]);
    expect(w.g.__omherShareFiles.abcdefgh23).toMatchObject({ title: "Shell", agent: "shell", cwd: "/home/you/code/web-app", started: 1_700_000_000_000, lastLine: "" });
    w.st.list = [];
    await w.share.publish();
    expect(w.g.__omherShareFiles).toEqual({});
  });

  it("says ended or done for a session that stopped", () => {
    expect(statusOf(rec({ status: "exited", exitCode: 0 }), null, undefined, 0)?.state).toBe("done");
    expect(statusOf(rec({ status: "exited", exitCode: 2 }), null, undefined, 0)?.state).toBe("ended");
    expect(statusOf(rec({ paused: true }), null, undefined, 0)?.state).toBe("ended");
    expect(statusOf(rec({ linkId: undefined }), null, undefined, 0)).toBeNull();
  });
});

describe("a bot row's preview", () => {
  it("shows an omher terminal link as that terminal's title, never the raw address", async () => {
    const { getSessions } = await import("./sessions");
    const { plain } = await import("../sidebar/BotRow");
    const ss = getSessions();
    const id = ss.startTerminal("shell", "/w/preview")!;
    ss.rename(id, "checkout build");
    const link = ss.linkOf(id)!;
    expect(plain(`The build runs in ${link} now.`)).toBe("The build runs in checkout build now.");
    expect(plain("Old one: omher://terminal/zzzzzzzzzz")).toBe("Old one: Terminal not on this computer");
    expect(plain(`[the build](${link})`)).toBe("the build");
    expect(plain("no links here")).toBe("no links here");
  });
});
