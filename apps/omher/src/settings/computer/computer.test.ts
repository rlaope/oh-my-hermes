import { describe, expect, it } from "vitest";
import type { Bot, ComputerStatus } from "../../lib/protocol";
import { checkLook, driverActions, flipFailure, grantKey, overall, platformName, readOnReturn, switchOff, type ComputerRead } from "./computer";

const bot = (over: Partial<Bot> = {}): Bot => ({
  name: "kami",
  display_name: "Kami",
  is_default: false,
  model: "",
  provider: "",
  description: "",
  status: "online",
  running: false,
  ...over,
});
const read = (over: Partial<ComputerRead> = {}): ComputerStatus => ({
  read: true,
  pinned: false,
  platform: "darwin",
  platform_supported: true,
  installed: true,
  version: "cua-driver 0.4.2",
  ready: true,
  can_grant: true,
  checks: [],
  error: null,
  accessibility: true,
  screen_recording: true,
  ...over,
});

describe("Settings › Computer", () => {
  it("names the platform as people do, else as Hermes wrote it", () => {
    expect(["darwin", "win32", "linux", "freebsd"].map(platformName)).toEqual(["macOS", "Windows", "Linux", "freebsd"]);
  });

  it("offers Install without a driver and Grant access only on macOS with a grant missing", () => {
    expect(driverActions(read({ installed: false, ready: null, accessibility: null, screen_recording: null }))).toEqual(["install"]);
    expect(driverActions(read({ screen_recording: false, ready: false }))).toEqual(["grant"]);
    expect(driverActions(read({ accessibility: null, ready: null }))).toEqual(["grant"]);
    expect(driverActions(read())).toEqual([]);
    // Windows and Linux have no grants to ask for: never Grant access there
    expect(driverActions(read({ platform: "win32", can_grant: false, accessibility: null, screen_recording: null, ready: false }))).toEqual([]);
    // nothing on a computer Hermes does not support, nor when nothing could be read
    expect(driverActions(read({ platform: "freebsd", platform_supported: false, installed: false }))).toEqual([]);
    expect(driverActions({ read: false, pinned: false, line: "x" })).toEqual([]);
    expect(driverActions(null)).toEqual([]);
  });

  it("says ready, not ready or not known", () => {
    expect(overall(read())).toBe("ready");
    expect(overall(read({ ready: false }))).toBe("notReady");
    expect(overall(read({ ready: null }))).toBe("unknown");
    expect(overall({ read: false, pinned: false, line: "" })).toBe("unknown");
    expect(overall(null)).toBe("unknown");
    expect([true, false, null].map(grantKey)).toEqual(["cu.granted", "cu.notGranted", "cu.notKnown"]);
  });

  it("words and colours a driver check from one map; an unknown state keeps Hermes' word", () => {
    expect(checkLook("ok")).toEqual({ key: "cu.checkOk", tone: "ok" });
    expect(checkLook("PASS")).toEqual({ key: "cu.checkOk", tone: "ok" });
    expect(checkLook("warn")).toEqual({ key: "cu.checkWarn", tone: "warn" });
    expect(checkLook("fail")).toEqual({ key: "cu.checkFail", tone: "fail" });
    expect(checkLook("skip")).toEqual({ key: "cu.checkSkip", tone: "skip" });
    expect(checkLook("pending")).toEqual({ key: null, tone: "" });
  });

  it("says what a failed flip knows: Hermes left it, omher can't tell, or nothing was asked", () => {
    expect(flipFailure({ state: "off" })).toBe("disagrees");
    expect(flipFailure({ state: "unknown" })).toBe("unknown");
    for (const code of ["bad_request", "pinned", "cannot_tell", "busy", "remote_bot", "remote_only"]) expect(flipFailure({ thrownCode: code })).toBe("notAsked");
    for (const code of ["disconnected", "timeout", "internal", "unknown"]) expect(flipFailure({ thrownCode: code })).toBe("unknown");
    // no Hermes to run, and a request the page's client never sent: nothing was asked
    expect(flipFailure({ thrownCode: "no_hermes" })).toBe("notAsked");
    expect(flipFailure({ thrownCode: "disconnected", sent: false })).toBe("notAsked");
  });

  it("reads again on coming back only while a grant waits and nothing else runs", () => {
    expect(readOnReturn({ grantAsked: true, running: false, visible: true })).toBe(true);
    expect(readOnReturn({ grantAsked: true, running: true, visible: true })).toBe(false); // a flip or an install
    expect(readOnReturn({ grantAsked: true, running: false, visible: false })).toBe(false);
    expect(readOnReturn({ grantAsked: false, running: false, visible: true })).toBe(false);
  });

  it("turns a switch off with its reason, in order, and leaves it usable otherwise", () => {
    const st = read();
    expect(switchOff(bot(), { remote: false, status: st, state: "on" })).toBeNull();
    expect(switchOff(bot(), { remote: false, status: st, state: "off" })).toBeNull();
    expect(switchOff(bot(), { remote: true, status: st, state: "on" })).toEqual({ key: "cu.offRemote" });
    const peer = bot({ name: "mac:mini", host: { kind: "ssh", peer: "mac", label: "Mac mini", host: "me@mini" } });
    expect(switchOff(peer, { remote: false, status: st, state: undefined })).toEqual({ key: "cu.offPeer", vars: { computer: "Mac mini" } });
    expect(switchOff(bot(), { remote: false, status: read({ pinned: true }), state: "on" })).toEqual({ key: "cu.offPinned" });
    expect(switchOff(bot(), { remote: false, status: read({ platform: "freebsd", platform_supported: false }), state: "off" })).toEqual({
      key: "cu.unsupported",
      vars: { platform: "freebsd" },
    });
    expect(switchOff(bot(), { remote: false, status: st, state: "unknown", why: "offline" })).toEqual({ key: "cu.offOffline", vars: { bot: "Kami" } });
    expect(switchOff(bot(), { remote: false, status: st, state: "unknown", why: "unread" })).toEqual({ key: "cu.offUnread", vars: { bot: "Kami" } });
    // a status that could not be read does not hide the switch: it is the bot's own setting
    expect(switchOff(bot(), { remote: false, status: { read: false, pinned: false, line: "x" }, state: "off" })).toBeNull();
  });
});
