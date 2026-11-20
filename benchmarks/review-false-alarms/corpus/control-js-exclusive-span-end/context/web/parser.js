export class ParseError extends Error {
  /**
   * `span.start` is the index of the first bad character; `span.end` is one
   * past the last one (exclusive), the same convention as String.prototype.slice.
   */
  constructor(message, span) {
    super(message);
    this.span = span;
  }
}

export function parseNumberList(source) {
  const values = [];
  const item = /[^,\s]+/g;
  let match;
  while ((match = item.exec(source)) !== null) {
    const value = Number(match[0]);
    if (Number.isNaN(value)) {
      throw new ParseError("not a number", {
        start: match.index,
        end: match.index + match[0].length,
      });
    }
    values.push(value);
  }
  return values;
}
