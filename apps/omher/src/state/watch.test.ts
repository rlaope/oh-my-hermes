// Watch results: a delivered automation's answer is one tagged message (unread +1, a "<bot> · <watch>" note), its
// routine.ran draws nothing, and answers that came in while omher was closed count exactly, under one note.
import { describe, expect, it } from "vitest";
import { initialState, newWatchRows, reduce, selectUnreadTotal, type Action, type AppState } from "./store";
import { noteFor, watchMissedNote } from "../lib/notify";
import { badgeCount } from "../app/badge";
import type { BridgeEvent, Msg } from "../lib/protocol";

const T0 = 1_800_000_000_000;
const ev = (s: AppState, e: BridgeEvent, now = T0) => reduce(s, { type: "event", ev: e, now } as Action);
const base = (): AppState => ({ ...initialState(), selectedBot: "kami" });

describe("watch results", () => {
  it("a hit on a bot not open: one tagged answer, unread 1, no routine line", () => {
    let s = base();
    s = ev(s, { event: "routine.ran", bot: "friren", routine_id: "j1", name: "deploys", status: "ok", ts: 1, delivered: "friren" });
    expect(s.chats.friren?.items ?? []).toEqual([]);
    expect(s.unread.friren ?? 0).toBe(0);
    s = ev(s, { event: "message", bot: "friren", id: "138428", text: "Deploy failed\nmore", watch: { name: "deploys", ts: 2 } });
    const items = s.chats.friren.items;
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "assistant", watch: { name: "deploys", ts: 2 } });
    expect(s.unread.friren).toBe(1);
    expect(selectUnreadTotal(s)).toBe(1);
    expect(badgeCount(selectUnreadTotal(s))).toBe(1);
  });

  it("an undelivered routine.ran (a failure, or a job that is not bot-chat) still draws its line", () => {
    const s = ev(base(), { event: "routine.ran", bot: "friren", routine_id: "j1", name: "deploys", status: "error", ts: 1 });
    expect(s.chats.friren.items.map((i) => i.kind)).toEqual(["routine"]);
    expect(s.unread.friren).toBe(1);
  });

  it("the note is '<bot> · <watch>' with the answer's first line", () => {
    const n = noteFor(
      { event: "message", bot: "friren", id: "1", text: "\n**Deploy failed** on main\nsecond line", watch: { name: "deploys", ts: 2 } },
      { name: () => "Friren", watching: () => false },
    );
    expect(n).toEqual({ title: "Friren · deploys", body: "Deploy failed on main", bot: "friren", tag: "friren:watch" });
  });

  it("answers missed while closed: exact count, one summary note", () => {
    const msgs: Msg[] = Array.from({ length: 40 }, (_, i) => ({ id: `w${i}`, role: "assistant", text: `match ${i}`, ts: 100 + i, watch: { name: "deploys", ts: 100 + i } }));
    const old: Msg = { id: "old", role: "assistant", text: "seen", ts: 50, watch: { name: "deploys", ts: 50 } };
    const plain: Msg = { id: "p", role: "assistant", text: "a normal answer", ts: 200 };
    const rows = newWatchRows(undefined, [old, ...msgs, plain], 60);
    expect(rows).toHaveLength(40);
    expect(newWatchRows(undefined, msgs, null)).toEqual([]); // no record yet: a first start never floods
    let s = reduce(base(), { type: "watch.missed", bot: "friren", count: rows.length });
    expect(s.unread.friren).toBe(40);
    s = reduce(s, { type: "watch.missed", bot: "kami", count: 3 }); // the open bot: nothing unread
    expect(s.unread.kami ?? 0).toBe(0);
    expect(watchMissedNote("Friren", "friren", rows)?.title).toBe("Friren: 40 watch alerts");
    expect(watchMissedNote("Friren", "friren", rows.slice(0, 1))?.title).toBe("Friren · deploys");
    expect(watchMissedNote("Friren", "friren", [])).toBeNull();
  });

  it("chat.open carries the watch tag onto the reloaded answer", () => {
    const s = reduce(base(), {
      type: "chat.opened",
      bot: "friren",
      now: T0,
      res: { session_id: "s", running: false, model: "m", provider: "p", reasoning: "low", messages: [{ id: "a", role: "assistant", text: "x", ts: 5, watch: { name: "deploys", ts: 4 } }] },
    });
    expect(s.chats.friren.items[0]).toMatchObject({ watch: { name: "deploys", ts: 4 } });
  });
});
