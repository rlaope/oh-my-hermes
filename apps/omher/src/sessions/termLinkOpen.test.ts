import { describe, expect, it } from "vitest";
import { getSessions } from "./sessions";
import { getStore } from "../state/store";
import { openTermLinkId } from "./termLinkOpen";

describe("opening a terminal link from outside", () => {
  it("opens the session holding the id, and only that", () => {
    const ss = getSessions();
    const a = ss.startTerminal("shell", "/w/a")!;
    const b = ss.startTerminal("shell", "/w/b")!;
    expect(getStore().getState().ui.session).toBe(b);
    const linkA = ss.getState().list.find((r) => r.id === a)!.linkId!;
    expect(openTermLinkId(linkA)).toBe(true);
    expect(getStore().getState().ui).toMatchObject({ view: "session", session: a });
  });

  it("an id no session holds, or a malformed one, opens nothing", () => {
    const before = getStore().getState().ui.session;
    expect(openTermLinkId("zzzzzzzzzz")).toBe(false);
    expect(openTermLinkId("ZZZZZZZZZZ")).toBe(false);
    expect(openTermLinkId("../../etc")).toBe(false);
    expect(getStore().getState().ui.session).toBe(before);
  });
});
