// remark plugin: each `obsidian://` link in markdown (the scheme in any case), bare in the text or written as a link
// (`[text](obsidian://…)`, `<obsidian://…>`, `[text][ref]` with `[ref]: obsidian://…`), becomes a
// `span[data-obsidian]`, which Markdown draws as a chip that names the note and opens nothing (rule 22: omher opens
// only web links and messenger threads). It never stays a link node, so the address never reaches an href or the url
// transform. Code (inline and fenced) is never text in mdast, and the text of an http(s) link is left alone.
// GFM reads its own literals before this runs, so a bare address's query can arrive split: `file=https://…`,
// `www.…` or `me@example.com` as links, `~x~` or `*x*` as strikethrough or emphasis. Where the source shows one
// unbroken address, those pieces are folded back into it (by their source offsets, or for the nodes GFM adds without
// offsets, by their text matching the source), so the chip names the whole address and none of it becomes a link of
// its own. A link the author wrote out (`[text](url)`) right after an address is not a GFM piece and stays a link,
// ending the address; emphasis or strikethrough written with no space after an address cannot be told from a split
// query and is folded, as a sent message's plain text reads the same word. The text after an address goes back
// through this loop, so a second address there is a chip too. Only the mdast shapes used here are typed.
import { findUrls } from "./linkKinds";

interface MdNode {
  type: string;
  value?: string;
  url?: string;
  identifier?: string;
  children?: MdNode[];
  data?: { hName?: string; hProperties?: Record<string, string> };
  position?: { start: { offset?: number }; end: { offset?: number } };
}

const SKIP = new Set(["link", "linkReference", "definition", "inlineCode", "code", "html"]);
const OBSIDIAN = /^obsidian:\/\//i;
const HAS_OBSIDIAN = /obsidian:\/\//i;
const WORD_END = /[\s<>"'`]/g;

const chip = (url: string, children?: MdNode[]): MdNode => ({
  type: "obsidianLink",
  children: children ?? [{ type: "text", value: url }],
  data: { hName: "span", hProperties: { dataObsidian: url } },
});

const span = (n: MdNode) => [n.position?.start.offset, n.position?.end.offset] as const;
/** A node's text as shown (a link's text, an emphasis's words). */
const plain = (n: MdNode): string => n.value ?? (n.children ?? []).map(plain).join("");

/** The `[ref]: obsidian://…` definitions, by their (already normalised) identifier. */
function obsidianDefinitions(node: MdNode, out = new Map<string, string>()): Map<string, string> {
  for (const child of node.children ?? []) {
    if (child.type === "definition" && child.identifier && child.url && OBSIDIAN.test(child.url.trim())) out.set(child.identifier, child.url.trim());
    else obsidianDefinitions(child, out);
  }
  return out;
}

export function remarkObsidianLinks() {
  let src = "";
  let defs = new Map<string, string>();
  const walk = (node: MdNode) => {
    if (!node.children || SKIP.has(node.type)) return;
    const kids = node.children;
    const next: MdNode[] = [];
    for (let i = 0; i < kids.length; i++) {
      const child = kids[i];
      if (child.type === "link" && child.url && OBSIDIAN.test(child.url.trim())) {
        next.push(chip(child.url.trim(), child.children ?? []));
        continue;
      }
      const ref = child.type === "linkReference" && child.identifier ? defs.get(child.identifier) : undefined;
      if (ref) {
        next.push(chip(ref, child.children ?? []));
        continue;
      }
      if (child.type !== "text" || !child.value || !HAS_OBSIDIAN.test(child.value)) {
        walk(child);
        next.push(child);
        continue;
      }
      const text = child.value;
      // where the node sits in the source: its own offsets, else (a node GFM split off) its text found in the parent's
      const s = span(child)[0] ?? (src ? src.indexOf(text, node.position?.start.offset ?? 0) : -1);
      const e = s + text.length;
      // the node is the source as written (no escapes or entities), so its offsets map one to one
      const literal = s >= 0 && src.slice(s, e) === text;
      let at = 0;
      let after: MdNode | null = null;
      for (const f of findUrls(text)) {
        if (!OBSIDIAN.test(f.url)) continue;
        if (f.start > at) next.push({ type: "text", value: text.slice(at, f.start) });
        at = f.end;
        if (!literal || f.end !== text.length) {
          next.push(chip(f.url));
          continue;
        }
        // the address may go on past this node: its end comes from the source, then the siblings that lie inside it
        const start = s + f.start;
        WORD_END.lastIndex = start;
        const stop = WORD_END.exec(src);
        const word = src.slice(start, stop ? stop.index : src.length);
        const end = start + (findUrls(word)[0]?.url.length ?? f.url.length);
        let reach = e;
        while (i + 1 < kids.length && reach < end) {
          const k = kids[i + 1];
          const [ks, ke] = span(k);
          const shown = plain(k);
          let to: number;
          // a link is a GFM piece only when its source is its text (a literal), not an author's `[text](url)`
          if (ks !== undefined && ke !== undefined) to = ks === reach && (k.type !== "link" || src.slice(ks, ke) === shown) ? ke : -1;
          else to = (k.type === "text" || k.type === "link") && shown && src.startsWith(shown, reach) ? reach + shown.length : -1;
          if (to < 0) break; // not the next piece of the same source
          if (to <= end) {
            reach = to;
            i += 1;
            continue;
          }
          // a text node that starts inside the address and runs past it: its part after the address goes back
          // through the loop, with its own source offsets, so another address in it is found
          if (k.type === "text" && k.value !== undefined && src.slice(reach, to) === k.value) {
            after = { type: "text", value: k.value.slice(end - reach), position: { start: { offset: end }, end: { offset: to } } };
            reach = end;
            i += 1;
          }
          break;
        }
        const url = findUrls(src.slice(start, reach))[0]?.url ?? f.url;
        next.push(chip(url));
        if (start + url.length < reach) next.push({ type: "text", value: src.slice(start + url.length, reach) });
      }
      if (at < text.length) next.push({ type: "text", value: text.slice(at) });
      if (after) {
        kids[i] = after;
        i -= 1;
      }
    }
    node.children = next;
  };
  return (tree: MdNode, file?: { value?: unknown }) => {
    src = typeof file?.value === "string" ? file.value : "";
    defs = obsidianDefinitions(tree);
    walk(tree);
  };
}
