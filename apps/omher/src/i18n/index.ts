// UI strings by key, in English, Korean, Japanese and Chinese. English is the source: every key lives in `en`, and
// the other three carry the same keys with the same `{slots}` (i18n.test.ts). On a first run (no `omher.lang` and
// not onboarded yet) the language comes from the system's preferred languages and is saved; after that it comes
// from `omher.lang`, which Settings › General › Language (and the first-run card) writes through the store's
// setLanguage, so the app re-renders without a restart. literals.test.ts fails on new hard-coded English.
import { Fragment, createElement, type ReactNode } from "react";
import { en } from "./en";
import { ja } from "./ja";
import { ko } from "./ko";
import { zh } from "./zh";

export type Lang = "en" | "ko" | "ja" | "zh";
export type Key = keyof typeof en;
export const LANGS: readonly Lang[] = ["en", "ko", "ja", "zh"];
export const DICT: Record<Lang, Record<Key, string>> = { en, ko, ja, zh };
export const LANG_KEY = "omher.lang";
/** Each language in its own words, for the picker. */
export const LANG_NAMES: Record<Lang, string> = { en: "English", ko: "한국어", ja: "日本語", zh: "中文" };
/** The BCP 47 tag for `<html lang>` and dates: zh is Simplified Chinese. */
export const LANG_TAG: Record<Lang, string> = { en: "en", ko: "ko", ja: "ja", zh: "zh-CN" };

/** The first of the system's languages omher speaks (any `zh-*` is zh), else English. */
export function detectLang(prefs: readonly string[] | undefined): Lang {
  for (const p of prefs ?? []) {
    const base = p.toLowerCase().split(/[-_]/)[0];
    if (LANGS.includes(base as Lang)) return base as Lang;
  }
  return "en";
}

type Store = Pick<Storage, "getItem">;
const browserStore = (): Storage | undefined => (typeof localStorage === "undefined" ? undefined : localStorage);
const browserPrefs = (): readonly string[] | undefined =>
  typeof navigator === "undefined" ? undefined : navigator.languages?.length ? navigator.languages : [navigator.language];

/** The language to show: `omher.lang` when it names one; else on a first run only (not yet onboarded) the system's
 *  language; an install that already ran without choosing one stays English. */
export function readLang(store: Store | undefined = browserStore(), prefs: readonly string[] | undefined = browserPrefs()): Lang {
  try {
    const v = store?.getItem(LANG_KEY);
    if (LANGS.includes(v as Lang)) return v as Lang;
    if (store && store.getItem("omher.onboarded") !== "1") return detectLang(prefs);
    return "en";
  } catch {
    return "en";
  }
}

/** readLang, and a language picked from the system on first run is saved, so it outlives the first-run card. */
function bootLang(): Lang {
  const store = browserStore();
  const l = readLang(store);
  try {
    if (store && !store.getItem(LANG_KEY) && store.getItem("omher.onboarded") !== "1") store.setItem(LANG_KEY, l);
  } catch {
    /* no storage: the language holds for this run */
  }
  return l;
}

let current: Lang = "en";
export const lang = (): Lang => current;
/** The current language as a locale tag, for `toLocaleDateString` and friends. */
export const locale = (): string => LANG_TAG[current];
/** Switch the language for strings read from now on and tell the page (`<html lang>` picks the CJK glyphs). The
 *  store's `setLanguage` calls it and then re-renders. */
export const setLang = (l: Lang) => {
  current = l;
  if (typeof document !== "undefined") document.documentElement.lang = LANG_TAG[l];
};
setLang(bootLang());

/** `t("plans.of", { bot: "Kami" })`: the string for `key` in the current language, its `{slots}` filled. */
export function t(key: Key, vars?: Record<string, string | number>, l: Lang = current): string {
  const s = DICT[l][key] ?? en[key];
  return vars ? s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m)) : s;
}

/** `t` for a sentence that holds markup: each `{slot}` takes text or an element (`<code>`, a link), so the
 *  translation keeps its own word order. */
export function tx(key: Key, vars: Record<string, ReactNode>, l: Lang = current): ReactNode {
  const parts = (DICT[l][key] ?? en[key]).split(/\{(\w+)\}/g);
  return createElement(
    Fragment,
    null,
    ...parts.map((p, i) => (i % 2 === 1 ? createElement(Fragment, { key: i }, p in vars ? vars[p] : `{${p}}`) : p)),
  );
}

/** "Slack, Discord and Telegram" in the current language (English without the serial comma, as omher writes it). */
export function listText(items: string[], l: Lang = current): string {
  return new Intl.ListFormat(l === "en" ? "en-GB" : LANG_TAG[l], { type: "conjunction" }).format(items);
}
