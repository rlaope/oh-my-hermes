import { memo, useMemo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MentionLink, useMentions } from "./Mention";
import { remarkMentions } from "./remarkMentions";

const plain = [remarkGfm];

const HANGUL = /[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]/;

/** Plain text inside an element, for deciding how to emphasise it. */
function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node) return textOf((node as { props: { children?: ReactNode } }).props.children);
  return "";
}

/** Bot markdown. Inside a MentionContext (the app), `@name` of a known bot opens that bot's chat. */
export const Markdown = memo(function Markdown({ text }: { text: string }) {
  const resolve = useMentions()?.resolve;
  const plugins = useMemo(() => (resolve ? [remarkGfm, [remarkMentions, { resolve }] as const] : plain), [resolve]);
  return (
    <ReactMarkdown
      remarkPlugins={plugins as typeof plain}
      components={{
        a: ({ node: _n, ...p }) => <a {...p} target="_blank" rel="noreferrer" />,
        span: ({ node: _n, ...p }) => {
          const bot = (p as Record<string, unknown>)["data-mention"];
          return typeof bot === "string" ? <MentionLink bot={bot}>{p.children}</MentionLink> : <span {...p} />;
        },
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
