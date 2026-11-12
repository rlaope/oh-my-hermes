// Files in a SESSIONS chat: the pure helpers (which pictures go to the agent as its image input, the message that
// names the other files, the shell quoting of a dropped path, the restart book), and the sessions store sending
// files with the mock host, in a running chat and in a draft, failing without sending, and closing removing them.
import { describe, expect, it } from "vitest";
import { bytesOf, inlinePicture, INLINE_MAX, parseSentFiles, putSentFiles, shellQuote, wireText } from "./attach";
import { MockHost, type MockCall } from "./host";
import { createSessions } from "./sessions";
import { createStore, type BridgeLike, type OutFile } from "../state/store";

describe("attach helpers", () => {
  it("pictures the agents read themselves, up to 5 MB; everything else is named by path", () => {
    expect(inlinePicture("a.PNG", 10)).toBe(true);
    expect(inlinePicture("shot.jpeg", INLINE_MAX)).toBe(true);
    expect(inlinePicture("shot.jpeg", INLINE_MAX + 1)).toBe(false);
    expect(inlinePicture("logo.svg", 10)).toBe(false);
    expect(inlinePicture("notes.txt", 10)).toBe(false);
    expect(inlinePicture("scan.pdf", 10)).toBe(false);
  });

  it("the message names each saved copy after the text, in plain words", () => {
    expect(wireText("  hi ", [])).toBe("hi");
    expect(wireText("read it", ["/h/.omher/session-files/s1/1-notes.txt"])).toBe(
      "read it\n\nAttached file (a copy omher saved; open it with your tools):\n- /h/.omher/session-files/s1/1-notes.txt",
    );
    expect(wireText("", ["/a/1-x.pdf", "/a/2-y.csv"])).toBe("Attached files (copies omher saved; open them with your tools):\n- /a/1-x.pdf\n- /a/2-y.csv");
  });

  it("a dropped path is typed bare when plain, else quoted for the shell", () => {
    expect(shellQuote("/Users/you/.omher/session-files/s1/1-a.png")).toBe("/Users/you/.omher/session-files/s1/1-a.png");
    expect(shellQuote("/Users/you/My Shots/1-it's.png")).toBe("'/Users/you/My Shots/1-it'\\''s.png'");
    expect(shellQuote("/a/$(rm -rf ~).png")).toBe("'/a/$(rm -rf ~).png'");
    expect(shellQuote("C:\\Users\\you\\.omher\\a b.png", true)).toBe('"C:\\Users\\you\\.omher\\a b.png"');
  });

  it("base64 to bytes", () => {
    expect([...bytesOf("AP8Q")]).toEqual([0, 255, 16]);
  });

  it("the restart book keeps well-formed entries only, at most 40 per session", () => {
    const f = { name: "a.png", size: 3, kind: "image" as const, path: "/h/.omher/session-files/s1/1-a.png" };
    expect(parseSentFiles("{not json")).toEqual({});
    expect(parseSentFiles(JSON.stringify({ "../x": { m: { ts: 1, text: "", files: [f] } } }))).toEqual({});
    expect(parseSentFiles(JSON.stringify({ s1: { m: { ts: 1, text: "", files: [{ ...f, kind: "exe" }] } } }))).toEqual({});
    expect(parseSentFiles(JSON.stringify({ s1: { m: { ts: 1, text: "x", files: [f], extra: 1 } } }))).toEqual({ s1: { m: { ts: 1, text: "x", files: [f] } } });
    let book = {};
    for (let i = 0; i < 45; i++) book = putSentFiles(book, "s1", String(i), { ts: i, text: "", files: [f] });
    expect(Object.keys((book as Record<string, object>).s1)).toHaveLength(40);
    expect(Object.keys((book as Record<string, object>).s1)[0]).toBe("5");
  });
});

// ---- the sessions store with the mock host ------------------------------------------------------

function bridgeStub(): BridgeLike {
  return {
    connect: async () => undefined,
    onAny: () => () => {},
    onStatus: () => () => {},
    request: (async () => ({})) as BridgeLike["request"],
  };
}

function setup() {
  const g: Record<string, unknown> = { __omherMockAgents: ["claude", "codex", "omo", "omh"] };
  const host = new MockHost(g);
  const store = createStore(bridgeStub());
  const storage = new Map<string, string>();
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (k: string) => storage.get(k) ?? null,
    setItem: (k: string, v: string) => void storage.set(k, v),
    removeItem: (k: string) => void storage.delete(k),
  };
  const ss = createSessions(host, () => store);
  const calls = () => (g.__omherSessionCalls as MockCall[] | undefined) ?? [];
  return { ss, store, calls, storage, g, host };
}

const out = (name: string, text: string, kind: OutFile["kind"] = "file"): OutFile => ({
  name,
  size: text.length,
  kind,
  url: null,
  attach: kind === "image" ? "image" : "file",
  read: async () => btoa(text),
});

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function running(ss: ReturnType<typeof setup>["ss"], agent: "claude" | "codex" | "omo" = "claude") {
  await ss.loadAgents();
  const id = ss.draft(agent);
  ss.setDraft(id, { cwd: "/w/app" });
  await ss.start(id, "/status");
  await wait(50);
  return id;
}

describe("files in a session chat", () => {
  it("a running chat saves each file in the session's folder; pictures go as images, others by path", async () => {
    const { ss, store, calls } = setup();
    const id = await running(ss);
    await ss.sendFiles(id, "what is this?", [out("shot.png", "PNGDATA", "image"), out("notes.txt", "a\nb\n")]);
    const saves = calls().filter((c) => c.op === "file.save");
    expect(saves.map((c) => [c.session, c.name, c.size])).toEqual([
      [id, "shot.png", 7],
      [id, "notes.txt", 4],
    ]);
    const send = calls().filter((c) => c.op === "chat.input").pop()!;
    expect(send.input).toMatchObject({
      kind: "send",
      text: `what is this?\n\nAttached file (a copy omher saved; open it with your tools):\n- /Users/you/.omher/session-files/${id}/1-notes.txt`,
      images: [`/Users/you/.omher/session-files/${id}/1-shot.png`],
    });
    // the bubble shows the text as typed and both files
    const user = store.getState().chats[ss.chatKey(id)!].items.filter((i) => i.kind === "user").pop()!;
    expect(user).toMatchObject({ text: "what is this?" });
    expect((user as { files: { name: string }[] }).files.map((f) => f.name)).toEqual(["shot.png", "notes.txt"]);
  });

  it("a draft's first message carries its files: saved before the agent starts, then sent with the first prompt", async () => {
    const { ss, store, calls } = setup();
    await ss.loadAgents();
    const id = ss.draft("codex");
    ss.setDraft(id, { cwd: "/w/app" });
    expect(await ss.start(id, "", undefined, [out("word.png", "PNG", "image")])).toBe(true);
    const ops = calls().map((c) => c.op).filter((o) => o !== "reset");
    expect(ops.slice(0, 3)).toEqual(["file.save", "chat.start", "chat.input"]);
    const send = calls().find((c) => c.op === "chat.input")!;
    expect(send.input).toEqual({ kind: "send", text: "", images: [`/Users/you/.omher/session-files/${id}/1-word.png`], id: expect.stringMatching(/^local-/) });
    const user = store.getState().chats[ss.chatKey(id)!].items.find((i) => i.kind === "user")!;
    expect((user as { files: unknown[] }).files).toHaveLength(1);
  });

  it("a file that cannot be saved sends nothing, starts nothing and gives the error back", async () => {
    const { ss, calls, g } = setup();
    const id = await running(ss);
    const before = calls().filter((c) => c.op === "chat.input").length;
    g.__omherFileSaveError = "disk full";
    await expect(ss.sendFiles(id, "x", [out("a.txt", "x")])).rejects.toThrow("Couldn't attach a.txt · disk full");
    expect(calls().filter((c) => c.op === "chat.input")).toHaveLength(before);
    // in a draft: the agent does not start and the draft stays
    const d = ss.draft("claude");
    ss.setDraft(d, { cwd: "/w/app" });
    await expect(ss.start(d, "hi", undefined, [out("a.txt", "x")])).rejects.toThrow("disk full");
    expect(ss.getState().list.find((r) => r.id === d)!.status).toBe("draft");
    expect(calls().filter((c) => c.op === "chat.start")).toHaveLength(1);
  });

  it("closing a session removes its saved files and forgets its sent-files record", async () => {
    const { ss, calls, storage } = setup();
    const id = await running(ss);
    await ss.sendFiles(id, "", [out("a.txt", "x")]);
    expect(JSON.parse(storage.get("omher.sessions.files")!)[id]).toBeTruthy();
    ss.close(id);
    await wait(20);
    expect(calls().some((c) => c.op === "file.remove" && c.session === id)).toBe(true);
    expect(JSON.parse(storage.get("omher.sessions.files")!)[id]).toBeUndefined();
  });

  it("after a restart a sent bubble shows its files again; folders of sessions that are gone are pruned", async () => {
    const first = setup();
    const id = await running(first.ss);
    await first.ss.sendFiles(first.ss.getState().list[0].id, "look", [out("a.png", "PNG", "image")]);
    const book = first.storage.get("omher.sessions.files")!;
    const userMsg = first.store.getState().chats[first.ss.chatKey(id)!].messages.filter((m) => m.role === "user").pop()!;
    // a new page load: the same storage, the snapshot's messages, a host that still has the saved copy
    const again = setup();
    again.storage.set("omher.sessions.files", book);
    const host = again.host as unknown as { files: Map<string, Uint8Array> };
    host.files.set(`/Users/you/.omher/session-files/${id}/1-a.png`, new Uint8Array([1, 2]));
    const fresh = createSessions(again.host, () => again.store);
    fresh.restore([{ id, agent: "claude", cwd: "/w/app", startedAt: 1, view: "chat", running: false, messages: [{ ...userMsg, id: userMsg.id }] }]);
    await wait(30);
    const items = again.store.getState().chats[fresh.chatKey(id)!].items.filter((i) => i.kind === "user");
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ text: "look" });
    expect((items[0] as { files: { name: string; url: string | null }[] }).files).toEqual([{ name: "a.png", size: 3, kind: "image", url: expect.stringMatching(/^blob:/) }]);
    expect(again.calls().find((c) => c.op === "file.prune")).toMatchObject({ keep: [id] });
  });
});
