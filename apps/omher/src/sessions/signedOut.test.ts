// The shell says an Agent Client Protocol agent is not signed in with the command between backticks
// (`signed_out` in acp_chat.rs). Wherever that sentence reaches a person as plain text (a failed turn's line, the
// Ended line, the sidebar row's tooltip, a notification) it is said in their language with no backtick.
import { readFileSync } from "node:fs";
import { expect, test } from "vitest";
import { createSessions, signedOutSaid } from "./sessions";
import { createStore, type BridgeLike } from "../state/store";
import { DICT, LANGS } from "../i18n";
import type { ChatEvent, ChatInput, SessionHost } from "./host";

const SHELL = "Kilo Code is not signed in. Run `kilo auth login` in a terminal and sign in.";
const SAID = "Kilo Code is not signed in. Run kilo auth login in a terminal and sign in.";

test("the shell's sentence is the one this file reads", () => {
  const rs = readFileSync(new URL("../../src-tauri/src/acp_chat.rs", import.meta.url), "utf8");
  expect(rs).toContain('format!("{} is not signed in. Run `{}` in a terminal and sign in.", self.agent.label, self.agent.login)');
});

test("the not-signed-in sentence is said without backticks; other text is left alone", () => {
  expect(signedOutSaid(SHELL)).toBe(SAID);
  expect(signedOutSaid(`  ${SHELL}\n`)).toBe(SAID);
  expect(signedOutSaid("Run `make test` first")).toBe("Run `make test` first");
  for (const l of LANGS) expect(DICT[l]["ss.signedOut"], l).not.toContain("`");
});

test("a turn that fails because the agent is not signed in says so without backticks", async () => {
  (globalThis as { localStorage?: unknown }).localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  const bridge: BridgeLike = { connect: async () => undefined, onAny: () => () => {}, onStatus: () => () => {}, request: (async () => ({})) as BridgeLike["request"] };
  let sink: (e: ChatEvent) => void = () => {};
  const host = {
    kind: "mock",
    reset: async () => {},
    agents: async () => [{ id: "kilo", label: "Kilo Code", mode: "chat", path: "/bin/kilo" }],
    home: async () => "/w",
    pickFolder: async () => null,
    chatStart: async (_a: string, _c: string, on: (e: ChatEvent) => void) => {
      sink = on;
      on({ event: "session.info", agent_session: "ses_1", model: "Auto Free" });
      return 1;
    },
    // Kilo Code answers a prompt to a model that needs its account: the shell ends the turn with its sentence
    chatInput: async (_id: number, i: ChatInput) => {
      if (i.kind !== "send") return;
      sink({ event: "turn.start" });
      sink({ event: "turn.end", outcome: "error", error: SHELL, signed_out: true, login: "kilo auth login" });
    },
    chatClose: async () => {},
  } as unknown as SessionHost;
  const store = createStore(bridge);
  const ss = createSessions(host, () => store);
  await ss.loadAgents();
  const id = ss.draft("kilo");
  ss.setDraft(id, { cwd: "/w/proj" });
  await ss.start(id, "hi");
  const last = store.getState().chats[ss.chatKey(id)!]!.lastTurn!;
  expect(last.outcome).toBe("error");
  expect(last.error).toBe(SAID);
});
