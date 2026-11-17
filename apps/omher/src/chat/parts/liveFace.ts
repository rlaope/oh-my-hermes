import { answerSoFar, turnHasActivity, type TimelineItem, type Turn } from "../../state/store";

/** Which row of a running turn carries the bot's ringed face: the typing bubble until the turn has something to
 *  show, then the live activity line, then the answer being written (once a whole line of it shows). One face in the live run at every moment, in the
 *  same column, so the face never blinks out when the first status ("OMH — recalled 2 memories") arrives. While an
 *  ask card waits on the person the line keeps it (it says "Waiting for approval"). A bot bubble that landed after
 *  the line (an answer mid-turn, an away session) carries its own face, so the line then has none. */
export function liveFaceRow(items: TimelineItem[], turn: Turn | null | undefined, typing: boolean): "typing" | "activity" | "streaming" | null {
  if (!turn) return null;
  if (answerSoFar(turn)) return "streaming";
  if (typing) return "typing";
  if (!turnHasActivity(turn)) return null;
  const at = items.findIndex((i) => i.kind === "activity" && i.id === turn.id);
  if (at < 0) return null;
  for (let k = at + 1; k < items.length; k++) if (items[k].kind === "assistant") return null;
  return "activity";
}
