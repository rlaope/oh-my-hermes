/** Sidebar bot order. The sidebar shows the pinned bots first (in pin order), then the rest of the roster (in roster
 *  order). Moving a row keeps it in its own group: a pinned bot moves among the pinned ones, any other bot among the
 *  rest, so a drag never pins or unpins. */

/** The rows `bot` can move between, as [first, last] sidebar indices; null when it is not in the list. */
export function moveRange(order: readonly string[], pinned: readonly string[], bot: string): [number, number] | null {
  if (!order.includes(bot)) return null;
  const pins = order.filter((n) => pinned.includes(n)).length;
  return pinned.includes(bot) ? [0, pins - 1] : [pins, order.length - 1];
}

/** Put `members` back into `list` in the order `next`, each in one of the slots the members held; every other entry
 *  (a bot Hermes no longer lists) keeps its place. */
function refill(list: readonly string[], members: readonly string[], next: readonly string[]): string[] {
  let i = 0;
  return list.map((n) => (members.includes(n) ? next[i++] : n));
}

/** The pinned list and roster after moving `bot` to sidebar index `to` (clamped to its group), or null when nothing
 *  changes. `order` is the sidebar as shown (selectSidebarBots). */
export function moveInSidebar(
  order: readonly string[],
  pinned: readonly string[],
  roster: readonly string[],
  bot: string,
  to: number,
): { pinned: string[]; roster: string[] } | null {
  const range = moveRange(order, pinned, bot);
  if (!range) return null;
  const [lo, hi] = range;
  const group = order.slice(lo, hi + 1);
  const from = group.indexOf(bot);
  const at = Math.max(0, Math.min(group.length - 1, to - lo));
  if (at === from) return null;
  const next = group.filter((n) => n !== bot);
  next.splice(at, 0, bot);
  return pinned.includes(bot)
    ? { pinned: refill(pinned, group, next), roster: [...roster] }
    : { pinned: [...pinned], roster: refill(roster, group, next) };
}
