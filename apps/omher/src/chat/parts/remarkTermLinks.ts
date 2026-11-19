// remark plugin: each `omher://terminal/<id>` in markdown text becomes a link node, so Markdown draws it as an omher
// chip (GFM only autolinks http(s) and www). Code (inline and fenced) is never text in mdast, and existing links are
// skipped. `keepTermLinks` is the url transform that lets a terminal link through (react-markdown's default drops
// any scheme but http(s), mailto, irc and xmpp); every other URL goes through the default unchanged.
import { defaultUrlTransform } from "react-markdown";
import { findTermLinks, parseTermLink } from "../../sessions/termLink";

interface MdNode {
  type: string;
  value?: string;
  url?: string;
  children?: MdNode[];
}

const SKIP = new Set(["link", "linkReference", "definition", "inlineCode", "code", "html"]);

export function remarkTermLinks() {
  const walk = (node: MdNode) => {
    if (!node.children || SKIP.has(node.type)) return;
    const next: MdNode[] = [];
    for (const child of node.children) {
      if (child.type !== "text" || !child.value?.includes("omher://")) {
        walk(child);
        next.push(child);
        continue;
      }
      const text = child.value;
      const found = findTermLinks(text);
      if (!found.length) {
        next.push(child);
        continue;
      }
      let at = 0;
      for (const f of found) {
        if (f.start > at) next.push({ type: "text", value: text.slice(at, f.start) });
        next.push({ type: "link", url: f.url, children: [{ type: "text", value: f.url }] });
        at = f.end;
      }
      if (at < text.length) next.push({ type: "text", value: text.slice(at) });
    }
    node.children = next;
  };
  return (tree: MdNode) => walk(tree);
}

export function keepTermLinks(url: string): string {
  return parseTermLink(url) ? url.trim() : defaultUrlTransform(url);
}
