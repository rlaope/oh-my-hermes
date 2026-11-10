// UI strings by key, in English, Korean, Japanese and Chinese. English is the source: every key lives in `en`, and
// the other three carry the same keys with the same `{slots}` (i18n.test.ts). The app shows English unless
// `omher.lang` in localStorage names another language; there is no picker yet. Strings written before this module
// are still literals in their components: a new string gets a key here.
import { en } from "./en";
import { ja } from "./ja";
import { ko } from "./ko";
import { zh } from "./zh";

export type Lang = "en" | "ko" | "ja" | "zh";
export type Key = keyof typeof en;
export const LANGS: readonly Lang[] = ["en", "ko", "ja", "zh"];
export const DICT: Record<Lang, Record<Key, string>> = { en, ko, ja, zh };
export const LANG_KEY = "omher.lang";

/** The stored language, or English when none (or an unknown one) is stored. */
export function readLang(store: Pick<Storage, "getItem"> | undefined = typeof localStorage === "undefined" ? undefined : localStorage): Lang {
  try {
    const v = store?.getItem(LANG_KEY);
    return LANGS.includes(v as Lang) ? (v as Lang) : "en";
  } catch {
    return "en";
  }
}

let current: Lang = readLang();
export const lang = (): Lang => current;
/** Switch the language for strings read from now on (tests; a picker would re-render after it). */
export const setLang = (l: Lang) => {
  current = l;
};

/** `t("plans.of", { bot: "Kami" })`: the string for `key` in the current language, its `{slots}` filled. */
export function t(key: Key, vars?: Record<string, string | number>, l: Lang = current): string {
  const s = DICT[l][key] ?? en[key];
  return vars ? s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m)) : s;
}
