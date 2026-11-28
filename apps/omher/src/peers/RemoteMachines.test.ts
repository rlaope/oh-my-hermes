import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import { linkLine } from "./RemoteMachines";
import type { PeerStatus } from "./host";

const base: PeerStatus = { id: "mini", label: "Mac mini", host: "mini", state: "connected", attempt: 0 };
const NOW = 1_800_000_000_000;

describe("Remote machines' link line", () => {
  afterEach(() => setLang("en"));

  it("says how long a link is up, when it last was, and when the next try is", () => {
    expect(linkLine(base, NOW)).toBe("");
    expect(linkLine({ ...base, connected_at: NOW - 3 * 60_000 }, NOW)).toBe("up for 3m");
    const waiting: PeerStatus = { ...base, state: "reconnecting", attempt: 3, connected_at: NOW - 40_000, retry_at: NOW + 8_000 };
    expect(linkLine(waiting, NOW)).toBe("next try in 8s · last connected 40s ago");
    // a link that never came up has only its countdown; a past retry time reads as 0s, never negative
    expect(linkLine({ ...base, state: "reconnecting", retry_at: NOW - 500 }, NOW)).toBe("next try in 0s");
    expect(linkLine({ ...base, state: "failed", connected_at: NOW - 2 * 3_600_000 }, NOW)).toBe("last connected 2h ago");
  });

  it("a link that is down says when it was last connected from its drop, not from when it came up", () => {
    const up = NOW - 3 * 3_600_000;
    const dropped: PeerStatus = {
      ...base,
      state: "reconnecting",
      attempt: 1,
      connected_at: up,
      retry_at: NOW + 2_000,
      events: [
        { at: up, what: "connected" },
        { at: NOW - 60_000, what: "dropped", kind: "dropped" },
        { at: NOW - 60_000, what: "retrying", wait: 2 },
      ],
    };
    expect(linkLine(dropped, NOW)).toBe("next try in 2s · last connected 1m ago");
    expect(linkLine({ ...dropped, state: "failed", retry_at: undefined }, NOW)).toBe("last connected 1m ago");
    // a drop before an earlier session is not this one's
    const older = { ...dropped, events: [{ at: up - 60_000, what: "dropped" as const }, ...dropped.events!] };
    expect(linkLine(older, NOW)).toBe("next try in 2s · last connected 1m ago");
    // the drop left the history (8 events): the oldest event kept after it came up is the nearest time known
    const evicted = { ...dropped, events: [{ at: NOW - 5 * 60_000, what: "retrying" as const, wait: 8 }, { at: NOW - 60_000, what: "retrying" as const, wait: 16 }] };
    expect(linkLine(evicted, NOW)).toBe("next try in 2s · last connected 5m ago");
    // while connected: still how long it has been up
    expect(linkLine({ ...dropped, state: "connected", retry_at: undefined }, NOW)).toBe("up for 3h");
  });

  it("reads in Korean", () => {
    setLang("ko");
    expect(linkLine({ ...base, state: "reconnecting", connected_at: NOW - 40_000, retry_at: NOW + 16_000 }, NOW)).toBe("16초 후 다시 시도 · 마지막 연결 40초 전");
  });
});
