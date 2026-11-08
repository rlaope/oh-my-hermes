import { useEffect, useState } from "react";

/** Current time in ms; re-renders every `ms` while `on` (for "working · 4m" labels). Read at render time,
 *  so every view of the same session shows the same value. */
export function useNow(on: boolean, ms = 10_000): number {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!on) return;
    const h = setInterval(() => tick((n) => n + 1), ms);
    return () => clearInterval(h);
  }, [on, ms]);
  return Date.now();
}
