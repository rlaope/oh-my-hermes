// The sidebar footer's CPU chip: shown while another app keeps a CPU core busy (src/lib/cpu.ts), the hottest app and
// its usage; a click opens Settings › General, where the warning is turned off. It starts the page's CPU watch.
import { useEffect } from "react";
import { t } from "../i18n";
import { showNote } from "../lib/notify";
import { startCpuWatch, useCpuHogs, type CpuHog } from "../lib/cpu";
import { notifyEnabled, useStore } from "../state/store";
import { getHost } from "../sessions/host";

/** The chip for hogs `hogs` (hottest first), or nothing while there is none. */
export function CpuChipView({ hogs, onOpen }: { hogs: CpuHog[]; onOpen: () => void }) {
  if (!hogs.length) return null;
  const top = hogs[0];
  return (
    <button
      type="button"
      className="disk-chip cpu-chip"
      title={t("cpu.chipTitle", { name: top.name, pct: top.pct })}
      onClick={onOpen}
      data-testid="cpu-chip"
    >
      <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
        <rect x="4" y="4" width="8" height="8" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M6 1.5v2M10 1.5v2M6 12.5v2M10 12.5v2M1.5 6h2M1.5 10h2M12.5 6h2M12.5 10h2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      </svg>
      <span>{t(hogs.length > 1 ? "cpu.chipMore" : "cpu.chip", { name: top.name, pct: top.pct, n: hogs.length - 1 })}</span>
    </button>
  );
}

export function CpuChip() {
  const s = useStore();
  const hogs = useCpuHogs();
  useEffect(() => {
    startCpuWatch(getHost(), (n) => {
      if (notifyEnabled()) void showNote(n, () => s.openSettings("general"), true);
    });
  }, []);
  return <CpuChipView hogs={hogs} onOpen={() => s.openSettings("general")} />;
}
