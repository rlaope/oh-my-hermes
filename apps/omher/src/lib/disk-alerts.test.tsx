// Disk notes under the shell's worse-step count (src-tauri/src/disk.rs `Watch::alerts`), in its own module because
// startDiskWatch runs once per page. Shapes from the independent verify of #3010: a recovery the page never polled
// followed by a new drop to the same level, and a slow reply that lands after the warning was turned Off.
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { setDiskWarn, startDiskWatch, useDisk, type DiskHost, type DiskState } from "./disk";
import type { Note } from "./notify";

const crit = (alerts: number): DiskState => ({ level: "critical", free_bytes: 4e9, volume: "/", alerts });
const low = (alerts: number): DiskState => ({ level: "low", free_bytes: 10e9, volume: "/", alerts });
const ok = (alerts: number): DiskState => ({ level: "ok", free_bytes: 30e9, volume: "/", alerts });

describe("disk alerts count", () => {
  it("notes a drop after an unpolled recovery, ignores a slow reply after Off, and never notes a step twice", async () => {
    let event: (s: DiskState) => void = () => {};
    let replies: ((s: DiskState) => void)[] = [];
    const host: DiskHost = {
      onDiskLevel(fn) {
        event = fn;
        return () => {};
      },
      diskWatch: () => new Promise<DiskState>((r) => replies.push(r)),
    };
    const notes: Note[] = [];
    startDiskWatch(host, (n) => notes.push(n), 1e9);
    const Level = () => <span>{useDisk().level}</span>;
    const level = () => renderToStaticMarkup(<Level />);
    const reply = async (s: DiskState, i = 0) => {
      replies.splice(i, 1)[0](s);
      await new Promise((r) => setTimeout(r, 0));
    };

    // startup: critical, from both the event and the first reply: one note
    event(crit(1));
    await reply(crit(1));
    expect(notes.map((n) => n.tag)).toEqual(["disk:critical"]);

    // the shell recovers to low silently (no event, no poll), then drops to critical again: a new note
    event(crit(2));
    expect(notes.map((n) => n.tag)).toEqual(["disk:critical", "disk:critical"]);

    // a reply asked before that drop arrives late: it does not move the chip back or note anything
    setDiskWarn(20);
    await reply(low(1));
    expect(level()).toContain("critical");
    expect(notes).toHaveLength(2);

    // two asks in flight; the warning turned Off answers ok first; the older low reply lands after it: ignored
    setDiskWarn(20);
    setDiskWarn(0);
    await reply(ok(2), 1);
    expect(level()).toContain("ok");
    await reply(low(2), 0);
    expect(level()).toContain("ok");
    expect(notes).toHaveLength(2);
    replies = [];
  });
});
