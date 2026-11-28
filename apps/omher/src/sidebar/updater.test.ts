import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { percent, relaunchOrWait, RESTART_WAIT_MS, retryDelay, shortError, updateHost, watchForUpdates, type PendingUpdate } from "./updater";

describe("updater helpers", () => {
  it("rounds progress down and caps it at 100", () => {
    expect(percent({ done: 0, total: 1000 })).toBe(0);
    expect(percent({ done: 999, total: 1000 })).toBe(99);
    expect(percent({ done: 2000, total: 1000 })).toBe(100);
    expect(percent({ done: 10, total: null })).toBeNull();
    expect(percent({ done: 10, total: 0 })).toBeNull();
  });

  it("keeps an error to its first line", () => {
    expect(shortError(new Error("signature mismatch\nat x"))).toBe("signature mismatch");
    expect(shortError("offline")).toBe("offline");
    expect(shortError({})).toBe("Update failed");
    expect(shortError("x".repeat(200))).toHaveLength(80);
  });
});

const MIN = 60_000;
const HOUR = 60 * MIN;

/** The injected host (`window.__omherUpdateHost`): each check takes the next answer, then keeps the last one. */
type Answer = "fail" | "none" | "hold" | string;
let asked: number[] = [];
let found: (string | null)[] = [];
let release: () => void = () => {};
let doc: EventTarget & { visibilityState: string };

function open(answers: Answer[], paused: () => boolean = () => false) {
  const left = [...answers];
  const update = (version: string): PendingUpdate => ({ version, install: async () => {} });
  const win = Object.assign(new EventTarget(), {
    __omherUpdateHost: {
      check: async () => {
        asked.push(Date.now());
        const a = left.length > 1 ? left.shift()! : left[0];
        if (a === "fail") throw new Error("network down");
        if (a === "none") return null;
        if (a === "hold") {
          await new Promise<void>((r) => (release = r));
          return update("9.9.9");
        }
        return update(a);
      },
      relaunch: async () => {},
    },
  });
  vi.stubGlobal("window", win);
  vi.stubGlobal("document", doc);
  return watchForUpdates(updateHost()!, (u) => void found.push(u ? u.version : null), paused);
}
const pass = (ms: number) => vi.advanceTimersByTimeAsync(ms);
const focus = () => window.dispatchEvent(new Event("focus"));
const shown = () => document.dispatchEvent(new Event("visibilitychange"));
/** Minutes after launch at which each check was sent. */
const askedAt = () => asked.map((t) => t / MIN);

describe("an app left open keeps looking for a newer release", () => {
  beforeEach(() => {
    asked = [];
    found = [];
    doc = Object.assign(new EventTarget(), { visibilityState: "visible" });
    vi.useFakeTimers();
    vi.setSystemTime(0);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("tries a failed check again within minutes, not 6 hours later", async () => {
    const stop = open(["fail", "0.2.8"]);
    await pass(0);
    expect(found).toEqual([]);
    await pass(2 * MIN);
    expect(found).toEqual(["0.2.8"]);
    expect(askedAt()).toEqual([0, 2]);
    stop();
  });

  it("backs off while checks keep failing, and never waits longer than an hour", async () => {
    expect([1, 2, 3, 4, 5, 6, 7, 20].map((n) => retryDelay(n) / MIN)).toEqual([2, 4, 8, 16, 32, 60, 60, 60]);
    const stop = open(["fail"]);
    await pass(4 * HOUR);
    expect(askedAt()).toEqual([0, 2, 6, 14, 30, 62, 122, 182]);
    expect(found).toEqual([]);
    stop();
  });

  it("after a good check waits 6 hours, and a failure after that is retried in minutes again", async () => {
    const stop = open(["fail", "fail", "none", "fail", "0.2.8"]);
    await pass(6 * HOUR + 10 * MIN);
    expect(askedAt()).toEqual([0, 2, 6, 366, 368]);
    expect(found).toEqual([null, "0.2.8"]);
    stop();
  });

  it("checks when the window gets focus 31 minutes after the last good check", async () => {
    const stop = open(["none", "0.2.8"]);
    await pass(31 * MIN);
    expect(askedAt()).toEqual([0]);
    focus();
    await pass(0);
    expect(askedAt()).toEqual([0, 31]);
    expect(found).toEqual([null, "0.2.8"]);
    stop();
  });

  it("checks when the window is shown again, and not while it is hidden", async () => {
    const stop = open(["none", "0.2.8"]);
    await pass(31 * MIN);
    doc.visibilityState = "hidden";
    shown();
    focus();
    await pass(0);
    expect(askedAt()).toEqual([0]);
    doc.visibilityState = "visible";
    shown();
    await pass(0);
    expect(askedAt()).toEqual([0, 31]);
    stop();
  });

  it("sends nothing on focus 5 minutes after a good check", async () => {
    const stop = open(["none"]);
    await pass(5 * MIN);
    focus();
    shown();
    await pass(0);
    expect(askedAt()).toEqual([0]);
    await pass(24 * MIN);
    focus();
    await pass(0);
    expect(askedAt()).toEqual([0]);
    await pass(MIN);
    focus();
    await pass(0);
    expect(askedAt()).toEqual([0, 30]);
    stop();
  });

  it("sends one request however often the window comes back while a check is in flight", async () => {
    const stop = open(["none", "hold"]);
    await pass(31 * MIN);
    focus();
    shown();
    await pass(5 * MIN);
    focus();
    shown();
    await pass(0);
    expect(askedAt()).toEqual([0, 31]);
    expect(found).toEqual([null]);
    release();
    await pass(0);
    expect(found).toEqual([null, "9.9.9"]);
    expect(askedAt()).toEqual([0, 31]);
    stop();
  });

  it("while checks fail, coming back asks again but not more than once a minute", async () => {
    const stop = open(["fail"]);
    await pass(0);
    focus();
    shown();
    await pass(30_000);
    focus();
    await pass(0);
    expect(askedAt()).toEqual([0]);
    await pass(30_000);
    focus();
    await pass(0);
    expect(askedAt()).toEqual([0, 1]);
    stop();
  });

  it("a check that answers after the button is gone reports nothing and plans no further check", async () => {
    const stop = open(["hold"]);
    await pass(0);
    stop();
    release();
    await pass(7 * HOUR);
    expect(found).toEqual([]);
    expect(askedAt()).toEqual([0]);
  });

  it("gives the shell's own check a time limit, so one that never answers cannot hold back the next", async () => {
    // the shell's side of the bridge: what the updater's own check hands to Tauri
    const sent: [string, { timeout?: number }][] = [];
    const invoke = async (cmd: string, args: { timeout?: number }) => {
      sent.push([cmd, args]);
      return null;
    };
    vi.stubGlobal("window", { __TAURI_INTERNALS__: { invoke } });
    expect(await updateHost()!.check()).toBeNull();
    expect(sent.map(([cmd, args]) => [cmd, args.timeout])).toEqual([["plugin:updater|check", 30_000]]);
  });

  it("does not check while an install runs, and stops for good when the button is gone", async () => {
    let installing = true;
    const stop = open(["0.2.8"], () => installing);
    await pass(31 * MIN);
    focus();
    await pass(0);
    expect(askedAt()).toEqual([]);
    installing = false;
    focus();
    await pass(0);
    expect(askedAt()).toEqual([31]);
    const gone = [vi.spyOn(window, "removeEventListener"), vi.spyOn(document, "removeEventListener")];
    stop();
    expect(gone.map((g) => g.mock.calls.map((c) => c[0]))).toEqual([["focus"], ["visibilitychange"]]);
    await pass(7 * HOUR);
    focus();
    shown();
    await pass(0);
    expect(askedAt()).toEqual([31]);
  });
});

describe("a restart that does not happen", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  /** A relaunch that never ends the page (resolves, or hangs when `hang`), recording each call after a save. */
  const stand = (how: "resolve" | "hang" | "reject") => {
    const log: string[] = [];
    const host = {
      relaunch: () => {
        log.push("relaunch");
        return how === "resolve" ? Promise.resolve() : how === "reject" ? Promise.reject(new Error("no")) : new Promise<void>(() => {});
      },
    };
    return { log, host, save: () => log.push("save") };
  };

  it("saves what is open, asks once, and waits 10 s before saying it is stuck", async () => {
    const { log, host, save } = stand("resolve");
    const stuck = vi.fn();
    relaunchOrWait(host, save, stuck, RESTART_WAIT_MS);
    expect(log).toEqual(["save", "relaunch"]);
    await vi.advanceTimersByTimeAsync(RESTART_WAIT_MS - 1);
    expect(stuck).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(stuck).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(stuck).toHaveBeenCalledTimes(1);
  });

  it("a relaunch that never answers still ends in the waiting state", async () => {
    const { host, save } = stand("hang");
    const stuck = vi.fn();
    relaunchOrWait(host, save, stuck, 500);
    await vi.advanceTimersByTimeAsync(500);
    expect(stuck).toHaveBeenCalledTimes(1);
  });

  it("a refused relaunch says so at once, only once", async () => {
    const { host, save } = stand("reject");
    const stuck = vi.fn();
    relaunchOrWait(host, save, stuck, RESTART_WAIT_MS);
    await vi.advanceTimersByTimeAsync(0);
    expect(stuck).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(RESTART_WAIT_MS);
    expect(stuck).toHaveBeenCalledTimes(1);
  });

  it("each retry saves again before it relaunches, and a dropped wait stays quiet", async () => {
    const { log, host, save } = stand("resolve");
    const stuck = vi.fn();
    relaunchOrWait(host, save, stuck, 100);
    await vi.advanceTimersByTimeAsync(100);
    relaunchOrWait(host, save, stuck, 100);
    await vi.advanceTimersByTimeAsync(100);
    expect(log).toEqual(["save", "relaunch", "save", "relaunch"]);
    expect(stuck).toHaveBeenCalledTimes(2);
    const stop = relaunchOrWait(host, save, stuck, 100);
    stop();
    await vi.advanceTimersByTimeAsync(1000);
    expect(stuck).toHaveBeenCalledTimes(2);
  });
});
