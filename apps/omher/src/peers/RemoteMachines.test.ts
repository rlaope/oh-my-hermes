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

  it("reads in Korean", () => {
    setLang("ko");
    expect(linkLine({ ...base, state: "reconnecting", connected_at: NOW - 40_000, retry_at: NOW + 16_000 }, NOW)).toBe("16초 후 다시 시도 · 마지막 연결 40초 전");
  });
});
