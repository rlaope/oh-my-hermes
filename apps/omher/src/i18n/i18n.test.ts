import { afterEach, describe, expect, it } from "vitest";
import { DICT, LANG_KEY, LANGS, readLang, setLang, t, type Key } from "./index";

const slots = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
const keys = Object.keys(DICT.en) as Key[];

describe("i18n", () => {
  afterEach(() => setLang("en"));

  it("carries every key in en, ko, ja and zh, none empty", () => {
    expect(LANGS).toEqual(["en", "ko", "ja", "zh"]);
    for (const l of LANGS) {
      expect(Object.keys(DICT[l]).sort(), l).toEqual([...keys].sort());
      for (const k of keys) expect(DICT[l][k].trim(), `${l} ${k}`).not.toBe("");
    }
  });

  it("keeps each key's {slots} the same in every language", () => {
    for (const l of LANGS) for (const k of keys) expect(slots(DICT[l][k]), `${l} ${k}`).toEqual(slots(DICT.en[k]));
  });

  it("names the run list Plans: 계획, 計画, 计划", () => {
    expect(LANGS.map((l) => t("plans.tab", undefined, l))).toEqual(["Plans", "계획", "計画", "计划"]);
  });

  it("fills slots, and leaves a slot it has no value for as written", () => {
    expect(t("graph.done", { done: 3, total: 7 })).toBe("Done 3/7");
    expect(t("graph.done", { done: 3 })).toBe("Done 3/{total}");
    setLang("ko");
    expect(t("graph.done", { done: 3, total: 7 })).toBe("완료 3/7");
  });

  it("shows English unless a known language is stored", () => {
    const store = (v: string | null) => ({ getItem: (k: string) => (k === LANG_KEY ? v : null) });
    expect(readLang(store(null))).toBe("en");
    expect(readLang(store("ja"))).toBe("ja");
    expect(readLang(store("fr"))).toBe("en");
    expect(readLang(undefined)).toBe("en");
    expect(
      readLang({
        getItem: () => {
          throw new Error("no storage");
        },
      }),
    ).toBe("en");
  });
});
