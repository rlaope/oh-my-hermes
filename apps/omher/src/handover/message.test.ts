import { describe, expect, it } from "vitest";
import { GOAL_CHARS, STAT_FILES, codeSpan, goalLine, handoverMessage, handoverTitle, worktreeOf, type HandoverFacts } from "./message";

const WT = { path: "/w/gateway-keepalive", branch: "fix/keepalive", head: "3f2c1a9e0" };
const DIFF: HandoverFacts["diff"] = {
  scope: "uncommitted",
  truncated: false,
  files: [
    { path: "gateway/upstream.py", add: 1, del: 1 },
    { path: "tests/test_upstream.py", add: 3, del: 0 },
    { path: "notes/재시도.md", add: 0, del: 0, untracked: true },
  ],
};
const CLOSING = "Nothing was moved or closed: the folder, its files and any terminal open in it stay as they are. Work there with your own tools.";

describe("handoverMessage", () => {
  it("a worktree with uncommitted changes: folder, branch, status, diff stat, goal, closing line", () => {
    expect(handoverMessage({ folder: WT.path, worktree: WT, diff: DIFF, goal: "  finish the keepalive fix\nand open a PR " })).toBe(
      [
        "Handover from omher: pick up the work in this folder.",
        [
          "- Folder: `/w/gateway-keepalive`",
          "- Branch: `fix/keepalive` at 3f2c1a9",
          "- Status: 2 changed files, 1 untracked",
          "- Diff stat (uncommitted, vs HEAD): 2 files, +4 -1",
          "  - `gateway/upstream.py` +1 -1",
          "  - `tests/test_upstream.py` +3 -0",
          "  - `notes/재시도.md` untracked",
        ].join("\n"),
        "Goal: finish the keepalive fix and open a PR",
        CLOSING,
      ].join("\n\n"),
    );
  });

  it("is the same text for the same facts (deterministic) and leaves out an empty goal", () => {
    const f = { folder: WT.path, worktree: WT, diff: DIFF, goal: "   " };
    expect(handoverMessage(f)).toBe(handoverMessage({ ...f }));
    expect(handoverMessage(f)).not.toContain("Goal:");
  });

  it("a clean worktree says clean and stats the last commit", () => {
    const text = handoverMessage({ folder: "/w/gateway", worktree: { path: "/w/gateway", branch: "main", head: "a91b0c2d4" }, diff: { scope: "last commit", truncated: false, files: [{ path: "docs/notes.md", add: 2, del: 0 }] }, goal: "" });
    expect(text).toContain("- Status: clean, no uncommitted changes\n- Last commit: 1 file, +2 -0\n  - `docs/notes.md` +2 -0");
  });

  it("a folder inside a worktree names both; a detached head says so", () => {
    const text = handoverMessage({ folder: "/w/gateway-keepalive/gateway", worktree: { ...WT, branch: "" }, diff: DIFF, goal: "" });
    expect(text).toContain("- Folder: `/w/gateway-keepalive/gateway`\n- Worktree: `/w/gateway-keepalive`\n- Branch: detached at 3f2c1a9");
  });

  it("a folder outside the bot's worktrees carries no git facts and asks the bot to read them itself", () => {
    const text = handoverMessage({ folder: "/home/you/code/web-app", worktree: null, diff: null, goal: "" });
    expect(text).toBe(
      [
        "Handover from omher: pick up the work in this folder.",
        "- Folder: `/home/you/code/web-app`\n- Git: omher did not read this folder's status; check it with `git status` and `git diff --stat` there.",
        CLOSING,
      ].join("\n\n"),
    );
  });

  it("a worktree whose diff could not be read keeps its branch and says git was not read", () => {
    const text = handoverMessage({ folder: WT.path, worktree: WT, diff: null, goal: "" });
    expect(text).toContain("- Branch: `fix/keepalive` at 3f2c1a9\n- Git: omher did not read");
    expect(text).not.toContain("Status:");
  });

  it("paths with spaces and Windows paths are written as they are, in code spans", () => {
    const win = "C:\\Users\\me\\My Projects\\web_app";
    const text = handoverMessage({ folder: win, worktree: { path: win, branch: "feat/a_b", head: "" }, diff: { scope: "uncommitted", truncated: false, files: [{ path: "src/new file.ts", add: 5, del: 0 }] }, goal: "" });
    expect(text).toContain("- Folder: `C:\\Users\\me\\My Projects\\web_app`\n- Branch: `feat/a_b`\n");
    expect(text).toContain("  - `src/new file.ts` +5 -0");
    expect(text).not.toContain("Worktree:");
    const mac = handoverMessage({ folder: "/Users/me/Library/Mobile Documents/app", worktree: null, diff: null, goal: "" });
    expect(mac).toContain("- Folder: `/Users/me/Library/Mobile Documents/app`");
  });

  it("lists at most STAT_FILES files by name and counts the rest; a cut list says so", () => {
    const files = Array.from({ length: STAT_FILES + 3 }, (_, i) => ({ path: `f${i}.ts`, add: 1, del: 0 }));
    const text = handoverMessage({ folder: WT.path, worktree: WT, diff: { scope: "uncommitted", truncated: true, files }, goal: "" });
    expect(text).toContain(`- Status: ${STAT_FILES + 3} changed files, 0 untracked (list cut)`);
    expect(text).toContain(`  - \`f${STAT_FILES - 1}.ts\` +1 -0\n  - and 3 more`);
    expect(text).not.toContain(`\`f${STAT_FILES}.ts\``);
  });
});

describe("codeSpan", () => {
  it("fences longer than any backtick run inside and pads an edge backtick", () => {
    expect(codeSpan("a b")).toBe("`a b`");
    expect(codeSpan("a`b")).toBe("``a`b``");
    expect(codeSpan("`x")).toBe("`` `x ``");
    expect(codeSpan("a``b`")).toBe("``` a``b` ```");
  });
});

describe("goalLine", () => {
  it("one line, cut to GOAL_CHARS characters", () => {
    expect(goalLine("a\n\tb  c")).toBe("a b c");
    const long = "가".repeat(GOAL_CHARS + 10);
    const cut = goalLine(long);
    expect([...cut]).toHaveLength(GOAL_CHARS);
    expect(cut.endsWith("…")).toBe(true);
  });
});

describe("handoverTitle", () => {
  it("the folder's last part and its branch (else the short head)", () => {
    expect(handoverTitle({ folder: "/w/gateway-keepalive/", worktree: WT })).toBe("gateway-keepalive (fix/keepalive)");
    expect(handoverTitle({ folder: "C:\\code\\My App", worktree: { ...WT, branch: "" } })).toBe("My App (3f2c1a9)");
    expect(handoverTitle({ folder: "/home/you/code/web-app", worktree: null })).toBe("web-app");
  });
});

describe("worktreeOf", () => {
  const trees = [
    { path: "/w/gateway", n: 1 },
    { path: "/w/gateway/sub/inner", n: 2 },
    { path: "C:\\Code\\App", n: 3 },
  ];
  it("the worktree itself or one holding the folder, the deepest first", () => {
    expect(worktreeOf("/w/gateway", trees)?.n).toBe(1);
    expect(worktreeOf("/w/gateway/", trees)?.n).toBe(1);
    expect(worktreeOf("/w/gateway/src", trees)?.n).toBe(1);
    expect(worktreeOf("/w/gateway/sub/inner/x", trees)?.n).toBe(2);
  });
  it("never a sibling with the same prefix, nor a folder outside", () => {
    expect(worktreeOf("/w/gateway-keepalive", trees)).toBeNull();
    expect(worktreeOf("/home/you", trees)).toBeNull();
    expect(worktreeOf("", trees)).toBeNull();
  });
  it("a Windows path matches with either separator and any case", () => {
    expect(worktreeOf("c:/code/app/src", trees)?.n).toBe(3);
    expect(worktreeOf("C:\\CODE\\APP", trees)?.n).toBe(3);
    expect(worktreeOf("C:\\Code\\Apple", trees)).toBeNull();
  });
});
