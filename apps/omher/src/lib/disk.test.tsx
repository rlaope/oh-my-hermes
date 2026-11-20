import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { DiskChipView } from "../sidebar/DiskChip";
import { diskNote, diskWarn, gb, startDiskWatch, useDisk, type DiskState } from "./disk";
import { MockHost } from "../sessions/host";
import type { Note } from "./notify";

const chip = (d: DiskState) => renderToStaticMarkup(<DiskChipView d={d} onOpen={() => {}} />);

describe("disk chip", () => {
  it("shows while the disk is low or critical, with the free space", () => {
    const low = chip({ level: "low", free_bytes: 12.4e9, volume: "/" });
    expect(low).toContain('data-testid="disk-chip"');
    expect(low).toContain('data-level="low"');
    expect(low).toContain("12 GB free");
    expect(chip({ level: "critical", free_bytes: 4.5e9, volume: "/" })).toContain("4.5 GB free");
  });
  it("hides when the disk is fine", () => {
    expect(chip({ level: "ok", free_bytes: 80e9, volume: "/" })).toBe("");
  });
});

describe("disk note", () => {
  it("says how much is left and where", () => {
    expect(diskNote({ level: "low", free_bytes: 4.5e9, volume: "/" })).toMatchObject({
      title: "Disk space low: 4.5 GB left",
      body: "Free space on / before builds and agents start failing.",
      tag: "disk:low",
    });
    expect(diskNote({ level: "critical", free_bytes: 3e9, volume: "C:\\" }).title).toBe("Disk space critically low: 3.0 GB left");
    expect(gb(25.6e9)).toBe("26 GB");
  });
  it("warns below 20 GB unless Settings says otherwise", () => {
    expect(diskWarn()).toBe(20);
  });
});

describe("mock host disk watch", () => {
  it("follows the shell's rules: the event only when the level gets worse, better only past the margin", async () => {
    const g: Record<string, unknown> = { __omherDiskFree: 30e9 };
    const h = new MockHost(g as never);
    const heard: string[] = [];
    h.onDiskLevel((s) => heard.push(s.level));
    expect((await h.diskWatch(20)).level).toBe("ok");
    g.__omherDiskFree = 19e9;
    expect((await h.diskWatch(20)).level).toBe("low");
    expect((await h.diskWatch(20)).level).toBe("low");
    g.__omherDiskFree = 4e9;
    expect((await h.diskWatch(20)).level).toBe("critical");
    g.__omherDiskFree = 6e9;
    expect((await h.diskWatch(20)).level).toBe("critical");
    g.__omherDiskFree = 21e9;
    expect((await h.diskWatch(20)).level).toBe("low");
    g.__omherDiskFree = 22e9;
    expect((await h.diskWatch(20)).level).toBe("ok");
    expect((await h.diskWatch(0)).level).toBe("ok");
    expect(heard).toEqual(["low", "critical"]);
  });

  it("startDiskWatch sends one note per worse level and keeps the reading for the chip", async () => {
    const g: Record<string, unknown> = { __omherDiskFree: 4.5e9 };
    const h = new MockHost(g as never);
    const notes: Note[] = [];
    startDiskWatch(h, (n) => notes.push(n), 1e9);
    await new Promise((r) => setTimeout(r, 0));
    expect(notes.map((n) => n.title)).toEqual(["Disk space critically low: 4.5 GB left"]);
    const Shown = () => <DiskChipView d={useDisk()} onOpen={() => {}} />;
    expect(renderToStaticMarkup(<Shown />)).toContain('data-level="critical"');
    // the same level on the next minute's reading: no second note
    await h.diskWatch(20);
    expect(notes).toHaveLength(1);
  });
});
