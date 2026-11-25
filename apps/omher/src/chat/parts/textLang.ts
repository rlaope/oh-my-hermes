/** `"ko"` for text written in Korean, for the `lang` of the element that shows it; otherwise undefined.
 *  Only Korean keeps words whole (`[lang="ko"]` in theme/base.css sets `word-break: keep-all`), and that rule follows
 *  the UI language. A bot's Korean reply in an English, Japanese or Chinese window would break between any two
 *  syllables without it, and keep-all on every bubble would make a Japanese or Chinese sentence break only at its
 *  punctuation. Hangul with no kana reads as Korean; Han characters alone do not (they are Chinese or Japanese too). */
export function koText(text: string | undefined): "ko" | undefined {
  if (!text || !/[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]/.test(text)) return undefined;
  return /[\u3040-\u30ff]/.test(text) ? undefined : "ko";
}
