// The folder a thread runs in reaches its row: a restored row listed without one (a thread this bridge has not
// attached yet) takes the cwd `thread.open` returns, so the terminal panel's next tab starts there.
import { describe, expect, it } from "vitest";
import { createStore, type BridgeLike } from "../state/store";

function bridgeWith(listed: string, opened: string): BridgeLike {
  const row = { thread: "t1", title: "restored", cwd: listed, started_at: 1, running: false, needs: false, message_count: 2 };
  return {
    connect() {},
    onAny: () => () => {},
    onStatus: () => () => {},
    async request(op: string) {
      if (op === "thread.list") return { threads: [row] };
      if (op === "thread.open")
        return { thread: "t1", session_id: "t1", title: "restored", cwd: opened, messages: [], running: false, model: "m", provider: "p", reasoning: "high" };
      throw new Error(`unexpected ${op}`);
    },
  } as unknown as BridgeLike;
}

describe("a restored thread's folder", () => {
  it("is the cwd thread.open returns when the list had none", async () => {
    const st = createStore(bridgeWith("", "/work/restored"));
    await st.actions.loadThreads("kami");
    expect(st.getState().threads.kami[0].cwd).toBe("");
    await st.actions.openThread("kami", "t1");
    expect(st.getState().threads.kami[0].cwd).toBe("/work/restored");
    // the bridge lists it again (a thread event, a reconnect) still without a folder: the row keeps the one it learned
    await st.actions.loadThreads("kami");
    expect(st.getState().threads.kami[0].cwd).toBe("/work/restored");
  });

  it("an open that names no folder keeps the one the list gave", async () => {
    const st = createStore(bridgeWith("/work/listed", ""));
    await st.actions.loadThreads("kami");
    await st.actions.openThread("kami", "t1");
    expect(st.getState().threads.kami[0].cwd).toBe("/work/listed");
  });
});
