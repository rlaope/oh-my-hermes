// The shell's startup `disk-level` event can fire before the page's async listener is registered, and the shell sends
// it only once. The first reading must still raise the one note (its own module: startDiskWatch runs once per page).
import { describe, expect, it } from "vitest";
import { startDiskWatch, type DiskHost, type DiskState } from "./disk";
import type { Note } from "./notify";

describe("disk startup race", () => {
  it("notes once when the startup event is lost and the first reading is already low, then once per worse level", async () => {
    let listener: ((s: DiskState) => void) | undefined;
    let reading: DiskState = { level: "low", free_bytes: 19e9, volume: "/" };
    const host: DiskHost = {
      onDiskLevel(fn) {
        setTimeout(() => (listener = fn), 10); // registered late, like Tauri's async listen
        return () => {};
      },
      async diskWatch() {
        listener?.(reading); // the shell's one startup event: nobody is listening yet
        return reading;
      },
    };
    const notes: Note[] = [];
    startDiskWatch(host, (n) => notes.push(n), 1e9);
    await new Promise((r) => setTimeout(r, 30));
    expect(notes.map((n) => n.tag)).toEqual(["disk:low"]);

    // the same level from the event as well: still one
    listener?.(reading);
    expect(notes).toHaveLength(1);

    // worse: one more, whichever source says it first, not twice
    reading = { level: "critical", free_bytes: 4e9, volume: "/" };
    listener?.(reading);
    await host.diskWatch(20);
    expect(notes.map((n) => n.tag)).toEqual(["disk:low", "disk:critical"]);

    // fine again, then low again: a new note
    listener?.({ level: "ok", free_bytes: 30e9, volume: "/" });
    listener?.({ level: "low", free_bytes: 18e9, volume: "/" });
    expect(notes.map((n) => n.tag)).toEqual(["disk:low", "disk:critical", "disk:low"]);
  });
});
