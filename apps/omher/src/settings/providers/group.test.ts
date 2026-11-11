import { describe, expect, it } from "vitest";
import { countLabel, filterGroups, groupModels, splitModel } from "./group";

describe("provider model groups", () => {
  it("splits the vendor prefix and a :free-style suffix", () => {
    expect(splitModel("liquid/lfm-3-1.7b:free")).toEqual({ vendor: "liquid", entry: { id: "liquid/lfm-3-1.7b:free", name: "lfm-3-1.7b", tag: "free" } });
    expect(splitModel("Opus 5.5")).toEqual({ vendor: "", entry: { id: "Opus 5.5", name: "Opus 5.5", tag: "" } });
  });

  it("groups by vendor in first-seen order and leads with the current model", () => {
    const g = groupModels(["anthropic/a", "openai/x", "google/g", "openai/y:free", "openai/z"], "openai/z");
    expect(g.map((x) => x.vendor)).toEqual(["openai", "anthropic", "google"]);
    expect(g[0].models.map((e) => e.name)).toEqual(["z", "x", "y"]);
    expect(g[0].models[2].tag).toBe("free");
  });

  it("keeps the order when the current model is not listed", () => {
    expect(groupModels(["b/1", "a/2"], "c/3").map((x) => x.vendor)).toEqual(["b", "a"]);
  });

  it("filters on the full id and drops empty groups", () => {
    const g = groupModels(["anthropic/claude", "liquid/lfm:free", "openai/gpt"]);
    expect(filterGroups(g, " FREE ").map((x) => x.vendor)).toEqual(["liquid"]);
    expect(filterGroups(g, "")).toBe(g);
  });

  it("labels the count", () => {
    expect([0, 1, 62].map(countLabel)).toEqual(["No models", "1 model", "62 models"]);
  });
});
