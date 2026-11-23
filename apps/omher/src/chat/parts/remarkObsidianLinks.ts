// remark plugin: each `obsidian://` link in markdown, bare in the text or written as a link (`[text](obsidian://…)`,
// `<obsidian://…>`), becomes a `span[data-obsidian=<url>]`, which Markdown draws as a chip that names the note and
// opens nothing (rule 22: omher opens only web links and messenger threads). It never stays a link node, so the
// address never reaches an href or the url transform. Code (inline and fenced) is never text in mdast, and the text
// of an http(s) link is left alone. Only the mdast shapes used here are typed.
import { findUrls } from "./linkKinds";

interface MdNode {
  type: string;
  value?: string;
  url?: string;
  children?: MdNode[];
  data?: { hName?: string; hProperties?: Record<string, string> };
}

const SKIP = new Set(["link", "linkReference", "definition", "inlineCode", "code", "html"]);
const OBSIDIAN = /^obsidian:\/\//i;

const chip = (url: string, children: MdNode[]): MdNode => ({
  type: "obsidianLink",
  children,
  data: { hName: "span", hProperties: { dataObsidian: url } },
});

export function remarkObsidianLinks() {
  const walk = (node: MdNode) => {
    if (!node.children || SKIP.has(node.type)) return;
    const next: MdNode[] = [];
    for (const child of node.children) {
      if (child.type === "link" && child.url && OBSIDIAN.test(child.url.trim())) {
        next.push(chip(child.url.trim(), child.children ?? []));
        continue;
      }
      if (child.type !== "text" || !child.value?.includes("obsidian://")) {
        walk(child);
        next.push(child);
        continue;
      }
      const text = child.value;
      let at = 0;
      for (const f of findUrls(text)) {
        if (!OBSIDIAN.test(f.url)) continue;
        if (f.start > at) next.push({ type: "text", value: text.slice(at, f.start) });
        next.push(chip(f.url, [{ type: "text", value: f.url }]));
        at = f.end;
      }
      if (at < text.length) next.push({ type: "text", value: text.slice(at) });
    }
    node.children = next;
  };
  return (tree: MdNode) => walk(tree);
}
