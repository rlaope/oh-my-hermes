import { describe, expect, it } from "vitest";
import type { Automation, Away } from "../lib/protocol";
import { botAutomations, botElsewhere, editDraft, fileProblem, memoryUse, PAGE_FILE_MAX } from "./botPage";

const job = (bot: string, name: string): Automation => ({
  id: `${bot}-${name}`,
  name,
  schedule: "every 30m",
  next_run_at: null,
  last_run_at: null,
  last_status: null,
  enabled: true,
  bot,
  paused: false,
  prompt: "",
  script: null,
  deliver: "local",
  origin: null,
  created_at: null,
  last_error: null,
  repeat: { times: null, completed: 0 },
});

const away = (id: string, running: boolean, last: number): Away => ({
  id,
  source: "slack",
  label: id,
  title: id,
  started_at: 0,
  last_active: last,
  message_count: 1,
  running,
});

describe("bot page helpers", () => {
  it("says why a file shows no text, and nothing for one that was read or is absent", () => {
    expect(fileProblem({ file: "SOUL.md", state: "ok", size: 10 })).toBeNull();
    expect(fileProblem({ file: "SOUL.md", state: "missing", size: null })).toBeNull();
    expect(fileProblem({ file: "memories/MEMORY.md", state: "too_big", size: 3 * 1024 * 1024 })).toBe(
      "memories/MEMORY.md is 3.0 MB, larger than the 1.0 MB omher reads, so it was not read.",
    );
    expect(fileProblem({ file: "SOUL.md", state: "unreadable", size: null })).toBe("SOUL.md could not be read.");
    expect(fileProblem({ file: "SOUL.md", state: "link", size: null })).toBe("SOUL.md is a link, so omher does not read it.");
    expect(PAGE_FILE_MAX).toBe(1 << 20);
  });

  it("measures a memory target against its limit, capped at 100 and flagged when over", () => {
    expect(memoryUse({ chars: 0, limit: 2200 })).toEqual({ pct: 0, over: false });
    expect(memoryUse({ chars: 1100, limit: 2200 })).toEqual({ pct: 50, over: false });
    expect(memoryUse({ chars: 2200, limit: 2200 })).toEqual({ pct: 100, over: false });
    expect(memoryUse({ chars: 2500, limit: 2200 })).toEqual({ pct: 100, over: true });
    // a limit of 0 (or below) is the limit Hermes enforces: nothing fits
    expect(memoryUse({ chars: 5, limit: 0 })).toEqual({ pct: 100, over: true });
    expect(memoryUse({ chars: 0, limit: 0 })).toEqual({ pct: 0, over: false });
  });

  it("keeps only this bot's automations, by name", () => {
    const list = [job("kami", "nightly"), job("friren", "digest"), job("kami", "brief")];
    expect(botAutomations(list, "kami").map((a) => a.name)).toEqual(["brief", "nightly"]);
    expect(botAutomations(null, "kami")).toEqual([]);
    expect(botAutomations(list, "peer:kami")).toEqual([]);
  });

  it("lists sessions elsewhere running first, then newest", () => {
    const rows = [away("old", false, 10), away("live", true, 5), away("new", false, 30)];
    expect(botElsewhere(rows).map((a) => a.id)).toEqual(["live", "new", "old"]);
    expect(botElsewhere(undefined)).toEqual([]);
  });

  it("drafts a request to the bot for each Edit, ending ready for the person's words", () => {
    expect(editDraft("soul")).toBe("Update your SOUL.md: ");
    expect(editDraft("memory")).toBe("Update your memory (memories/MEMORY.md): ");
    expect(editDraft("user")).toBe("Update what you remember about me (memories/USER.md): ");
  });
});
