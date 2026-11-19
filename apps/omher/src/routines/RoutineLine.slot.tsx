// The routine line: one gray line in the timeline per `routine.ran`, e.g. "⏱ Routine · Repo watch · done 09:00".
// Click opens the routine's last status underneath. Read-only: nothing here can start or change a routine.
import { useState } from "react";
import "./routines.css";
import type { SlotProps } from "../features";
import { useStore } from "../state/store";
import { hhmm } from "../app/time";
import { ChevronDown, ChevronRight } from "../ui";
import { t } from "../i18n";
import { isFailure, statusText } from "../elsewhere/format";

export { isFailure, statusWord } from "../elsewhere/format";

export const slot = "routineLine";

export default function RoutineLine({ bot, item }: SlotProps["routineLine"]) {
  const s = useStore();
  const [open, setOpen] = useState(false);
  // The freshest last_status the bridge knows for this routine, else what the event carried.
  const known = s.routines[bot]?.find((r) => r.id === item.routine_id)?.last_status;
  const last = (known ?? item.status ?? "").toString();
  const word = statusText(item.status);
  const at = hhmm(new Date(item.ts * 1000));
  // failed runs folded into this line: "×12 · 03:56–09:37"
  const times = (item.count ?? 1) > 1 && item.since ? t("rt.times", { n: item.count!, from: hhmm(new Date(item.since * 1000)), to: at }) : at;

  return (
    <div className="routine" data-testid="routine-line" data-open={open}>
      <button
        type="button"
        className="routine-row"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        title={open ? t("rt.hide") : t("rt.show")}
      >
        <span className="routine-ic" aria-hidden>
          ⏱
        </span>
        <span className="routine-t">
          {t("rt.routine")} · <span className="routine-name">{item.name}</span> ·{" "}
          <span className={isFailure(item.status) ? "routine-bad" : undefined}>{word}</span>{" "}
          <span data-testid="routine-when">{times}</span>
        </span>
        <span className="routine-chev" aria-hidden>
          {open ? <ChevronDown /> : <ChevronRight />}
        </span>
      </button>
      {open && (
        <div className="routine-detail" data-testid="routine-detail">
          <span className="routine-k">{t("rt.last")}</span>
          <span className={isFailure(last) ? "routine-bad" : undefined}>{last ? statusText(last) : t("rt.unknown")}</span>
        </div>
      )}
    </div>
  );
}
