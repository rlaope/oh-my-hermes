import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { CpuChipView } from "../sidebar/CpuChip";
import { cpuWarn, resetCpuForTest, setCpuWarn, startCpuWatch, type CpuHog, type CpuState } from "./cpu";
import { cpuHogNote, type Note } from "./notify";
import { MockHost } from "../sessions/host";

const chip = (hogs: CpuHog[]) => renderToStaticMarkup(<CpuChipView hogs={hogs} onOpen={() => {}} />);

/** A host whose events the test fires by hand. */
function fakeHost() {
  const warn = new Set<(h: CpuHog) => void>();
  const state = new Set<(s: CpuState) => void>();
  const asked: boolean[] = [];
  return {
    asked,
    fire: (h: CpuHog) => warn.forEach((f) => f(h)),
    host: {
      cpuWatch: async (on: boolean) => (asked.push(on), { hogs: [], supported: true }),
      onCpuHog: (f: (h: CpuHog) => void) => (warn.add(f), () => warn.delete(f)),
      onCpuHogs: (f: (s: CpuState) => void) => (state.add(f), () => state.delete(f)),
    },
  };
}

let store: Map<string, string>;
beforeEach(() => {
  store = new Map();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
  });
});
afterEach(() => {
  resetCpuForTest();
  vi.unstubAllGlobals();
});

describe("cpu chip", () => {
  it("names the hottest app and its usage, and how many more", () => {
    const one = chip([{ name: "Web", pct: 99, pid: 7 }]);
    expect(one).toContain('data-testid="cpu-chip"');
    expect(one).toContain("Web · 99 % CPU");
    expect(chip([{ name: "Web", pct: 99, pid: 7 }, { name: "Build", pct: 91, pid: 8 }])).toContain("Web · 99 % CPU +1");
  });
  it("hides with no hog", () => {
    expect(chip([])).toBe("");
  });
});

describe("cpu note", () => {
  it("is a system warning naming the app", () => {
    expect(cpuHogNote({ name: "Web", pct: 99 })).toEqual({
      title: "Web has kept a CPU core busy for over a minute · 99 %",
      body: "It may be stuck. Quit it in Activity Monitor or Task Manager if you do not need it.",
      bot: "",
      tag: "cpu:Web",
    });
  });
});

describe("cpu watch", () => {
  it("is on by default and asks the shell to read", async () => {
    expect(cpuWarn()).toBe(true);
    const f = fakeHost();
    const notes: Note[] = [];
    startCpuWatch(f.host, (n) => notes.push(n));
    await Promise.resolve();
    expect(f.asked).toEqual([true]);
    f.fire({ name: "Web", pct: 97, pid: 7 });
    expect(notes.map((n) => n.title)).toEqual(["Web has kept a CPU core busy for over a minute · 97 %"]);
  });
  it("turned off: the shell stops reading and a late warning is dropped", async () => {
    const f = fakeHost();
    const notes: Note[] = [];
    startCpuWatch(f.host, (n) => notes.push(n));
    setCpuWarn(false);
    await Promise.resolve();
    expect(f.asked).toEqual([true, false]);
    expect(localStorage.getItem("omher.cpuWarn")).toBe("off");
    f.fire({ name: "Web", pct: 97, pid: 7 });
    expect(notes).toEqual([]);
  });
});

describe("mock host cpu watch", () => {
  it("sends a warning and the hog list while on, nothing while off", async () => {
    const g: Record<string, unknown> = {};
    const h = new MockHost(g as never);
    const warned: string[] = [];
    const lists: number[] = [];
    h.onCpuHog((x) => warned.push(x.name));
    h.onCpuHogs((s) => lists.push(s.hogs.length));
    await h.cpuWatch(true);
    const send = g.__omherCpuHog as (x: CpuHog | null) => void;
    send({ name: "Web", pct: 99, pid: 7 });
    send(null);
    expect((await h.cpuWatch(false)).hogs).toEqual([]);
    send({ name: "Other", pct: 99, pid: 8 });
    expect(warned).toEqual(["Web"]);
    expect(lists).toEqual([1, 0]);
    expect(g.__omherCpuWatch).toEqual([true, false]);
  });
});
