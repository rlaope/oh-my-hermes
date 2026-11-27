// A thread's unread answers (`fold:<bot>:<thread>`, summed into the Dock count and the Windows taskbar dot) show on its
// row, and the bot row counts those of its threads the tree does not show (past "Show N more"), so every answer that
// keeps the count up has a row that shows it. Opening the thread clears the mark and the count.
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { initialState, reduce, selectUnreadTotal, type Action, type AppState } from "../state/store";
import type { BridgeEvent } from "../lib/protocol";
import { threadKey, THREADS_SHOWN, type ThreadRow } from "./types";

let current: AppState = initialState();
vi.mock("../state/store", async (orig) => ({ ...(await orig<typeof import("../state/store")>()), useStore: () => current }));
const { hiddenThreadUnread, ThreadTree } = await import("./ThreadTree");

const T0 = 1_800_000_000_000;
const ev = (s: AppState, e: BridgeEvent) => reduce(s, { type: "event", ev: e, now: T0 } as Action);
const row = (thread: string): ThreadRow => ({ thread, title: `title ${thread}`, cwd: "", started_at: 0, running: false, needs: false, message_count: 0, last: 0 });
const finish = (s: AppState, thread: string, id: string) => {
  s = ev(s, { event: "turn.start", bot: "kami", session: thread } as BridgeEvent);
  s = ev(s, { event: "message", bot: "kami", session: thread, id, text: `answer ${id}` } as BridgeEvent);
  return ev(s, { event: "turn.end", bot: "kami", session: thread, outcome: "done" } as BridgeEvent);
};
const tree = (s: AppState, all = false) => {
  current = s;
  return renderToStaticMarkup(<ThreadTree bot="kami" id="threads-of-kami" all={all} onAll={() => undefined} />);
};
const rowHtml = (html: string, thread: string) => html.split("<li").find((part) => part.includes(`data-thread="${thread}"`)) ?? "";

function listed(n: number): AppState {
  let s = reduce(initialState(), { type: "select", bot: "kami" });
  return reduce(s, { type: "threads", bot: "kami", threads: Array.from({ length: n }, (_, i) => row(`th-${i + 1}`)) } as Action);
}

beforeEach(() => {
  current = initialState();
});

describe("a thread's unread answers show on its row", () => {
  it("a thread that finished while not open counts in the total and marks its row; opening it clears both", () => {
    let s = finish(listed(2), "th-1", "a1");
    expect(selectUnreadTotal(s)).toBe(1);
    const before = rowHtml(tree(s), "th-1");
    expect(before).toContain('data-testid="thread-unread"');
    expect(before).toContain('class="th-row unread"');
    expect(before).toContain("1 unread");
    // the other thread has nothing unread
    expect(rowHtml(tree(s), "th-2")).not.toContain("thread-unread");
    s = reduce(s, { type: "ui.thread", bot: "kami", thread: "th-1" });
    expect(selectUnreadTotal(s)).toBe(0);
    expect(rowHtml(tree(s), "th-1")).not.toContain("thread-unread");
  });

  it("an open question takes the count's place, as on the bot row", () => {
    // an answer, then the turn asks before it ends
    let s = ev(listed(1), { event: "turn.start", bot: "kami", session: "th-1" } as BridgeEvent);
    s = ev(s, { event: "message", bot: "kami", session: "th-1", id: "a1", text: "answer a1" } as BridgeEvent);
    expect(s.unread[threadKey("kami", "th-1")]).toBe(1);
    s = ev(s, { event: "approval.request", bot: "kami", session: "th-1", request_id: "ap-1", title: "Run", command: "ls", choices: ["once", "deny"] } as BridgeEvent);
    const html = rowHtml(tree(s), "th-1");
    expect(html).toContain('data-state="needs_you"');
    expect(html).not.toContain("thread-unread");
  });
});

describe("threads out of view count on the bot row", () => {
  const past = `th-${THREADS_SHOWN + 2}`;

  it("a thread past 'Show N more' counts on the bot row and the more line until all show", () => {
    const s = finish(listed(THREADS_SHOWN + 2), past, "a1");
    expect(hiddenThreadUnread(s, "kami", false)).toBe(1);
    expect(tree(s)).toContain('data-testid="thread-more-unread"');
    expect(hiddenThreadUnread(s, "kami", true)).toBe(0);
    const all = tree(s, true);
    expect(all).not.toContain("thread-more-unread");
    expect(rowHtml(all, past)).toContain('data-testid="thread-unread"');
  });

  it("a thread in view does not count twice on the bot row", () => {
    const s = finish(listed(THREADS_SHOWN + 2), "th-1", "a1");
    expect(hiddenThreadUnread(s, "kami", false)).toBe(0);
  });
});
