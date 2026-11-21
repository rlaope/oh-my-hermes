import { describe, expect, it } from "vitest";
import type { TimelineItem } from "../../state/store";
import { answered, quoteFor } from "./answers";

const u = (id: string, text: string, extra: object = {}): TimelineItem => ({ kind: "user", id, ts: 0, text, ...extra }) as TimelineItem;
const a = (id: string, text = "ok"): TimelineItem => ({ kind: "assistant", id, ts: 0, text });
const act = (id: string): TimelineItem => ({ kind: "activity", id, ts: 0, turn: { id, startedAt: 0, status: "", steps: [], skills: [], streaming: "" } });

describe("quoteFor: what a bot answer replies to", () => {
  it("one message: no header", () => {
    expect(quoteFor([u("u1", "hi"), a("a1")], 1)).toBeNull();
    expect(quoteFor([u("u1", "hi"), act("t1"), a("a1")], 2)).toBeNull();
  });

  it("quotes the last of several messages sent before one answer, and counts the rest", () => {
    const items = [a("a0"), u("u1", "fix the tile"), u("u2", "and the spinner\nwith seconds"), act("t1"), a("a1")];
    expect(answered(items, 4).map((m) => m.id)).toEqual(["u1", "u2"]);
    expect(quoteFor(items, 4)).toEqual({ lines: [{ id: "u1", text: "fix the tile" }, { id: "u2", text: "and the spinner with seconds" }], more: 0 });
  });

  it("says nothing for one message even with a card or notice between it and its answer", () => {
    const card: TimelineItem = { kind: "system", id: "s1", ts: 0, text: "Switched model" };
    expect(quoteFor([u("u1", "why 502?"), card, a("a1")], 2)).toBeNull();
    expect(quoteFor([u("u1", "di"), card, act("t1"), a("a1")], 3)).toBeNull();
  });

  it("quotes two messages even when only activity sits between them and the answer", () => {
    expect(quoteFor([u("u1", "one"), u("u2", "two"), act("t1"), a("a1")], 3)).toEqual({ lines: [{ id: "u1", text: "one" }, { id: "u2", text: "two" }], more: 0 });
  });

  it("a queued or steer-unknown send was not taken by the agent yet, so it does not make a second message", () => {
    expect(quoteFor([u("u1", "one"), u("u2", "two", { wait: "queued" }), a("a1")], 2)).toBeNull();
    expect(quoteFor([u("u1", "one"), u("u2", "two", { steerUnknown: true }), a("a1")], 2)).toBeNull();
  });

  it("a dropped send decides whether the count reaches two", () => {
    expect(quoteFor([u("u1", "one"), u("u2", "two", { wait: "dropped" }), a("a1")], 2)).toBeNull();
    expect(quoteFor([u("u1", "one"), u("u2", "two", { wait: "dropped" }), u("u3", "three"), a("a1")], 3)!.lines.map((l) => l.id)).toEqual(["u1", "u3"]);
  });

  it("a message with only a file is quoted by its file name", () => {
    const f = u("u2", "", { files: [{ name: "shot.png" }] });
    expect(quoteFor([u("u1", "look"), f, a("a1")], 2)).toEqual({ lines: [{ id: "u1", text: "look" }, { id: "u2", text: "shot.png" }], more: 0 });
  });

  it("a second answer after the first one gets nothing: the messages were answered", () => {
    const items = [u("u1", "one"), a("a1"), a("a2")];
    expect(quoteFor(items, 1)).toBeNull();
    expect(quoteFor(items, 2)).toBeNull();
    expect(quoteFor([u("u1", "one"), u("u2", "two"), a("a1"), a("a2")], 3)).toBeNull();
  });

  it("a failed or held send does not make a second message", () => {
    expect(quoteFor([u("u1", "one"), u("u2", "two", { error: "offline" }), a("a1")], 2)).toBeNull();
    expect(quoteFor([u("u1", "one"), { ...u("u2", "two"), held: true } as TimelineItem, a("a1")], 2)).toBeNull();
  });

  it("the answer being written (at the end) quotes the same way; a failed or dropped send is not answered", () => {
    const items = [u("u1", "one"), u("u2", "two", { error: "offline" }), u("u3", "three", { wait: "dropped" }), u("u4", "four"), act("t1")];
    expect(quoteFor(items, items.length)).toEqual({ lines: [{ id: "u1", text: "one" }, { id: "u4", text: "four" }], more: 0 });
  });

  it("keeps a long message to 140 characters and says nothing after a message nobody asked", () => {
    const long = "x".repeat(200);
    expect(quoteFor([u("u1", "a"), u("u2", long), a("a1")], 2)!.lines[1].text).toHaveLength(140);
    // at most three lines; the rest is a count
    const five = [u("u1", "1"), u("u2", "2"), u("u3", "3"), u("u4", "4"), u("u5", "5"), a("a1")];
    expect(quoteFor(five, 5)).toEqual({ lines: [{ id: "u3", text: "3" }, { id: "u4", text: "4" }, { id: "u5", text: "5" }], more: 2 });
    expect(quoteFor([a("a0"), a("a1")], 1)).toBeNull();
  });
  it("never quotes a held message: it was not sent yet", () => {
    const held = { ...u("h", "held one"), held: true };
    expect(answered([u("u1", "a"), u("u2", "b"), held, a("a1")], 3).map((m) => m.id)).toEqual(["u1", "u2"]);
  });
});
