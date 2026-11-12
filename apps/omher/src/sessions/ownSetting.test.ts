// audit O13: a session whose agent runs its own config without approvals or with full disk access says so, quietly,
// from what the agent itself reported; picking one of omher's modes replaces it.
import { describe, expect, it } from "vitest";
import { ownSetting } from "./ownSetting";
import { setLang } from "../i18n";

describe("the agent's own setting", () => {
  it("Codex with approval never and dangerFullAccess (its first session.info, codex-12-late-step-init.jsonl)", () => {
    expect(ownSetting({ mode: "", approval: "never", sandbox: "dangerFullAccess" })).toBe("No approvals · full disk access");
    expect(ownSetting({ mode: "", approval: "never", sandbox: "workspaceWrite" })).toBe("No approvals");
    expect(ownSetting({ mode: "", approval: "on-request", sandbox: "dangerFullAccess" })).toBe("Full disk access");
  });
  it("Claude Code's own bypassPermissions reads the same; its ask modes say nothing", () => {
    expect(ownSetting({ mode: "bypassPermissions", approval: "bypassPermissions" })).toBe("No approvals");
    for (const m of ["default", "plan", "acceptEdits"]) expect(ownSetting({ mode: m, approval: m })).toBeNull();
  });
  it("one of omher's modes picked: the label is that mode again", () => {
    for (const m of ["read-only", "ask", "auto"]) expect(ownSetting({ mode: m, approval: "never", sandbox: "dangerFullAccess" })).toBeNull();
  });
  it("a setting that still asks in a sandbox, or nothing reported, says nothing", () => {
    expect(ownSetting({ mode: "", approval: "untrusted", sandbox: "workspaceWrite" })).toBeNull();
    expect(ownSetting({})).toBeNull();
    expect(ownSetting(undefined)).toBeNull();
  });
  it("in the person's language", () => {
    setLang("ko");
    try {
      expect(ownSetting({ mode: "", approval: "never", sandbox: "dangerFullAccess" })).toBe("승인 없음 · 디스크 전체 접근");
    } finally {
      setLang("en");
    }
  });
});
