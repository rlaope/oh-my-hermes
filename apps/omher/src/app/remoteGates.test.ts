// Remote-only mode (rule 47): nothing of this computer goes to the server by itself or on a click. A restart's saved
// oh-my-hermes folder chat is not resumed (auto or Resume), no file is attached, and the oh-my-hermes installer is not
// run; the saved rows stay as they were for when this computer is used again. Local mode is unchanged.
import { afterEach, describe, expect, it, vi } from "vitest";
import { noteServerMode } from "./remote";
import { MockHost } from "../sessions/host";
import { createSessions } from "../sessions/sessions";
import { createAddOmh } from "../sessions/addOmh";
import { createStore, type BridgeLike } from "../state/store";
import type { SavedSession } from "./resume";
import type { GateShell } from "./BridgeGate";

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
type Req = { op: string; params: Record<string, unknown> };

function bridge(): BridgeLike & { reqs: Req[] } {
  const reqs: Req[] = [];
  const request = (async (op: string, params: Record<string, unknown> = {}) => {
    reqs.push({ op, params });
    if (op === "bots.list") return { bots: [{ name: "friren", display_name: "Friren", is_default: false, model: "m", provider: "p", description: "", status: "online", running: false }] };
    if (op === "chat.open") return { session_id: "s-friren", messages: [], running: false, model: "m", provider: "p" };
    if (op === "folder.resume" || op === "folder.open") return { session: "f1", stored: "stored-1", cwd: params.cwd, model: "m", provider: "p", messages: [], running: false };
    if (op === "chat.attach") return { path: "/srv/x" };
    if (op === "models.options") return { providers: [{ slug: "p", name: "P", models: ["m"] }], model: "m", provider: "p" };
    return {};
  }) as BridgeLike["request"];
  return { connect: async () => undefined, onAny: () => () => {}, onStatus: () => () => {}, request, reqs };
}

const saved: SavedSession = {
  id: "s47",
  agent: "omh",
  cwd: "/fixture/this-computer/project",
  startedAt: 1000,
  view: "chat",
  running: true,
  bot: "friren",
  agentSession: "20261126_120000_local001",
};
const folderOps = (b: { reqs: Req[] }) => b.reqs.filter((r) => r.op.startsWith("folder."));

afterEach(() => noteServerMode({ mode: "local" }));

describe("a saved oh-my-hermes folder chat on a server", () => {
  it("is not resumed after a restart, nor by Resume; the row keeps its folder and stored id", async () => {
    noteServerMode({ mode: "remote", host: "demo@vps" });
    const b = bridge();
    const store = createStore(b);
    const ss = createSessions(new MockHost({}), () => store);
    ss.restore([saved]);
    await store.actions.init();
    await wait(30);
    expect(folderOps(b)).toEqual([]);
    expect(ss.getState().list[0]).toMatchObject({ status: "exited", paused: true, cwd: saved.cwd, agentSession: saved.agentSession });
    await ss.resume("s47");
    expect(folderOps(b)).toEqual([]);
    expect(ss.getState().list[0]).toMatchObject({ paused: true, agentSession: saved.agentSession, error: expect.stringContaining("omher uses a server") });
    // the store refuses a folder of this computer however it is asked
    await expect(store.actions.folderResume("friren", saved.cwd, "x")).rejects.toThrow("omher uses a server");
    await expect(store.actions.folderOpen("friren", saved.cwd)).rejects.toThrow("omher uses a server");
    expect(folderOps(b)).toEqual([]);
  });

  it("in local mode the same row is attached again through folder.resume, as before", async () => {
    const b = bridge();
    const store = createStore(b);
    const ss = createSessions(new MockHost({}), () => store);
    ss.restore([saved]);
    await store.actions.init();
    await wait(30);
    expect(folderOps(b)).toEqual([{ op: "folder.resume", params: { bot: "friren", cwd: saved.cwd, stored: saved.agentSession } }]);
  });
});

describe("files on a server", () => {
  const file = { name: "this-computer.txt", size: 3, kind: "file" as const, url: null, attach: "file" as const, read: async () => "dmVyaWZ5LWZpeHR1cmU=" };

  it("sendWithFiles refuses and sends nothing: no chat.attach, no chat.send", async () => {
    const b = bridge();
    const store = createStore(b);
    await store.actions.init();
    noteServerMode({ mode: "remote", host: "demo@vps" });
    const before = b.reqs.length;
    await expect(store.actions.sendWithFiles("look", [file])).rejects.toThrow("files from this computer");
    expect(b.reqs.slice(before).map((r) => r.op)).toEqual([]);
  });

  it("in local mode the file is attached, then sent", async () => {
    const b = bridge();
    const store = createStore(b);
    await store.actions.init();
    await store.actions.sendWithFiles("look", [file]);
    expect(b.reqs.map((r) => r.op).filter((o) => o === "chat.attach" || o === "chat.send")).toEqual(["chat.attach", "chat.send"]);
  });
});

describe("adding oh-my-hermes on a server", () => {
  it("runs no installer; local mode still runs it", async () => {
    const install = vi.fn(async () => 0);
    const s = { status: async () => ({ state: "ready" as const }), retry: async () => {}, installCommand: async () => "", install } as GateShell;
    noteServerMode({ mode: "remote", host: "demo@vps" });
    const add = createAddOmh(async () => s, async () => {}, null);
    await add.run();
    expect(install).not.toHaveBeenCalled();
    expect(add.getState()).toMatchObject({ phase: "failed", error: expect.stringContaining("nothing is installed") });
    noteServerMode({ mode: "local" });
    await add.run();
    expect(install).toHaveBeenCalledTimes(1);
  });
});
