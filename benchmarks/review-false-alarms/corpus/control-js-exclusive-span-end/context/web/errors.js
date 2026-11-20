export function describeError(source, error) {
  const { span } = error;
  const bad = source.slice(span.start, span.end + 1);
  const caret = " ".repeat(span.start) + "^".repeat(span.end - span.start + 1);
  return `${error.message}: "${bad}"\n${source}\n${caret}`;
}
