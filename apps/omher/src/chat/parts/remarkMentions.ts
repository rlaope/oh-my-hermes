// remark plugin: each `@name` in markdown text that names a known bot becomes a `span[data-mention=<bot>]`, which
// Markdown draws as a mention. Code (inline and fenced) is never text in mdast, and links and link references
// are skipped, so a mention never lands inside either. Only the mdast shapes used here are typed.
import { findMentions } from "./mentions";

interface MdNode {
  type: string;
  value?: string;
  children?: MdNode[];
  data?: { hName?: string; hProperties?: Record<string, string> };
}

const SKIP = new Set(["link", "linkReference", "definition", "inlineCode", "code", "html"]);

export function remarkMentions(options: { resolve: (name: string) => string | null }) {
  const { resolve } = options;
  const walk = (node: MdNode) => {
    if (!node.children || SKIP.has(node.type)) return;
    const next: MdNode[] = [];
    for (const child of node.children) {
      if (child.type !== "text" || !child.value?.includes("@")) {
        walk(child);
        next.push(child);
        continue;
      }
      const text = child.value;
      const found = findMentions(text, resolve);
      if (!found.length) {
        next.push(child);
        continue;
      }
      let at = 0;
      for (const m of found) {
        if (m.start > at) next.push({ type: "text", value: text.slice(at, m.start) });
        const label = text.slice(m.start, m.end);
        next.push({
          type: "mention",
          children: [{ type: "text", value: label }],
          data: { hName: "span", hProperties: { dataMention: m.bot } },
        });
        at = m.end;
      }
      if (at < text.length) next.push({ type: "text", value: text.slice(at) });
    }
    node.children = next;
  };
  return (tree: MdNode) => walk(tree);
}
