// Shell picker (kshell): the shells this computer offers come from the shell as a list of ids, the page sends back
// only an id, the setting and the saved row keep only a well-formed id, and the mock host maps an id that is not on
// its list to the default shell and says which one was missing.
import { describe, expect, it } from "vitest";
import { cleanShellId, parseTermSettings, TERM_DEFAULTS } from "./term/settings";
import { parseResume } from "../app/resume";
import { MOCK_SHELLS, MockShellHost, type MockShellCall } from "../terminal/host";

describe("shell ids", () => {
  it("keeps only the ids shells_available makes", () => {
    for (const ok of ["powershell", "pwsh", "cmd", "gitbash", "wsl", "unix:/bin/zsh", "unix:/opt/homebrew/bin/fish"]) expect(cleanShellId(ok)).toBe(ok);
    for (const bad of ["", "zsh", "/bin/zsh", "bash -l", "unix:bin/zsh", "unix:/bin/zsh\n-c", "powershell.exe", "cmd /c calc", 42, null, undefined, {}, "unix:/" + "a".repeat(700)])
      expect(cleanShellId(bad)).toBe("");
  });

  it("Settings › Terminal › Default shell defaults to the login shell and keeps a picked id", () => {
    expect(TERM_DEFAULTS.defaultShell).toBe("");
    expect(parseTermSettings(null).defaultShell).toBe("");
    expect(parseTermSettings({ defaultShell: "unix:/opt/homebrew/bin/fish" }).defaultShell).toBe("unix:/opt/homebrew/bin/fish");
    expect(parseTermSettings({ defaultShell: "/bin/sh -c 'x'" }).defaultShell).toBe("");
  });

  it("a saved Shell row keeps its shell id across a restart", () => {
    const raw = (shell: unknown) =>
      JSON.stringify({ v: 1, at: 1, bot: null, view: "chat", session: null, panelOpen: false, panelTab: "runs", runsFull: false, runId: null, drafts: {}, sessions: [{ id: "s1", agent: "shell", cwd: "/home/you", startedAt: 1, view: "terminal", running: true, shell }] });
    expect(parseResume(raw("gitbash"))?.sessions[0].shell).toBe("gitbash");
    expect(parseResume(raw("rm -rf /"))?.sessions[0].shell).toBeUndefined();
  });
});

describe("mock shell host", () => {
  const start = async (h: MockShellHost, shell?: string) => {
    let out = "";
    const got = await h.start("/home/you/code", 80, 24, (d) => (out += d), () => undefined, shell);
    await new Promise((r) => setTimeout(r, 40));
    return { got, out };
  };

  it("lists three shells, the default first", async () => {
    const h = new MockShellHost({});
    const list = await h.shells();
    expect(list.map((s) => s.id)).toEqual(MOCK_SHELLS.map((s) => s.id));
    expect(list.filter((s) => s.default).map((s) => s.label)).toEqual(["zsh"]);
  });

  it("starts the shell picked by id, and the default for an id it does not have", async () => {
    const g: { __omherShellCalls?: MockShellCall[] } = {};
    const h = new MockShellHost(g);
    const fish = await start(h, "unix:/opt/homebrew/bin/fish");
    expect(fish.got.missing).toBeUndefined();
    expect(fish.out).toContain("fish login shell in /home/you/code");
    const gone = await start(h, "gitbash");
    expect(gone.got.missing).toBe("gitbash");
    expect(gone.out).toContain("(mock) login shell in");
    const plain = await start(h);
    expect(plain.got.missing).toBeUndefined();
    expect(g.__omherShellCalls?.filter((c) => c.op === "start").map((c) => (c.op === "start" ? c.shell : null))).toEqual(["unix:/opt/homebrew/bin/fish", "gitbash", undefined]);
  });
});
