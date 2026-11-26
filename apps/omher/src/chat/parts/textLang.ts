/** `"ko"` when a text is written in Korean, for the `lang` of the element that shows it; otherwise undefined.
 *  Only Korean keeps words whole (`[lang="ko"]` in theme/base.css sets `word-break: keep-all`), and that rule follows
 *  the UI language. A bot's Korean reply in an English, Japanese or Chinese window would break between any two
 *  syllables without it, and keep-all on every bubble would make a Japanese or Chinese sentence break only at its
 *  punctuation.
 *  Korean means Hangul is the text's main script, not merely present: code (fenced and inline) and URLs are left out,
 *  then Hangul must be at least twice the Han characters and kana letters together, and at least a third of all the
 *  words, a Latin word counting as one and a Hangul, Han or kana character as one each. So an English paragraph with
 *  one Korean word, a Chinese or Japanese sentence quoting one, and an English answer whose code holds '안녕' stay
 *  unmarked (screen readers keep their voice, ja/zh keep their line breaking), and Korean with English product names
 *  in it is Korean. Kana letters only: "・" and "ー" are shared punctuation. */
const HANGUL = /[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]/g;
const HAN = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/g;
const KANA = /[\u3041-\u3096\u30a1-\u30fa]/g;
const LATIN_WORD = /[A-Za-z]+/g;

export function koText(text: string | undefined): "ko" | undefined {
  if (!text) return undefined;
  const prose = text.replace(/```[\s\S]*?(```|$)/g, " ").replace(/`[^`\n]*`/g, " ").replace(/\b(?:https?|file):\/\/\S+/g, " ");
  const n = (re: RegExp) => prose.match(re)?.length ?? 0;
  const hangul = n(HANGUL);
  if (!hangul) return undefined;
  const cjk = n(HAN) + n(KANA);
  const all = hangul + cjk + n(LATIN_WORD);
  return hangul >= 2 * cjk && hangul * 3 >= all ? "ko" : undefined;
}
