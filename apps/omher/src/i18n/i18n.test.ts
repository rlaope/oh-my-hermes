import { afterEach, describe, expect, it } from "vitest";
import { isValidElement, type ReactElement } from "react";
import { detectLang, DICT, LANG_KEY, LANGS, listText, readLang, setLang, t, tx, type Key } from "./index";

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
    expect(t("graph.done", { done: 3, total: 7 })).toBe("3 of 7 done");
    expect(t("graph.done", { done: 3 })).toBe("3 of {total} done");
    setLang("ko");
    expect(t("graph.done", { done: 3, total: 7 })).toBe("7개 중 3개 완료");
  });

  it("uses the stored language; with none, an onboarded install stays English", () => {
    const store = (v: string | null) => ({ getItem: (k: string) => (k === LANG_KEY ? v : k === "omher.onboarded" ? "1" : null) });
    expect(readLang(store(null), ["zh-CN"])).toBe("en");
    expect(readLang(store("ja"), ["zh-CN"])).toBe("ja");
    expect(readLang(store("fr"), ["ko"])).toBe("en");
    expect(readLang(undefined, ["ko"])).toBe("en");
    expect(
      readLang({
        getItem: () => {
          throw new Error("no storage");
        },
      }),
    ).toBe("en");
  });

  it("on a first run (nothing stored, not onboarded) takes the system's language; any zh-* is zh", () => {
    const fresh = { getItem: () => null };
    expect(readLang(fresh, ["zh-CN", "en-US"])).toBe("zh");
    expect(readLang(fresh, ["zh-TW"])).toBe("zh");
    expect(readLang(fresh, ["zh-Hans-CN"])).toBe("zh");
    expect(readLang(fresh, ["ja-JP"])).toBe("ja");
    expect(readLang(fresh, ["ko-KR"])).toBe("ko");
    expect(readLang(fresh, ["fr-FR", "de"])).toBe("en");
    expect(readLang(fresh, ["fr-FR", "ko"])).toBe("ko");
    expect(readLang(fresh, undefined)).toBe("en");
    expect(detectLang(["en-GB", "zh-CN"])).toBe("en");
    expect(detectLang([])).toBe("en");
  });

  it("sets <html lang> with the language (zh is zh-CN)", () => {
    const doc = { documentElement: { lang: "en" } };
    const g = globalThis as { document?: unknown };
    const had = g.document;
    g.document = doc;
    try {
      setLang("zh");
      expect(doc.documentElement.lang).toBe("zh-CN");
      setLang("ja");
      expect(doc.documentElement.lang).toBe("ja");
    } finally {
      g.document = had;
    }
  });

  it("tx keeps markup in a slot and the translation's word order", () => {
    setLang("zh");
    const out = tx("pv.manual", { cmd: "CMD" }) as ReactElement<{ children: unknown[] }>;
    expect(isValidElement(out)).toBe(true);
    const flat = (n: unknown): string =>
      Array.isArray(n) ? n.map(flat).join("") : isValidElement(n) ? flat((n.props as { children?: unknown }).children) : String(n ?? "");
    expect(flat(out.props.children)).toBe("请在终端中运行 CMD。");
  });

  it("joins a list the way each language does", () => {
    expect(listText(["Slack", "Discord", "Telegram"], "en")).toBe("Slack, Discord and Telegram");
    expect(listText(["Slack", "Discord"], "zh")).toBe("Slack和Discord");
  });

  it("keeps brand, model and command names in Latin in every language", () => {
    for (const l of LANGS) {
      for (const k of ["omh.pop.body", "update.thenMixed", "acc.headerLine", "gate.text", "cmp.skillHint"] as Key[]) {
        for (const name of DICT.en[k].match(/Claude Code|Codex|Hermes|oh-my-hermes|omher|OmO|pi\b/g) ?? []) expect(DICT[l][k], `${l} ${k}`).toContain(name);
      }
    }
  });

  it("writes Simplified, not Traditional, Chinese", () => {
    const traditional = /[們這個說時麼對會還點開關發連線帳號設處於與為將應單選擇檔顯視窗鍵輸]/;
    for (const k of keys) expect(DICT.zh[k], k).not.toMatch(traditional);
  });

  it("zh calls a bot's reply 回复, and Settings descriptions end with 。", () => {
    for (const k of ["sounds.hint", "set.reasoningHint", "key.stop", "row.answering", "ss.answering", "note.failed"] as Key[]) {
      expect(DICT.zh[k], k).toContain("回复");
      expect(DICT.zh[k], k).not.toContain("回答");
    }
    const hints = keys.filter((k) => /^(set|look)\.\w*Hint2?$/.test(k) || ["sounds.hint", "lang.hint", "set.profileDefault", "set.profileHere"].includes(k));
    for (const k of hints) expect(DICT.zh[k], k).toMatch(/。$/);
  });
});
