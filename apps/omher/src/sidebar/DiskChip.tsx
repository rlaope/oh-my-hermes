// The sidebar footer's disk chip: shown while the home folder's volume is low on space (src/lib/disk.ts), its free
// space as a number; a click opens Settings › General, where the warning is set. It starts the page's disk watch.
import { useEffect } from "react";
import { t } from "../i18n";
import { showNote } from "../lib/notify";
import { gb, startDiskWatch, useDisk, type DiskState } from "../lib/disk";
import { notifyEnabled, useStore } from "../state/store";
import { getHost } from "../sessions/host";

/** The chip for reading `d`, or nothing while the disk is fine. */
export function DiskChipView({ d, onOpen }: { d: DiskState; onOpen: () => void }) {
  if (d.level === "ok") return null;
  return (
    <button
      type="button"
      className={`disk-chip ${d.level}`}
      title={t("disk.chipTitle", { volume: d.volume || "/" })}
      onClick={onOpen}
      data-testid="disk-chip"
      data-level={d.level}
    >
      <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
        <rect x="2" y="3" width="12" height="10" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M5 10h3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="11" cy="10" r="1" fill="currentColor" />
      </svg>
      <span>{t("disk.chip", { free: gb(d.free_bytes) })}</span>
    </button>
  );
}

export function DiskChip() {
  const s = useStore();
  const d = useDisk();
  useEffect(() => {
    startDiskWatch(getHost(), (n) => {
      if (notifyEnabled()) void showNote(n, () => s.openSettings("general"), true);
    });
  }, []);
  return <DiskChipView d={d} onOpen={() => s.openSettings("general")} />;
}
