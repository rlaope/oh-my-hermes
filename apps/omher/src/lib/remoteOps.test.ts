// Rule 46's page choke point: every op the page can send passes `BridgeClient.request`, which asks remoteOps.ts first.
// Each audited op goes through a real client over a stand-in socket: on a server the refused ones never reach the
// socket (and the allowed ones do), in local mode every one is sent as before.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { BridgeClient } from "./bridge";
import { noteServerMode } from "../app/remote";
import { REMOTE_OPS, remoteRefusal, type OpRule, type PageOp } from "./remoteOps";

class FakeSocket {
  static last: FakeSocket | null = null;
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.last = this;
    setTimeout(() => {
      this.readyState = 1;
      this.onopen?.();
    }, 0);
  }
  send(data: string) {
    this.sent.push(data);
    const { id } = JSON.parse(data) as { id: string };
    setTimeout(() => this.onmessage?.({ data: JSON.stringify({ id, ok: true, result: {} }) }), 0);
  }
  close() {
    this.readyState = 3;
  }
}

/** What each op is sent with in this test: every field the audit names as carrying this computer is filled. */
const LOCAL = { cwd: "/fixture/this-computer/private", data: "data:image/png;base64,AAAA", data_base64: "QUFBQQ==", path: "/srv/listed", url: "ws://127.0.0.1:1/?token=t", host: "me@here" };
/** An op that may carry this computer is sent with every such field filled; one that never does, with a bot only. */
const paramsOf = (op: PageOp): Record<string, unknown> => (REMOTE_OPS[op].send === "always" ? { bot: "kami" } : { bot: "kami", ...LOCAL });

async function client() {
  const b = new BridgeClient({ url: "ws://test", WebSocketImpl: FakeSocket as unknown as typeof WebSocket });
  await b.connect();
  return { b, sock: FakeSocket.last! };
}
const send = (b: BridgeClient, op: string, params: Record<string, unknown>) => (b.request as unknown as (o: string, p: unknown) => Promise<unknown>)(op, params);
const sentOps = (s: FakeSocket) => s.sent.map((x) => JSON.parse(x) as Record<string, unknown>);

const ops = Object.entries(REMOTE_OPS) as [PageOp, OpRule][];

afterEach(() => noteServerMode({ mode: "local" }));

describe("the page's one outgoing filter (rule 46)", () => {
  it("on a server: every op that carries this computer is refused before the socket; the rest are sent", async () => {
    noteServerMode({ mode: "remote", host: "demo@vps" });
    const { b, sock } = await client();
    for (const [op, rule] of ops) {
      const before = sock.sent.length;
      const got = await send(b, op, paramsOf(op)).then(
        () => "sent",
        (e: { code: string; message: string }) => e,
      );
      if (rule.send === "always") {
        expect(got, op).toBe("sent");
        expect(sock.sent.length, op).toBe(before + 1);
      } else {
        expect(got, op).toMatchObject({ code: "remote_only", message: expect.stringContaining("omher uses a server") });
        expect(sock.sent.length, `${op} reached the socket`).toBe(before);
      }
    }
    // nothing of this computer was written to the socket by any op
    const wire = sock.sent.join("\n");
    for (const v of [LOCAL.cwd, LOCAL.data, LOCAL.data_base64, LOCAL.url]) expect(wire).not.toContain(v);
  });

  it("on a server: an op refused for one field goes without it (a plain thread, the default face, the server's own runs)", async () => {
    noteServerMode({ mode: "remote", host: "demo@vps" });
    const { b, sock } = await client();
    const partial = ops.filter(([, r]) => r.send === "without");
    expect(partial.map(([op]) => op).sort()).toEqual(["bots.set_avatar", "runs.cli", "thread.create"]);
    for (const [op, rule] of partial) {
      if (rule.send !== "without") continue;
      const { [rule.field]: _dropped, ...rest } = { bot: "kami", ...LOCAL } as Record<string, unknown>;
      await expect(send(b, op, rest), op).resolves.toEqual({});
    }
    expect(sentOps(sock).map((m) => m.op)).toEqual(partial.map(([op]) => op));
    await expect(send(b, "bots.set_avatar", { bot: "kami", clear: true })).resolves.toEqual({});
  });

  it("on a server: an op the audit does not name is refused", async () => {
    noteServerMode({ mode: "remote", host: "demo@vps" });
    const { b, sock } = await client();
    await expect(send(b, "files.upload", { path: LOCAL.cwd })).rejects.toMatchObject({ code: "remote_only" });
    expect(remoteRefusal("toString", {})).not.toBeNull();
    expect(sock.sent).toEqual([]);
  });

  it("in local mode every audited op is sent as before, with its fields", async () => {
    noteServerMode({ mode: "local" });
    const { b, sock } = await client();
    for (const [op] of ops) await expect(send(b, op, paramsOf(op)), op).resolves.toEqual({});
    expect(sentOps(sock).map((m) => m.op)).toEqual(ops.map(([op]) => op));
    expect(sentOps(sock).find((m) => m.op === "runs.cli")).toMatchObject({ cwd: LOCAL.cwd });
    expect(sentOps(sock).find((m) => m.op === "chat.attach")).toMatchObject({ data_base64: LOCAL.data_base64 });
  });

  it("names every op the page sends anywhere in src (string calls included), and every folder/file op is refused", () => {
    const SRC = join(__dirname, "..");
    const files: string[] = [];
    const walk = (d: string) => {
      for (const n of readdirSync(d)) {
        const p = join(d, n);
        if (statSync(p).isDirectory()) walk(p);
        else if (/\.tsx?$/.test(n) && !/\.test\.tsx?$/.test(n)) files.push(p);
      }
    };
    walk(SRC);
    const used = new Set<string>();
    for (const f of files) {
      const text = readFileSync(f, "utf-8");
      for (const m of text.matchAll(/\b(?:request|threadReq)\(\s*["`]([a-z_]+\.[a-z_]+)["`]/g)) used.add(m[1]);
      // a template op (`automations.${action}`): each of its family the audit names
      for (const m of text.matchAll(/\brequest\(\s*`([a-z_]+)\.\$\{/g)) expect(ops.some(([op]) => op.startsWith(`${m[1]}.`)), m[1]).toBe(true);
    }
    expect(used.size).toBeGreaterThan(60);
    for (const op of used) expect(Object.keys(REMOTE_OPS), `${op} is sent but not audited`).toContain(op);
    // the ops the brief names: folder chats, attachments, avatar data, a local terminal's cwd, peer links
    for (const op of ["folder.open", "folder.resume", "folder.close", "chat.attach", "cli.title", "peers.probe", "peers.attach"] as PageOp[])
      expect(REMOTE_OPS[op].send, op).toBe("never");
    expect(REMOTE_OPS["bots.set_avatar"]).toMatchObject({ send: "without", field: "data" });
    expect(REMOTE_OPS["runs.cli"]).toMatchObject({ send: "without", field: "cwd" });
  });
});
