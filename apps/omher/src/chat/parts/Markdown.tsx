import { memo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const plugins = [remarkGfm];

const HANGUL = /[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]/;

/** Plain text inside an element, for deciding how to emphasise it. */
function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node) return textOf((node as { props: { children?: ReactNode } }).props.children);
  return "";
}

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={plugins}
      components={{
        a: ({ node: _n, ...p }) => <a {...p} target="_blank" rel="noreferrer" />,
        // Hangul has no italic face; a synthetic slant reads as broken, so emphasis there is weight instead
        em: ({ node: _n, children, ...p }) => (
          <em {...p} className={HANGUL.test(textOf(children)) ? "hangul" : undefined}>
            {children}
          </em>
        ),
      }}
    >
      {text}
    </ReactMarkdown>
  );
});
