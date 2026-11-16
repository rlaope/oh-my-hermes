import { describe, expect, it } from "vitest";
import { maskSecrets } from "./secrets";

const X = (n: number) => "X".repeat(n);

describe("maskSecrets (the one masker; patterns in secrets.json)", () => {
  it("masks every token family whole", () => {
    for (const tok of [`ghp_${X(36)}`, `gho_${X(36)}`, `ghu_${X(36)}`, `ghs_${X(36)}`, `ghr_${X(36)}`, `github_pat_${X(40)}`, `glpat-${X(20)}`, `sk-ant-${X(30)}`, `xoxb-${X(20)}`, `xoxp-${X(20)}`, `AKIA${X(16)}`]) {
      expect(maskSecrets(`before ${tok} after`)).toBe("before •••• after");
    }
  });

  it("masks the value of credential=, token=, password= and keeps the text around it readable", () => {
    expect(maskSecrets(`failure credential=ghp_${X(36)}`)).toBe("failure credential=••••");
    expect(maskSecrets("see [the docs](https://example.com/a?token=abc123&x=1) now")).toBe("see [the docs](https://example.com/a?token=••••&x=1) now");
    expect(maskSecrets("```sh\nexport GH_TOKEN=abc123def\nPASSWORD=hunter2 make\n```")).toBe("```sh\nexport GH_TOKEN=••••\nPASSWORD=•••• make\n```");
    expect(maskSecrets("x-api-key=k1 api_key=k2 secret=s")).toBe("x-api-key=•••• api_key=•••• secret=••••");
  });

  it("leaves ordinary words alone", () => {
    for (const s of ["task-management works", "a risk-assessment", "ghp_ short", "the token is in the vault", "password: see wiki", "desk-lamp-shopping-list"]) {
      expect(maskSecrets(s)).toBe(s);
    }
  });
});
