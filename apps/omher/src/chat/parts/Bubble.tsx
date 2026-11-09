import type { MessageItem } from "../../state/store";
import { Markdown } from "./Markdown";

/** Messenger bubble, filled on both sides. Bot text renders markdown; user text stays plain. */
export function Bubble({ item, streaming }: { item: Pick<MessageItem, "kind" | "text" | "error">; streaming?: boolean }) {
  if (item.kind === "user") {
    return (
      <div className="msg u" data-testid="bubble-user">
        <div className="b">{item.text}</div>
        {item.error && <div className="msg-err">Not sent · {item.error}</div>}
      </div>
    );
  }
  return (
    <div className={`msg a${streaming ? " streaming" : ""}`} data-testid={streaming ? "bubble-streaming" : "bubble-bot"}>
      <div className="b md">
        <Markdown text={item.text} />
      </div>
    </div>
  );
}
