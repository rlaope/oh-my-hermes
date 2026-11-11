// Guard: no hard-coded English in a component. Every .tsx under src is parsed and these must be empty of prose:
// JSX text, the UI attributes (title, placeholder, aria-label, alt, label, hint, tip), strings rendered as JSX
// children (either side of a ternary or ||), and `label`/`title`/`hint`/`placeholder`/`text` properties. A
// string a person reads goes through t() with a key in all four dictionaries. ALLOWED holds what stays as written
// in every language: brand, product and command names, key names, sample code.
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");

const ALLOWED = new Set([
  // brand and product names
  "omher",
  "OMH",
  "Hermes",
  // commands and sample code shown as code
  "/skill",
  "/plan",
  "dag ulw",
  "/v1/responses",
  "hermes profile create <name>",
  // key names
  "Ctrl+J",
  "Ctrl+.",
  "Esc",
]);

const UI_ATTRS = new Set(["title", "placeholder", "aria-label", "alt", "label", "hint", "tip", "aria-description"]);
const UI_PROPS = new Set(["label", "title", "hint", "placeholder", "text", "tip", "body", "desc", "description", "note", "sub", "empty"]);

/** Prose: a word of two or more letters that is not an i18n key, CSS, a test id or a path. */
const prose = (raw: string): boolean => {
  const s = raw.trim().replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  if (!/[A-Za-z]{2,}/.test(s) || ALLOWED.has(s)) return false;
  if (/^[a-z][\w-]*(\.[\w-]+)+$/.test(s)) return false; // an i18n key ("set.general")
  if (/var\(--|\d+px\b/.test(s)) return false; // CSS
  return true;
};

function files(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) files(p, out);
    else if (p.endsWith(".tsx") && !p.endsWith(".test.tsx")) out.push(p);
  }
  return out;
}

/** The string literals an expression renders as is: a literal, a template's text, either side of `?:`, `||`, `??`. */
function rendered(e: ts.Expression, out: string[]): void {
  if (ts.isStringLiteral(e) || ts.isNoSubstitutionTemplateLiteral(e)) out.push(e.text);
  else if (ts.isTemplateExpression(e)) out.push([e.head.text, ...e.templateSpans.map((s) => s.literal.text)].join(" "));
  else if (ts.isParenthesizedExpression(e)) rendered(e.expression, out);
  else if (ts.isConditionalExpression(e)) {
    rendered(e.whenTrue, out);
    rendered(e.whenFalse, out);
  } else if (ts.isBinaryExpression(e)) {
    const op = e.operatorToken.kind;
    if (op === ts.SyntaxKind.BarBarToken || op === ts.SyntaxKind.QuestionQuestionToken || op === ts.SyntaxKind.PlusToken) {
      rendered(e.left, out);
      rendered(e.right, out);
    } else if (op === ts.SyntaxKind.AmpersandAmpersandToken) rendered(e.right, out);
  }
}

/** `file:line text` for every hard-coded UI literal in `source`. */
export function hardCoded(name: string, source: string): string[] {
  const sf = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const hits: string[] = [];
  const hit = (node: ts.Node, text: string) => {
    if (!prose(text)) return;
    const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
    hits.push(`${name}:${line} ${JSON.stringify(text.trim().replace(/\s+/g, " "))}`);
  };
  const visit = (node: ts.Node): void => {
    if (ts.isJsxText(node)) hit(node, node.text);
    else if (ts.isJsxAttribute(node) && UI_ATTRS.has(node.name.getText(sf)) && node.initializer) {
      const lits: string[] = [];
      if (ts.isStringLiteral(node.initializer)) lits.push(node.initializer.text);
      else if (ts.isJsxExpression(node.initializer) && node.initializer.expression) rendered(node.initializer.expression, lits);
      lits.forEach((l) => hit(node, l));
    } else if (ts.isJsxExpression(node) && node.expression && (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))) {
      const lits: string[] = [];
      rendered(node.expression, lits);
      lits.forEach((l) => hit(node, l));
    } else if (ts.isPropertyAssignment(node) && UI_PROPS.has(node.name.getText(sf).replace(/["']/g, ""))) {
      const lits: string[] = [];
      rendered(node.initializer, lits);
      lits.forEach((l) => hit(node, l));
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return hits;
}

describe("no hard-coded UI English", () => {
  it("finds a literal in each place a person reads one", () => {
    const src = [
      "const A = [{ label: 'Deny' }];",
      "export const X = ({ on }: { on: boolean }) => (",
      "  <div title=\"Open chat\" aria-label={`Close ${'x'}`}>",
      "    Settings",
      "    {on ? 'Working' : t('bot.offline')}",
      "    <code>/plan</code> <b>omher</b> {t('set.general')}",
      "  </div>",
      ");",
    ].join("\n");
    expect(hardCoded("x.tsx", src).map((h) => h.split(" ").slice(1).join(" "))).toEqual([
      '"Deny"',
      '"Open chat"',
      '"Close"',
      '"Settings"',
      '"Working"',
    ]);
  });

  it("leaves none in src/**/*.tsx", () => {
    const hits = files(SRC).flatMap((f) => hardCoded(relative(SRC, f), readFileSync(f, "utf8")));
    expect(hits).toEqual([]);
  });
});
