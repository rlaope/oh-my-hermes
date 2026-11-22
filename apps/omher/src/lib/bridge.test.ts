// A bridge that died and came back listens on a new port with a new token: the client asks for the URL again before
// every dial instead of retrying the one it had.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const invoke = vi.fn<(cmd: string) => Promise<string>>();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string) => invoke(cmd) }));

import { BridgeClient } from "./bridge";

class FakeSocket {
  static all: FakeSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  drop() {
    this.readyState = 3;
    this.onclose?.();
  }
}

const OLD = "ws://127.0.0.1:51001/?token=aaa";
const NEW = "ws://127.0.0.1:51002/?token=bbb";
const win = globalThis as unknown as { window?: Record<string, unknown> };

beforeAll(async () => {
  // load the mocked module once, so the client's dynamic import of it resolves within a few microtasks
  await import("@tauri-apps/api/core");
});

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.all = [];
  invoke.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  delete win.window;
});

const client = () => new BridgeClient({ WebSocketImpl: FakeSocket as unknown as typeof WebSocket, minDelay: 10, maxDelay: 40 });

describe("reconnect after the bridge comes back", () => {
  it("in the app: asks the shell's bridge_url again and dials the new port, not the dead one", async () => {
    win.window = { __TAURI_INTERNALS__: {} };
    invoke.mockResolvedValueOnce(OLD);
    const b = client();
    const opened = b.connect();
    await vi.waitFor(() => expect(FakeSocket.all.map((s) => s.url)).toEqual([OLD]));
    FakeSocket.all[0].open();
    await opened;

    // the bridge dies; while omher starts it again the shell says so, then names the new port
    invoke.mockRejectedValueOnce("the bridge is still starting").mockResolvedValueOnce(NEW);
    const seen: string[] = [];
    b.onStatus((s) => seen.push(s));
    FakeSocket.all[0].drop();
    expect(b.status).toBe("closed");
    await vi.waitFor(async () => {
      await vi.advanceTimersByTimeAsync(10);
      expect(FakeSocket.all.map((s) => s.url)).toEqual([OLD, NEW]);
    });
    expect(invoke.mock.calls.map((c) => c[0])).toEqual(["bridge_url", "bridge_url", "bridge_url"]);

    FakeSocket.all[1].open();
    expect(b.status).toBe("open");
    expect(seen).toContain("open");
    // requests go to the new bridge
    void b.request("bots.list").catch(() => {});
    expect(FakeSocket.all[1].sent).toHaveLength(1);
    expect(FakeSocket.all[0].sent).toHaveLength(0);
    b.close();
  });

  it("in the e2e page: asks the __OMHER_BRIDGE_URL__ stand-in again", async () => {
    let url = OLD;
    const standIn = vi.fn(async () => url);
    win.window = { __OMHER_BRIDGE_URL__: standIn };
    const b = client();
    const opened = b.connect();
    await vi.advanceTimersByTimeAsync(0);
    FakeSocket.all[0].open();
    await opened;
    url = NEW;
    FakeSocket.all[0].drop();
    await vi.advanceTimersByTimeAsync(50);
    expect(standIn).toHaveBeenCalledTimes(2);
    expect(FakeSocket.all.map((s) => s.url)).toEqual([OLD, NEW]);
    b.close();
  });

  it("a fixed URL option stays fixed (peers, tests)", async () => {
    const b = new BridgeClient({ url: OLD, WebSocketImpl: FakeSocket as unknown as typeof WebSocket, minDelay: 10, maxDelay: 40 });
    const opened = b.connect();
    await vi.advanceTimersByTimeAsync(0);
    FakeSocket.all[0].open();
    await opened;
    FakeSocket.all[0].drop();
    await vi.advanceTimersByTimeAsync(50);
    expect(FakeSocket.all.map((s) => s.url)).toEqual([OLD, OLD]);
    b.close();
  });
});
