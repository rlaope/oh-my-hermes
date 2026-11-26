import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { Bot } from "../lib/protocol";
import { RestartAction } from "./RestartLine";

vi.mock("../state/store", () => ({ getStore: () => ({ actions: { onBridgeEvent: () => () => {} } }) }));

const bot = (over: Partial<Bot> = {}): Bot => ({
  name: "kami", display_name: "Kami", is_default: false, model: "m", provider: "p", description: "", status: "offline", running: false, ...over,
});

describe("Restart / Start in place", () => {
  it("is offered for a bot on this computer", () => {
    expect(renderToStaticMarkup(<RestartAction bot={bot()} start testId="chat-start" />)).toContain('data-testid="chat-start"');
  });
  it("is not offered for a bot on another computer: the bridge refuses bots.restart for it", () => {
    const host = { label: "Mac mini", host: "demo@host.example" } as unknown as Bot["host"];
    expect(renderToStaticMarkup(<RestartAction bot={bot({ host })} start testId="chat-start" />)).toBe("");
  });
});
