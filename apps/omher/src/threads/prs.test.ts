import { describe, expect, it, vi } from "vitest";
import {
  PR_BACKOFF_MAX_MS,
  PR_REREAD_MS,
  PR_RING_GAP_MS,
  PR_TICK_MS,
  cleanPrs,
  createThreadPrs,
  failKey,
  failingPr,
  mayChange,
  mayRing,
  namedPrs,
  nextDelay,
  prLinksIn,
  readFailed,
  withState,
  type Told,
  type ThreadPr,
  type ThreadPrDeps,
} from "./prs";

const SHA = "0123456789abcdef0123456789abcdef01234567";
const pr = (number: number, state: ThreadPr["state"], checks: ThreadPr["checks"], head?: string, repo = "o/r"): ThreadPr => ({
  number,
  repo,
  url: `https://github.com/${repo}/pull/${number}`,
  state,
  checks,
  ...(head ? { head } : {}),
});

describe("which links name a pull request", () => {
  it("takes only full github.com PR links, as the bridge does", () => {
    expect(prLinksIn("opened https://github.com/o/r/pull/7 and (https://github.com/a/b.c/pull/12).")).toEqual([
      { number: 7, repo: "o/r", url: "https://github.com/o/r/pull/7" },
      { number: 12, repo: "a/b.c", url: "https://github.com/a/b.c/pull/12" },
    ]);
    for (const bad of [
      "https://github.com.evil.io/o/r/pull/1",
      "https://evilgithub.com/o/r/pull/1",
      "https://www.github.com/o/r/pull/1",
      "http://github.com/o/r/pull/1",
      "xhttps://github.com/o/r/pull/1",
      "https://evil.io/https://github.com/o/r/pull/1",
      "https://github.com/o/r/pull/1/files",
      "https://github.com/o/r/x/pull/1",
      "https://github.com/o/r/pull/12345678",
      "https://github.com/o/r/pull/007",
      "https://github.com/o/../pull/1",
      "https://github.com/-o/r/pull/1",
      "PR #12",
    ])
      expect(prLinksIn(`see ${bad} now`), bad).toEqual([]);
  });

  it("reads the bot's answers only, newest first, each once, three at most, with the answer that last named each", () => {
    const items = [
      { kind: "user", id: "u1", text: "the old one: https://github.com/o/r/pull/1" },
      { kind: "assistant", id: "a1", text: "opened https://github.com/o/r/pull/2 and https://github.com/o/r/pull/3" },
      { kind: "activity", id: "x", text: "https://github.com/o/r/pull/4" },
      { kind: "assistant", id: "a2", text: "also https://github.com/a/b/pull/5" },
      { kind: "assistant", id: "a3", text: "back on https://github.com/o/r/pull/2, then https://github.com/c/d/pull/6" },
    ];
    expect(namedPrs(items).map((p) => [p.repo, p.number, p.at])).toEqual([
      ["c/d", 6, "a3"],
      ["o/r", 2, "a3"],
      ["a/b", 5, "a2"],
    ]);
    expect(namedPrs([])).toEqual([]);
  });
});

describe("what the page keeps from the bridge", () => {
  it("drops anything that is not a known word, the canonical URL or a commit id", () => {
    const raw = [
      { number: 7, repo: "o/r", url: "https://github.com/o/r/pull/7", state: "open", checks: "failing", head: SHA, title: "<img src=x>" },
      { number: 8, repo: "o/r", url: "https://github.com/o/r/pull/8", state: "MERGED", checks: "✓ passing", head: "zz" },
      { number: 9, repo: "o/r", url: "https://github.com.evil.io/o/r/pull/9", state: "open", checks: "passing" },
      { number: 10, repo: "x/y", url: "https://github.com/o/r/pull/10", state: "open", checks: "passing" },
      "nope",
    ];
    expect(cleanPrs(raw)).toEqual([pr(7, "open", "failing", SHA), pr(8, "unknown", "none")]);
    expect(cleanPrs(null)).toEqual([]);
  });

  it("lays the bridge's word over the transcript's numbers, same repo and number only", () => {
    const refs = [{ number: 7, repo: "o/r", url: "https://github.com/o/r/pull/7", at: "a1" }, { number: 8, repo: "o/r", url: "https://github.com/o/r/pull/8", at: "a2" }];
    expect(withState(refs, [pr(7, "merged", "passing"), pr(8, "open", "running", undefined, "x/y")])).toEqual([
      { ...refs[0], state: "merged", checks: "passing" },
      { ...refs[1], state: "unknown", checks: "none" },
    ]);
  });
});

describe("the Needs reason and the one notification", () => {
  it("is the newest open (not draft) PR with failing checks", () => {
    expect(failingPr([pr(1, "merged", "failing"), pr(2, "draft", "failing"), pr(3, "open", "running")])).toBeNull();
    expect(failingPr([pr(4, "open", "passing"), pr(5, "open", "failing"), pr(6, "open", "failing")])?.number).toBe(5);
    expect(failingPr([pr(7, "unknown", "failing")])).toBeNull();
  });

  it("keys a notification by the PR and its head commit", () => {
    expect(failKey(pr(5, "open", "failing", SHA))).toBe(`o/r#5@${SHA}`);
    expect(failKey(pr(5, "open", "failing"))).toBe("o/r#5@?");
  });

  it("re-reads only what may change, with a doubling wait up to an hour", () => {
    expect(mayChange([pr(1, "merged", "passing"), pr(2, "closed", "none")])).toBe(false);
    expect(mayChange([pr(1, "merged", "passing"), pr(2, "draft", "none")])).toBe(true);
    expect(mayChange([pr(1, "unknown", "none")])).toBe(true);
    expect([0, 1, 2, 3, 4, 9].map(nextDelay)).toEqual([PR_REREAD_MS, 2 * PR_REREAD_MS, 4 * PR_REREAD_MS, 8 * PR_REREAD_MS, PR_BACKOFF_MAX_MS, PR_BACKOFF_MAX_MS]);
    expect(PR_REREAD_MS).toBe(5 * 60_000);
  });
});

/** A reader over a scripted bridge: `answers[thread]` is what `thread.prs` returns next (an Error rejects). */
function rig(answers: Record<string, unknown>, remote = false) {
  let now = 1_000_000;
  const calls: { thread: string; fresh: boolean }[] = [];
  const notes: string[] = [];
  let told: Told = { heads: [], prs: {} };
  const pending: (() => void)[] = [];
  const deps: ThreadPrDeps = {
    read: (_bot, thread, fresh) => {
      calls.push({ thread, fresh });
      return new Promise((res, rej) => {
        pending.push(() => {
          const a = answers[thread];
          if (a instanceof Error) rej(a);
          else res({ prs: (a as unknown[]) ?? [] });
        });
      });
    },
    remote: () => remote,
    now: () => now,
    notify: (f) => notes.push(failKey(f.pr)),
    told: { get: () => told, set: (t) => void (told = t) },
  };
  const prs = createThreadPrs(deps);
  const settle = async () => {
    while (pending.length) {
      pending.shift()!();
      await Promise.resolve();
      await new Promise((r) => setTimeout(r, 0));
    }
  };
  return { prs, calls, notes, settle, later: (ms: number) => (now += ms), told: () => told };
}

describe("when a thread is read", () => {
  it("reads at most two threads at once and never the same one twice at a time", async () => {
    const r = rig({});
    for (const th of ["a", "b", "c", "a"]) r.prs.read("kami", th, "open");
    expect(r.calls.map((c) => c.thread)).toEqual(["a", "b"]);
    await r.settle();
    expect(r.calls.map((c) => c.thread)).toEqual(["a", "b", "c"]);
    r.prs.stop();
  });

  it("a row in view is read once, not again within five minutes, then on the tick only while a PR may change", async () => {
    const answers: Record<string, unknown> = { t: [pr(1, "open", "running")] };
    const r = rig(answers);
    const off = r.prs.show("kami", "t");
    await r.settle();
    expect(r.calls).toHaveLength(1);
    r.prs.show("kami", "t")(); // in view again moments later: not read again
    r.prs.tick();
    expect(r.calls).toHaveLength(1);
    r.later(PR_REREAD_MS);
    r.prs.tick();
    await r.settle();
    expect(r.calls).toHaveLength(2);
    // merged now: the tick leaves it alone
    answers.t = [pr(1, "merged", "passing")];
    r.prs.read("kami", "t", "turn");
    await r.settle();
    r.later(10 * PR_REREAD_MS);
    r.prs.tick();
    expect(r.calls).toHaveLength(3);
    // out of view: no tick read even for a PR that may change
    answers.t = [pr(1, "open", "running")];
    r.prs.read("kami", "t", "turn");
    await r.settle();
    off();
    r.later(10 * PR_REREAD_MS);
    r.prs.tick();
    expect(r.calls).toHaveLength(4);
    r.prs.stop();
  });

  it("backs off after failed reads and never reads a bot on another computer", async () => {
    const r = rig({ t: new Error("gone") });
    r.prs.show("kami", "t");
    await r.settle();
    expect(r.prs.get("kami", "t")?.failures).toBe(1);
    // a failed first read has nothing to re-read on the tick (no PR known); a turn's end asks again
    r.prs.read("kami", "t", "turn");
    await r.settle();
    expect(r.prs.get("kami", "t")?.failures).toBe(2);
    const peer = rig({ t: [pr(1, "open", "failing")] }, true);
    peer.prs.read("mini:kami", "t", "open");
    peer.prs.show("mini:kami", "t");
    expect(peer.calls).toEqual([]);
    r.prs.stop();
    peer.prs.stop();
  });

  it("a gh that cannot say counts as a failed read: the next tick waits twice as long", async () => {
    const r = rig({ t: [pr(1, "unknown", "none")] });
    r.prs.show("kami", "t");
    await r.settle();
    expect(r.prs.get("kami", "t")?.failures).toBe(1);
    r.later(PR_REREAD_MS);
    r.prs.tick();
    expect(r.calls).toHaveLength(1);
    r.later(PR_REREAD_MS);
    r.prs.tick();
    expect(r.calls).toHaveLength(2);
    r.prs.stop();
  });

  it("a Refresh asks GitHub again (fresh), queued behind a read under way", async () => {
    const r = rig({ t: [] });
    r.prs.read("kami", "t", "open");
    r.prs.read("kami", "t", "refresh");
    r.prs.read("kami", "t", "view");
    expect(r.calls).toEqual([{ thread: "t", fresh: false }]);
    await r.settle();
    expect(r.calls).toEqual([
      { thread: "t", fresh: false },
      { thread: "t", fresh: true },
    ]);
    r.prs.stop();
  });
});

describe("Needs you and the notification", () => {
  it("lists a thread while its PR fails, leaves when it passes, and rings once per failing head", async () => {
    const answers: Record<string, unknown> = { t: [pr(5, "open", "failing", SHA)] };
    const r = rig(answers);
    const seen = vi.fn();
    r.prs.subscribe(seen);
    r.prs.read("kami", "t", "open");
    await r.settle();
    expect(r.prs.failing().map((f) => [f.thread, f.pr.number])).toEqual([["t", 5]]);
    expect(r.notes).toEqual([`o/r#5@${SHA}`]);
    const before = r.prs.failing();
    r.prs.read("kami", "t", "turn");
    await r.settle();
    expect(r.notes).toHaveLength(1); // the same failing head: no second ring
    expect(r.prs.failing()).toBe(before); // the same list for the view
    answers.t = [pr(5, "open", "passing", SHA)];
    r.prs.read("kami", "t", "turn");
    await r.settle();
    expect(r.prs.failing()).toEqual([]);
    const other = SHA.replace("0", "f");
    answers.t = [pr(5, "open", "failing", other)];
    r.prs.read("kami", "t", "turn");
    await r.settle();
    expect(r.notes).toHaveLength(1); // a new failing head within 6 hours of the last ring: quiet, and told
    const third = SHA.replace("0", "e");
    r.later(PR_RING_GAP_MS);
    r.prs.read("kami", "t", "turn");
    await r.settle();
    expect(r.notes).toHaveLength(1); // that quiet head never rings later
    answers.t = [pr(5, "open", "failing", third)];
    r.prs.read("kami", "t", "turn");
    await r.settle();
    expect(r.notes).toEqual([`o/r#5@${SHA}`, `o/r#5@${third}`]); // a new failing head after 6 hours rings once more
    answers.t = [pr(5, "merged", "failing", other)];
    r.prs.read("kami", "t", "turn");
    await r.settle();
    expect(r.prs.failing()).toEqual([]);
    expect(seen).toHaveBeenCalled();
    r.prs.forget("kami", "t");
    expect(r.prs.get("kami", "t")).toBeUndefined();
    r.prs.stop();
  });

  it("a draft or an unknown state with failing checks is not a Needs reason and never rings", async () => {
    const r = rig({ t: [pr(5, "draft", "failing", SHA)], u: [pr(6, "unknown", "failing")] });
    r.prs.read("kami", "t", "open");
    r.prs.read("kami", "u", "open");
    await r.settle();
    expect(r.prs.failing()).toEqual([]);
    expect(r.notes).toEqual([]);
    r.prs.stop();
  });
});

describe("review fixes: rings, failures, the cap, and Needs out of view", () => {
  it("rings once per failing head, never twice for one PR within six hours; a PR with no head by the hours alone", () => {
    let t: Told = { heads: [], prs: {} };
    const step = (p: ThreadPr, now: number) => {
      const r = mayRing(t, p, now);
      t = r.told;
      return r.ring;
    };
    const a = SHA, b = SHA.replace("0", "b");
    expect(step(pr(1, "open", "failing", a), 0)).toBe(true);
    expect(step(pr(1, "open", "failing", a), PR_RING_GAP_MS * 3)).toBe(false); // the same head, ever
    expect(step(pr(2, "open", "failing", a, "x/y"), 10)).toBe(true); // another PR: its own count
    expect(step(pr(3, "open", "failing"), 0)).toBe(true);
    const before = t;
    expect(step(pr(3, "open", "failing"), PR_RING_GAP_MS - 1)).toBe(false);
    expect(t).toBe(before); // nothing changed: the same record, so nothing is written
    expect(step(pr(3, "open", "failing"), PR_RING_GAP_MS)).toBe(true);
    expect(step(pr(1, "open", "failing", b), PR_RING_GAP_MS * 3 + 1)).toBe(true);
  });

  it("a read fails only when gh could say nothing about any PR; the cap is no failure", () => {
    expect(readFailed([])).toBe(false);
    expect(readFailed([pr(1, "unknown", "none")])).toBe(true);
    expect(readFailed([pr(1, "unknown", "none"), pr(2, "open", "passing")])).toBe(false);
    expect(readFailed([{ ...pr(1, "unknown", "none"), limited: true }])).toBe(false);
    expect(cleanPrs([{ ...pr(1, "unknown", "none"), limited: true }])[0].limited).toBe(true);
    expect(cleanPrs([{ ...pr(1, "open", "none"), limited: true }])[0].limited).toBeUndefined();
  });

  it("an answer held back by the cap is asked again on the next tick, not after a backoff", async () => {
    const answers: Record<string, unknown> = { t: [{ ...pr(1, "unknown", "none"), limited: true }] };
    const r = rig(answers);
    r.prs.show("kami", "t");
    await r.settle();
    expect(r.prs.get("kami", "t")?.failures).toBe(0);
    r.later(PR_TICK_MS);
    r.prs.tick();
    await r.settle();
    expect(r.calls).toHaveLength(2);
    r.prs.stop();
  });

  it("the tick re-reads a thread in Needs you even when its row is out of view, so it leaves when merged", async () => {
    const answers: Record<string, unknown> = { t: [pr(5, "open", "failing", SHA)] };
    const r = rig(answers);
    r.prs.read("kami", "t", "open"); // opened, never shown in the sidebar
    await r.settle();
    expect(r.prs.failing()).toHaveLength(1);
    answers.t = [pr(5, "merged", "passing", SHA)];
    r.later(PR_REREAD_MS);
    r.prs.tick();
    await r.settle();
    expect(r.prs.failing()).toEqual([]);
    r.prs.stop();
  });

  it("names the PRs of one transcript once (kept per items array)", () => {
    const items = [{ kind: "assistant", id: "a", text: "https://github.com/o/r/pull/1" }];
    expect(namedPrs(items)).toBe(namedPrs(items));
    expect(namedPrs([...items])).not.toBe(namedPrs(items));
  });
});
