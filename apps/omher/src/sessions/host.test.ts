// TauriHost.ack: what the terminal has drawn reaches the shell as one `session_ack` per session per task, and a
// call that fails loses no credit (its bytes ride on the next acknowledgement). The shell's command bridge is stood
// in for by overriding `core()`; nothing here needs a Tauri window.
import { describe, expect, it } from "vitest";
import { TauriHost } from "./host";

type Sent = { id: number; bytes: number };

class Host extends TauriHost {
  sent: Sent[] = [];
  /** how many of the next `session_ack` calls fail */
  fail = 0;
  /** the bridge itself cannot be loaded */
  noBridge = false;
  protected override async core() {
    if (this.noBridge) throw new Error("no bridge");
    const invoke = async (cmd: string, args: unknown) => {
      expect(cmd).toBe("session_ack");
      if (this.fail > 0) {
        this.fail -= 1;
        throw new Error("the call did not go through");
      }
      this.sent.push(args as Sent);
    };
    return { invoke, Channel: class {} } as unknown as Awaited<ReturnType<TauriHost["core"]>>;
  }
}

/** The end of this task and of everything it queued. */
const task = () => new Promise<void>((r) => setTimeout(r, 0));
const total = (sent: Sent[], id: number) => sent.filter((s) => s.id === id).reduce((n, s) => n + s.bytes, 0);

describe("TauriHost.ack", () => {
  it("sends one acknowledgement for everything one session drew in the same task", async () => {
    const h = new Host();
    for (const n of [100, 20, 3]) h.ack(7, n);
    expect(h.sent).toEqual([]); // not before the task ends
    await task();
    expect(h.sent).toEqual([{ id: 7, bytes: 123 }]);
  });

  it("sends one per session, and a later task sends again", async () => {
    const h = new Host();
    h.ack(1, 10);
    h.ack(2, 5);
    h.ack(1, 1);
    await task();
    expect(h.sent).toEqual([
      { id: 1, bytes: 11 },
      { id: 2, bytes: 5 },
    ]);
    h.ack(2, 64);
    await task();
    h.ack(2, 64);
    await task();
    expect(h.sent.slice(2)).toEqual([
      { id: 2, bytes: 64 },
      { id: 2, bytes: 64 },
    ]);
  });

  it("carries the bytes of a failed call into the next acknowledgement instead of dropping them", async () => {
    const h = new Host();
    h.fail = 1;
    h.ack(3, 1000);
    await task();
    expect(h.sent).toEqual([]); // the call failed
    h.ack(3, 24);
    await task();
    expect(h.sent).toEqual([{ id: 3, bytes: 1024 }]);
  });

  it("another session's acknowledgement takes the carried bytes along, and a call that went through is not sent twice", async () => {
    const h = new Host();
    h.fail = 1; // the first call of the task (session 1) fails, the second (session 2) goes through
    h.ack(1, 500);
    h.ack(2, 70);
    await task();
    expect(h.sent).toEqual([{ id: 2, bytes: 70 }]);
    h.ack(2, 30);
    await task();
    expect(total(h.sent, 1)).toBe(500);
    expect(total(h.sent, 2)).toBe(100);
    expect(h.sent).toHaveLength(3);
  });

  it("keeps everything when the bridge cannot be loaded, and sends it once it can", async () => {
    const h = new Host();
    h.noBridge = true;
    h.ack(4, 10);
    h.ack(5, 20);
    await task();
    h.ack(4, 1);
    await task();
    expect(h.sent).toEqual([]);
    h.noBridge = false;
    h.ack(5, 2);
    await task();
    expect(total(h.sent, 4)).toBe(11);
    expect(total(h.sent, 5)).toBe(22);
  });

  it("loses nothing over many tasks with calls failing now and then", async () => {
    const h = new Host();
    const acked = new Map<number, number>();
    for (let i = 0; i < 300; i++) {
      const id = 1 + (i % 3);
      const n = 1 + ((i * 7919) % 65536);
      if (i % 11 === 0) h.fail += 1;
      h.ack(id, n);
      acked.set(id, (acked.get(id) ?? 0) + n);
      if (i % 4 === 3) await task();
    }
    h.fail = 0;
    for (const id of acked.keys()) h.ack(id, 0);
    await task();
    for (const [id, n] of acked) expect(total(h.sent, id), `session ${id}`).toBe(n);
  });
});
