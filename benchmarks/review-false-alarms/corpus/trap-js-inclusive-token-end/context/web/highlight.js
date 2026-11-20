import { tokenize } from "./lexer.js";

function escapeHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function highlight(text, terms) {
  const wanted = new Set(terms.map((term) => term.toLowerCase()));
  let out = "";
  let cursor = 0;
  for (const token of tokenize(text)) {
    if (!wanted.has(token.text)) continue;
    out += escapeHtml(text.slice(cursor, token.start));
    out += "<mark>" + escapeHtml(text.slice(token.start, token.end + 1)) + "</mark>";
    cursor = token.end + 1;
  }
  return out + escapeHtml(text.slice(cursor));
}
