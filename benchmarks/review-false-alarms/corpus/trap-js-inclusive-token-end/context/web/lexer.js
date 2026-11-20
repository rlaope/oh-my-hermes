/**
 * Splits a query into words.
 *
 * `text` is the word lowercased. `start` and `end` are the indexes of the
 * word's first and last character in the input: both ends are inclusive, so
 * a one-character word has start === end. The error caret relies on this too.
 */
export function tokenize(input) {
  const tokens = [];
  const word = /\S+/g;
  let match;
  while ((match = word.exec(input)) !== null) {
    tokens.push({
      text: match[0].toLowerCase(),
      start: match.index,
      end: match.index + match[0].length - 1,
    });
  }
  return tokens;
}
