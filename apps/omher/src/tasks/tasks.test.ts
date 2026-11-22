import { afterEach, describe, expect, it } from "vitest";
import { BODY_BYTES, cutBytes, firstMessage, threadTitle } from "./message";
import { MaskingTaskHost, MeFail, type TaskHost } from "./host";
import { getTasks, resetTasks, setBar, setFilter, setPage, setRepo, setSource } from "./state";
import { repoOk } from "./types";

const item = { number: 1836, title: "Measurement  path\nfor the composer", state: "open" as const, url: "https://github.com/rlaope/oh-my-hermes/issues/1836", labels: [], author: "p", created: 0, updated: 0, checks: null };

describe("Start in thread text", () => {
  it("titles the thread #<n> <title> on one line", () => {
    expect(threadTitle(item)).toBe("#1836 Measurement path for the composer");
  });

  it("is the URL, the title, the body and the ask", () => {
    expect(firstMessage({ item, body: "Steps:\r\n1. open" })).toBe(
      "https://github.com/rlaope/oh-my-hermes/issues/1836\n\n#1836 Measurement path for the composer\n\nSteps:\n1. open\n\nWork on this issue.",
    );
    expect(firstMessage({ item, body: "  " })).toBe("https://github.com/rlaope/oh-my-hermes/issues/1836\n\n#1836 Measurement path for the composer\n\nWork on this issue.");
  });

  it("cuts the body to 4 KB of UTF-8 on a character boundary", () => {
    const long = "가".repeat(3000); // 9000 bytes
    const cut = cutBytes(long, BODY_BYTES);
    expect(new TextEncoder().encode(cut).length).toBeLessThanOrEqual(BODY_BYTES);
    expect(cut.endsWith("…")).toBe(true);
    expect(cut.replace("…", "")).toMatch(/^가+$/);
    expect(cutBytes("short", BODY_BYTES)).toBe("short");
    const msg = firstMessage({ item, body: "x".repeat(10_000) });
    expect(msg.length).toBeLessThan(4096 + 200);
  });
});

describe("repository names", () => {
  it("takes owner/repo on GitHub and subgroups on GitLab, nothing that reads as an option or path", () => {
    expect(repoOk("github", "rlaope/oh-my-hermes")).toBe(true);
    expect(repoOk("github", "a/b/c")).toBe(false);
    expect(repoOk("github", "-R/x")).toBe(false);
    expect(repoOk("github", "../x")).toBe(false);
    expect(repoOk("github", "o/r x")).toBe(false);
    expect(repoOk("gitlab", "g/s/p")).toBe(true);
    expect(repoOk("gitlab", "g")).toBe(false);
  });
});

describe("tasks state", () => {
  afterEach(() => resetTasks());

  it("keeps a picked repository first in its source's recent list and saves no page", () => {
    expect(setRepo("github", "a/b")).toBe(true);
    expect(setRepo("github", "c/d", "/home/me/c")).toBe(true);
    expect(setRepo("github", "a/b")).toBe(true);
    expect(setRepo("github", "bad name")).toBe(false);
    expect(getTasks().recent.github).toEqual(["a/b", "c/d"]);
    expect(getTasks().folders["github:c/d"]).toBe("/home/me/c");
    setPage(3);
    setFilter("assigned");
    expect(getTasks().page).toBe(0);
    setSource("gitlab");
    setBar(false);
    expect(getTasks().bar).toBe(false);
    expect(getTasks().source).toBe("gitlab");
  });
});

describe("token-like text from a task never reaches the page or a thread", () => {
  const fake = `ghp_${"X".repeat(36)}`;
  const leaky: TaskHost = {
    kind: "mock",
    status: async () => ({ installed: true, signed_in: true }),
    list: async () => ({ items: [{ ...item, title: `leak ${fake}`, labels: [{ name: `sk-${"Z".repeat(20)}`, color: "" }] }], more: false }),
    view: async () => ({ item: { ...item, title: `leak ${fake}` }, body: `example credential ${fake}`, comments: [{ author: "p", body: `token=${fake}`, created: 0 }], checks: [] }),
    remote: async () => null,
    ghAccounts: async () => ({ installed: true, accounts: [] }),
    me: async () => ({
      items: [{ repo: "o/r", number: 1, title: `leak ${fake}`, url: "", pr: true, draft: false, state: "open", author: "p", labels: [{ name: `sk-${"Z".repeat(20)}`, color: "" }], created: 0, updated: 0, asked: true, ci: "", review: "", conflict: false, requested: 0 }],
      more: false,
    }),
  };

  it("masks the list, the drawer and the error line through the one masker", async () => {
    const h = new MaskingTaskHost(leaky);
    const p = await h.list("github", "o/r", "issues", "open", 0);
    expect(JSON.stringify(p)).not.toContain(fake);
    expect(p.items[0].title).toBe("leak ••••");
    expect(p.items[0].labels[0].name).toBe("••••");
    const d = await h.view("github", "o/r", "issues", 1);
    expect(JSON.stringify(d)).not.toContain(fake);
    expect(d.body).toBe("example credential ••••");
    expect(d.comments[0].body).toBe("token=••••");
    const failing = new MaskingTaskHost({ ...leaky, list: async () => Promise.reject(new Error(`failure credential=${fake}`)) });
    await expect(failing.list("github", "o/r", "issues", "open", 0)).rejects.toThrow("failure credential=••••");
  });

  it("masks the 나 list and its error line, keeping why it failed", async () => {
    const h = new MaskingTaskHost(leaky);
    const p = await h.me("octo@github.com", "review", 0);
    expect(JSON.stringify(p)).not.toContain(fake);
    expect(p.items[0].title).toBe("leak ••••");
    expect(p.items[0].labels[0].name).toBe("••••");
    const failing = new MaskingTaskHost({ ...leaky, me: async () => Promise.reject({ kind: "auth", line: `HTTP 401: Bad credentials ${fake}` }) });
    const err = await failing.me("octo@github.com", "review", 0).catch((e) => e);
    expect(err).toBeInstanceOf(MeFail);
    expect(err.kind).toBe("auth");
    expect(err.message).toBe("HTTP 401: Bad credentials ••••");
  });

  it("masks Start in thread's title and first message", () => {
    const leak = { ...item, title: `leak ${fake}` };
    expect(threadTitle(leak)).toBe("#1836 leak ••••");
    const msg = firstMessage({ item: leak, body: `example credential ${fake}` });
    expect(msg).not.toContain(fake);
    expect(msg).toContain("example credential ••••");
  });
});
