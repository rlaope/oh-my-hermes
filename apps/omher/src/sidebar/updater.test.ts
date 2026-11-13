import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { percent, retryDelay, shortError, updateHost, watchForUpdates, type PendingUpdate } from "./updater";

const realCheck = vi.hoisted(() => vi.fn(async (_options?: { timeout?: number }) => null));
vi.mock("@tauri-apps/plugin-updater", () => ({ check: realCheck }));

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
    vi.stubGlobal("window", { __TAURI_INTERNALS__: {} });
    await updateHost()!.check();
    expect(realCheck.mock.calls).toEqual([[{ timeout: 30_000 }]]);
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
