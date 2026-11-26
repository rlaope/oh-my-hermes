import { afterEach, describe, expect, it } from "vitest";
import { noteServerMode, parsePort, remoteOnly, serverLabel, serverMode } from "./remote";
import { handBots } from "../handover/HandoverCard";
import { gateMode, sameStatus, type GateMode } from "./BridgeGate";
import type { Bot } from "../lib/protocol";

afterEach(() => noteServerMode({ mode: "local" }));

describe("remote-only mode from bridge_status", () => {
  it("is local until a status names mode remote, and local again after", () => {
    expect(remoteOnly()).toBe(false);
    noteServerMode({ mode: "local" });
    expect(remoteOnly()).toBe(false);
    noteServerMode({ mode: "remote", host: "demo@vps" });
    expect(remoteOnly()).toBe(true);
    expect(serverMode()).toEqual({ mode: "remote", host: "demo@vps", label: undefined });
    noteServerMode({});
    expect(remoteOnly()).toBe(false);
  });
  it("names the server by its label, else its host", () => {
    expect(serverLabel({ host: "demo@vps", label: "VPS" })).toBe("VPS");
    expect(serverLabel({ host: "demo@vps" })).toBe("demo@vps");
    expect(serverLabel(null)).toBe("");
  });
});

describe("the port field", () => {
  it("takes empty as ssh's own, a port 1-65535, and nothing else", () => {
    expect(parsePort("")).toBeUndefined();
    expect(parsePort("  ")).toBeUndefined();
    expect(parsePort("22")).toBe(22);
    expect(parsePort(" 2222 ")).toBe(2222);
    expect(parsePort("65535")).toBe(65535);
    for (const bad of ["0", "65536", "22a", "-1", "2.2", "123456"]) expect(parsePort(bad)).toBeNull();
  });
});

describe("Hand to <bot> while on a server", () => {
  const bot = (name: string, extra: Partial<Bot> = {}) => ({ name, display_name: name, status: "online", ...extra }) as Bot;
  it("offers no bot: a folder of this computer is not one a bot on the server can read", () => {
    const bots = [bot("kami"), bot("mini:x", { host: { peer: "mini", label: "mini", host: "mini" } as Bot["host"] })];
    expect(handBots(bots).map((b) => b.name)).toEqual(["kami"]);
    noteServerMode({ mode: "remote", host: "demo@vps" });
    expect(handBots(bots)).toEqual([]);
  });
});

describe("the gate in remote-only mode", () => {
  const walk = (states: ("ready" | "starting" | "failed")[], remote: boolean) => {
    let m: GateMode = "boot";
    return states.map((s) => (m = gateMode(m, s, remote)));
  };
  it("says Connecting on the screen before the app was up, and a lost link in the bar after", () => {
    expect(walk(["starting", "starting", "ready", "starting", "ready"], true)).toEqual(["boot", "boot", "up", "down", "up"]);
    // local mode keeps its quiet restart (the chats say reconnecting) until the shell gives up
    expect(walk(["starting", "ready", "starting", "failed"], false)).toEqual(["boot", "up", "up", "down"]);
  });
  it("re-renders on a change of mode or host, not on a steady answer", () => {
    const a = { state: "ready" as const, mode: "remote" as const, host: "demo@vps" };
    expect(sameStatus(a, { ...a })).toBe(true);
    expect(sameStatus(a, { ...a, host: "demo@other" })).toBe(false);
    expect(sameStatus({ state: "ready", mode: "local" }, { state: "ready", mode: "remote", host: "h" })).toBe(false);
    expect(sameStatus(null, a)).toBe(false);
  });
});
