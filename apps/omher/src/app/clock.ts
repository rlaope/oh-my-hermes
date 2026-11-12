// One clock for the live times on screen: every component that counts a running time reads the same `now`, ticked
// four times a second by one timer, so two times of the same moment never stand a tick apart (the activity line's
// elapsed and a subagent row's time read the same instant).
import { useEffect, useState } from "react";

let now = Date.now();
const subs = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | undefined;

function tick() {
  now = Date.now();
  subs.forEach((f) => f());
}

/** The shared `now` (ms) while `on`, re-rendering on each tick; `Date.now()` when off. */
export function useClock(on: boolean): number {
  const [, set] = useState(0);
  useEffect(() => {
    if (!on) return;
    const f = () => set((n) => n + 1);
    if (!subs.size) {
      now = Date.now();
      timer = setInterval(tick, 250);
    }
    subs.add(f);
    return () => {
      subs.delete(f);
      if (!subs.size && timer !== undefined) {
        clearInterval(timer);
        timer = undefined;
      }
    };
  }, [on]);
  return on && timer !== undefined ? now : Date.now();
}
