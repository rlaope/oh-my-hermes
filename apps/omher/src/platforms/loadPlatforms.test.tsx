import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createStore, type BridgeLike } from "../state/store";
import type { PlatformState, PlatformsRead } from "../lib/protocol";
import { RowPlatforms } from "./PlatformSection";
import { ROW_RECONNECT_MS } from "./platforms";

const row = (over: Partial<PlatformState> = {}): PlatformState => ({
  platform: "discord",
  status: "disconnected",
  attention: true,
  since: "2020-01-02T03:04:05Z",
  logged: "2020-01-02T03:04:05Z",
  reason_kind: "discord_token_rejected",
  unknown_why: "",
  reason: "",
  guidance: "",
  restart: "hermes -p default gateway restart",
  intents: [],
  ...over,
});
const read = (bots: Record<string, PlatformState[]>, available = true): PlatformsRead => ({
  available,
  bots: Object.fromEntries(Object.entries(bots).map(([bot, platforms]) => [bot, { log: "read", platforms }])),
});

/** A bridge that answers `bots.platforms` from a queue (an Error item is thrown) and nothing else. */
function platformsBridge(answers: (PlatformsRead | Error)[]) {
  const bridge: BridgeLike = {
    connect: async () => {},
    onAny: () => () => {},
    onStatus: () => () => {},
    request: (async (op: string) => {
      if (op !== "bots.platforms") return {};
      const next = answers.shift();
      if (next instanceof Error || next === undefined) throw { code: "bridge_error", message: "gone" };
      return next;
    }) as BridgeLike["request"],
  };
  return bridge;
}

describe("loadPlatforms", () => {
  it("dispatches only when the answer changed, and keeps the last one when the ask fails", async () => {
    const first = read({ "demo-bot": [row()] });
    const changes = [
      read({ "demo-bot": [row({ status: "failed" })] }),
      read({ "demo-bot": [row({ status: "failed", since: "2020-01-02T03:05:05Z" })] }),
      read({ "demo-bot": [row({ status: "failed", since: "2020-01-02T03:05:05Z", attention: false })] }),
      read({ "demo-bot": [row({ status: "failed", since: "2020-01-02T03:05:05Z", attention: false })], "other-bot": [] }),
      read({ "other-bot": [] }),
      read({ "other-bot": [] }, false),
    ];
    const store = createStore(platformsBridge([first, structuredClone(first), ...changes, new Error("gone")]));
    let renders = 0;
    store.subscribe(() => (renders += 1));
    await store.actions.loadPlatforms();
    expect(renders).toBe(1);
    await store.actions.loadPlatforms(); // the same answer again: no re-render
    expect(renders).toBe(1);
    for (const [i, want] of changes.entries()) {
      await store.actions.loadPlatforms();
      expect(renders, `change ${i}`).toBe(2 + i);
      expect(store.getState().platforms).toEqual(want);
    }
    await store.actions.loadPlatforms(); // a thrown ask: what was last read stays
    expect(renders).toBe(1 + changes.length);
    expect(store.getState().platforms).toEqual(changes[changes.length - 1]);
  });
});

describe("the sidebar row's clock", () => {
  afterEach(() => vi.useRealTimers());

  it("a reconnect crosses ten minutes onto the row with no new answer", () => {
    const since = Date.parse("2020-01-02T03:04:05Z");
    const same = read({ "demo-bot": [row({ status: "reconnecting", attention: false, reason_kind: "transient", since: "2020-01-02T03:04:05Z" })] });
    vi.useFakeTimers();
    vi.setSystemTime(since + ROW_RECONNECT_MS - 60_000);
    expect(renderToStaticMarkup(<RowPlatforms bot="demo-bot" read={same} />)).toBe("");
    vi.setSystemTime(since + ROW_RECONNECT_MS);
    expect(renderToStaticMarkup(<RowPlatforms bot="demo-bot" read={same} />)).toContain("platform-down-demo-bot");
  });
});
