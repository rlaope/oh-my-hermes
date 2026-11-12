// The Dock (macOS) or launcher (Linux desktops that show counts) count of asks waiting on the person: approvals and
// questions open in any bot's chat or SESSIONS chat, the same list as the Needs-you strip. Windows has no count, so
// the shell lays a small dot over the taskbar button instead (src-tauri/src/lib.rs `asks_badge`).
import { useEffect } from "react";
import { selectAsks, useStore } from "../state/store";
import { getHost } from "../sessions/host";

/** The number shown: every open ask, at most 99 (the Dock cuts longer labels). */
export const badgeCount = (asks: number) => Math.min(Math.max(0, asks), 99);

export function useAsksBadge(): void {
  const s = useStore();
  const n = badgeCount(selectAsks(s).length);
  useEffect(() => {
    void getHost()
      .badge(n)
      .catch(() => undefined);
  }, [n]);
}
