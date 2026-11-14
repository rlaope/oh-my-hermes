import { describe, expect, it } from "vitest";
import { labelFor, parsePeerDrafts, peerDraftsAllowed, validHost, validLabel } from "./draft";

const fence = (body: string) => "```omher-peer\n" + body + "\n```";

describe("omher-peer drafts", () => {
  it("reads one fenced block with host and label", () => {
    const text = `Sure.\n\n${fence('{"host": "sionic@10.1.145.204", "label": "Mac mini"}')}\n\nPress Connect.`;
    expect(parsePeerDrafts(text)).toEqual([{ draft: { host: "sionic@10.1.145.204", label: "Mac mini" }, why: null }]);
  });

  it("reads an inline one-line block, a ~~~ fence, a port, and ignores unknown keys", () => {
    const text = '```omher-peer {"host": "mini", "label": "Mini", "extra": 1}```\n~~~omher-peer\n{"host": "box", "port": 2222}\n~~~';
    expect(parsePeerDrafts(text)).toEqual([
      { draft: { host: "mini", label: "Mini" }, why: null },
      { draft: { host: "box", label: "box", port: 2222 }, why: null },
    ]);
  });

  it("fills a missing label from the host", () => {
    expect(labelFor("sionic@mac-mini.local")).toBe("mac-mini");
    expect(labelFor("10.1.145.204")).toBe("10.1.145.204");
    expect(parsePeerDrafts(fence('{"host": "u@studio.lan"}'))[0]).toEqual({ draft: { host: "u@studio.lan", label: "studio" }, why: null });
  });

  it("gives the reason for a block that is not a draft", () => {
    const why = (body: string) => parsePeerDrafts(fence(body))[0].why;
    expect(why("{not json")).toBe("json");
    expect(why("[1, 2]")).toBe("json");
    expect(why('{"label": "x"}')).toBe("shape");
    expect(why('{"host": 3}')).toBe("shape");
    expect(why('{"host": "mini", "port": "22"}')).toBe("shape");
    expect(why('{"host": "-oProxyCommand=sh"}')).toBe("host");
    expect(why('{"host": "mini; rm -rf ~"}')).toBe("host");
    expect(why('{"host": "$(id)@x"}')).toBe("host");
    expect(why('{"host": "mini:22"}')).toBe("host");
    expect(why('{"host": "mini", "label": "' + "x".repeat(41) + '"}')).toBe("label");
    expect(why('{"host": "mini", "port": 0}')).toBe("port");
    expect(why('{"host": "mini", "port": 70000}')).toBe("port");
    expect(why('{"host": "mini", "port": 22.5}')).toBe("port");
  });

  it("finds nothing in text without a block, or in a block of another kind", () => {
    expect(parsePeerDrafts("connect to mini please")).toEqual([]);
    expect(parsePeerDrafts('```json\n{"host": "mini"}\n```')).toEqual([]);
    expect(parsePeerDrafts('```omher-agent\n{"name": "x", "program": "y"}\n```')).toEqual([]);
  });

  it("checks hosts and labels the way the shell does", () => {
    for (const ok of ["mini", "sionic@10.1.145.204", "build-box.local", "_svc@h"]) expect(validHost(ok)).toBe(true);
    for (const bad of ["", "-x", "a b", "a@", "@a", "u@-h", "a/b", "a'b", "h:1", "u@h@x"]) expect(validHost(bad)).toBe(false);
    expect(validLabel("맥미니")).toBe(true);
    expect(validLabel(" ")).toBe(false);
    expect(validLabel("a\nb")).toBe(false);
  });

  it("is read only in a bot's main chat", () => {
    expect(peerDraftsAllowed("kami")).toBe(true);
    expect(peerDraftsAllowed("mini:sionic-kami")).toBe(true);
    expect(peerDraftsAllowed("fold:kami:f1")).toBe(false);
    expect(peerDraftsAllowed("agent:s3")).toBe(false);
  });
});
