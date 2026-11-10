import { describe, expect, it } from "vitest";
import { AGENT_IDS, agentIcon } from "./AgentIcon";

describe("agentIcon", () => {
  it("maps every agent id the app names to its own mark", () => {
    const want: [string, string][] = [
      ["claude", "Claude Code"], ["codex", "Codex"], ["omh", "OMH"], ["pi", "pi"], ["omp", "omp"],
      ["grok", "Grok"], ["grokbot", "Grok Bot"], ["gemini", "Gemini CLI"], ["opencode", "opencode"],
      ["cursor", "Cursor"], ["amp", "Amp"], ["cline", "Cline"], ["copilot", "GitHub Copilot"], ["goose", "Goose"],
      ["kilo", "Kilo Code"], ["junie", "Junie"], ["qwen", "Qwen Code"], ["windsurf", "Windsurf"], ["trae", "TRAE"],
      ["roo", "Roo Code"], ["openai", "OpenAI"], ["gemini-app", "Gemini"],
    ];
    for (const [id, title] of want) {
      const m = agentIcon(id);
      expect(m.kind, id).not.toBe("letter");
      expect(m.id, id).toBe(id);
      expect(m.title, id).toBe(title);
    }
    expect(AGENT_IDS).toHaveLength(22);
    expect(new Set(AGENT_IDS)).toEqual(new Set(want.map(([id]) => id)));
  });

  it("takes the vendors' own spellings and any case", () => {
    expect(agentIcon("claudecode").id).toBe("claude");
    expect(agentIcon("GithubCopilot").id).toBe("copilot");
    expect(agentIcon("kilocode").id).toBe("kilo");
    expect(agentIcon("RooCode").id).toBe("roo");
    expect(agentIcon("geminicli").id).toBe("gemini");
    expect(agentIcon(" Codex ").id).toBe("codex");
  });

  it("an unknown id gets a letter mark", () => {
    const m = agentIcon("zed");
    expect(m).toMatchObject({ kind: "letter", id: null, letter: "Z", title: "zed" });
    expect(agentIcon("").kind).toBe("letter");
    expect(agentIcon(undefined)).toMatchObject({ kind: "letter", letter: "?" });
  });

  it("monochrome marks draw in currentColor; colour marks keep their own fills", () => {
    for (const id of ["grok", "grokbot", "openai", "cursor", "opencode", "cline", "copilot", "goose", "kilo", "roo", "windsurf"]) {
      const m = agentIcon(id);
      expect(m.kind === "svg" && m.mono, id).toBe(true);
    }
    for (const id of ["claude", "codex", "gemini", "amp", "junie", "qwen", "trae", "pi", "omp"]) {
      const m = agentIcon(id);
      expect(m.kind === "svg" && !m.mono && /fill="/.test(m.body), id).toBe(true);
    }
  });

  it("marks carry no <title> and no id that another mark also uses", () => {
    const ids: string[] = [];
    for (const id of AGENT_IDS) {
      const m = agentIcon(id);
      if (m.kind !== "svg") continue;
      expect(m.body).not.toMatch(/<title>|<\?xml|<svg/);
      expect(m.body.length, id).toBeGreaterThan(20);
      ids.push(...[...m.body.matchAll(/id="([^"]+)"/g)].map((x) => x[1]));
      for (const ref of m.body.matchAll(/url\(#([^)]+)\)/g)) expect(m.body, id).toContain(`id="${ref[1]}"`);
    }
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
