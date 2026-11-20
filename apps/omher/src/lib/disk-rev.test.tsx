// The shell numbers its readings (`rev`): the event and a command reply travel on different channels, so either can
// arrive late. Shapes from the third independent verify of #3010. Own module: startDiskWatch runs once per page.
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { setDiskWarn, startDiskWatch, useDisk, type DiskHost, type DiskLevel, type DiskState } from "./disk";
import type { Note } from "./notify";

const st = (level: DiskLevel, alerts: number, rev: number): DiskState => ({ level, free_bytes: level === "ok" ? 30e9 : 10e9, volume: "/", alerts, rev });

describe("disk readings by rev", () => {
  it("drops an event older than the reply shown, and notes where the disk is now when steps arrive out of order", async () => {
    let event: (s: DiskState) => void = () => {};
    const replies: ((s: DiskState) => void)[] = [];
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
    const reply = async (s: DiskState) => {
      replies.shift()!(s);
      await new Promise((r) => setTimeout(r, 0));
    };

    // reading 1: low (reply), its event arrives after: one note
    await reply(st("low", 1, 1));
    event(st("low", 1, 1));
    expect(notes.map((n) => n.tag)).toEqual(["disk:low"]);

    // the warning turned Off: reading 2 answers ok; reading 1's event delivered late again: chip stays ok, no note
    setDiskWarn(0);
    await reply(st("ok", 1, 2));
    event(st("low", 1, 1));
    expect(level()).toContain("ok");
    expect(notes).toHaveLength(1);

    // back On while still low: reading 3 is a new worse step: one note
    setDiskWarn(20);
    await reply(st("low", 2, 3));
    expect(notes.map((n) => n.tag)).toEqual(["disk:low", "disk:low"]);

    // two worse steps the page hears out of order: critical (reading 5) first, then low (reading 4) late.
    // One note, for where the disk is now; the low it already passed is not announced afterwards.
    event(st("critical", 4, 5));
    event(st("low", 3, 4));
    expect(notes.map((n) => n.tag)).toEqual(["disk:low", "disk:low", "disk:critical"]);
    expect(level()).toContain("critical");
  });
});
