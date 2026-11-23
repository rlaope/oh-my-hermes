import { describe, expect, it } from "vitest";
import type { Layout } from "../terminal/layout";
import type { AgentInfo, SessionRec } from "./agents";
import { mergePartner, sideAt } from "./splitDrag";
import type { SplitGroup } from "./splitState";

describe("a drop on a pane", () => {
  const box = { left: 100, top: 50, width: 400, height: 200 };
  it("goes to the side whose edge is nearest the pointer", () => {
    expect(sideAt(box, 480, 150)).toBe("right");
    expect(sideAt(box, 120, 150)).toBe("left");
    expect(sideAt(box, 300, 60)).toBe("up");
    expect(sideAt(box, 300, 240)).toBe("down");
    // measured against the pane's own width and height: a wide pane's corner area goes by the nearer fraction
    expect(sideAt(box, 450, 70)).toBe("up");
    expect(sideAt(box, 490, 70)).toBe("right");
  });
});

describe("a header merge's partner", () => {
  const T = (id: string, cwd: string, o: Partial<SessionRec> = {}): SessionRec => ({ id, agent: "shell", cwd, startedAt: 0, status: "running", view: "terminal", ...o });
  // a bot's folder chat: a chat session, never a TERMINALS row
  const chat = (id: string, cwd: string): SessionRec => T(id, cwd, { agent: "claude", view: "chat" });
  const P = (n: number): Layout => ({ pane: n });
  const row = (a: Layout, b: Layout): Layout => ({ dir: "row", ratio: 0.5, a, b });
  const list = [T("s1", "/w/a"), T("s2", "/w/b"), T("s3", "/w/a"), T("s4", "/w/a/")];

  it("is the row under it in its folder, or above it when it is the last", () => {
    // /w/a holds s1, s3 and s4 (one folder however its path is spelled); s2 is another folder's
    expect(mergePartner(list, null, [], "s1")).toBe("s3");
    expect(mergePartner(list, null, [], "s3")).toBe("s4");
    expect(mergePartner(list, null, [], "s4")).toBe("s3");
  });

  it("is none for the only row of its folder: never a row of another folder", () => {
    expect(mergePartner(list, null, [], "s2")).toBeNull();
    expect(mergePartner([T("s1", "/w/a")], null, [], "s1")).toBeNull();
  });

  it("passes over what is not a TERMINALS row (a chat, a draft)", () => {
    const mixed = [T("s1", "/w/a"), chat("s2", "/w/a"), T("s3", "/w/a", { status: "draft" }), T("s4", "/w/a")];
    expect(mergePartner(mixed, null, [], "s1")).toBe("s4");
    expect(mergePartner(mixed, null, [], "s4")).toBe("s1");
    expect(mergePartner([T("s1", "/w/a"), chat("s2", "/w/a")], null, [], "s1")).toBeNull();
    // a chat is never the one dragged either
    expect(mergePartner(mixed, null, [], "s2")).toBeNull();
  });

  it("passes over a row already in another split, a full one included", () => {
    const four = [T("s1", "/w/a"), T("s2", "/w/a"), T("s3", "/w/a"), T("s5", "/w/a"), T("s6", "/w/a")];
    const two: SplitGroup[] = [{ layout: row(P(2), P(9)) }];
    expect(mergePartner(four, null, two, "s1")).toBe("s3");
    const full: SplitGroup[] = [{ layout: row(row(P(2), P(3)), row(P(5), P(9))) }];
    expect(mergePartner(four, null, full, "s1")).toBe("s6");
    expect(mergePartner(four, null, full, "s6")).toBe("s1");
    // every other row of the folder is in a split: none
    expect(mergePartner([T("s1", "/w/a"), T("s2", "/w/a")], null, two, "s1")).toBeNull();
  });

  it("asks the agents list whether a row is a terminal (an agent that opens as a chat counts only opened as a terminal)", () => {
    const agents: AgentInfo[] = [{ id: "claude", label: "Claude Code", mode: "chat", path: "/bin/claude" }];
    const rows = [T("s1", "/w/a"), T("s2", "/w/a", { agent: "claude", view: "chat" }), T("s3", "/w/a", { agent: "claude", open: "terminal" })];
    expect(mergePartner(rows, agents, [], "s1")).toBe("s3");
    // the same agent listed as a terminal agent: its row counts however it was opened
    expect(mergePartner(rows, [{ ...agents[0], mode: "terminal" }], [], "s1")).toBe("s2");
  });

  it("is none for a session already in a split (its header moves its pane instead)", () => {
    expect(mergePartner(list, null, [{ layout: row(P(1), P(2)) }], "s1")).toBeNull();
  });
});
