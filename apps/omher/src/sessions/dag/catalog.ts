// A closed read-only profile of A2UI 1.0. The upstream schemas + offline conformance test are in tests/a2ui-v1.
// This is a snapshot renderer, not a protocol session or an interpreter for arbitrary catalogs.
export const catalogId = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json";
type RecordNode = { id: string } & (
  | { component: "Card"; child: string }
  | { component: "Column"; children: string[] }
  | { component: "Divider"; axis: "horizontal" }
  | { component: "Text"; text: string; variant: "body" | "caption" }
);
const object = (x: unknown): x is Record<string, unknown> => !!x && typeof x === "object" && !Array.isArray(x);
const keys = (x: Record<string, unknown>, ...allowed: string[]) =>
  Object.keys(x).length === allowed.length && allowed.every((k) => Object.hasOwn(x, k));
const id = (x: unknown): x is string => typeof x === "string" && /^[a-z][a-z0-9-]{0,63}$/.test(x);
function component(x: unknown): x is RecordNode {
  if (!object(x) || !id(x.id)) return false;
  switch (x.component) {
    case "Text": return keys(x, "id", "component", "text", "variant") && typeof x.text === "string" && x.text.length <= 32768 && (x.variant === "body" || x.variant === "caption");
    case "Card": return keys(x, "id", "component", "child") && id(x.child);
    case "Column": return keys(x, "id", "component", "children") && Array.isArray(x.children) && x.children.length <= 512 && x.children.every(id);
    case "Divider": return keys(x, "id", "component", "axis") && x.axis === "horizontal";
    default: return false;
  }
}
/** Validate the entire message before resolving a single child. Reject shared subtrees as well as cycles,
 *  excessive depth, dangling references and unreachable records; no partial rendering. */
export function readSurface(message: unknown): Map<string, RecordNode> | null {
  if (!object(message) || !keys(message, "version", "createSurface") || message.version !== "1.0") return null;
  const s = message.createSurface;
  if (!object(s) || !keys(s, "surfaceId", "catalogId", "components") || s.catalogId !== catalogId || !id(s.surfaceId) ||
      !Array.isArray(s.components) || !s.components.length || s.components.length > 512) return null;
  const records = new Map<string, RecordNode>();
  for (const item of s.components) {
    if (!component(item) || records.has(item.id)) return null;
    records.set(item.id, item);
  }
  const seen = new Set<string>();
  function visit(key: string, depth: number): boolean {
    const r = records.get(key);
    if (!r || seen.has(key) || depth > 24) return false;
    seen.add(key);
    const children = r.component === "Card" ? [r.child] : r.component === "Column" ? r.children : [];
    return children.every((c) => visit(c, depth + 1));
  }
  return visit("root", 0) && seen.size === records.size ? records : null;
}

/** Each snapshot has its own renderer lifetime. Lines come from the admitted run or the exact selected node. */
export function evidenceSurface(title: string, status: string, paragraphs: readonly string[], surfaceId: string) {
  const components: RecordNode[] = [
    { id: "root", component: "Card", child: "body" },
    { id: "body", component: "Column", children: ["title", "status", "rule", ...paragraphs.map((_, i) => `p-${i}`)] },
    { id: "title", component: "Text", text: title, variant: "body" },
    { id: "status", component: "Text", text: status, variant: "caption" },
    { id: "rule", component: "Divider", axis: "horizontal" },
    ...paragraphs.map((text, i): RecordNode => ({ id: `p-${i}`, component: "Text", text, variant: "body" })),
  ];
  return { version: "1.0", createSurface: { surfaceId, catalogId, components } };
}
