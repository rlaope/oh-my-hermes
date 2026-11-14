// A bot on another computer is listed as `<peer>:<name>` (the bridge's multiplexer, BOUNDARY rule 31) and carries a
// `host` field. Those names pass every place a bot name goes; this file holds the few checks that need to tell them
// apart from a bot on this computer.
import type { Bot } from "../lib/protocol";

/** True for a bot that lives on another computer (a namespaced `<peer>:<name>`). */
export const isRemote = (bot: Pick<Bot, "name"> | string | null | undefined): boolean =>
  !!bot && (typeof bot === "string" ? bot : bot.name).includes(":");

/** The bot a folder chat (SESSIONS > oh-my-hermes) may run on: `pick` when it is on this computer, else the first
 *  bot that is. A folder chat runs in a folder on this computer. */
export function localBot(pick: string | null | undefined, bots: readonly Pick<Bot, "name">[]): string | undefined {
  if (pick && !isRemote(pick)) return pick;
  return bots.find((b) => !isRemote(b))?.name;
}
