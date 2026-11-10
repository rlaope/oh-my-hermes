import { describe, expect, it } from "vitest";
import { extOf, fileName, fileSize, mediaKind, splitMedia } from "./mediaLines";

describe("splitMedia", () => {
  it("takes whole MEDIA lines out of the text, in order", () => {
    const r = splitMedia("Done.\n\nMEDIA:/w/a.png\nMEDIA: /w/b clip.mp4\nMEDIA:`/w/c.zip`");
    expect(r.text).toBe("Done.");
    expect(r.paths).toEqual(["/w/a.png", "/w/b clip.mp4", "/w/c.zip"]);
  });

  it("leaves prose, relative paths and fenced examples alone", () => {
    const text = "Use MEDIA:/w/a.png to attach.\nMEDIA:a.png\n```\nMEDIA:/w/x.png\n```";
    expect(splitMedia(text)).toEqual({ text, paths: [] });
  });

  it("accepts home and Windows paths", () => {
    expect(splitMedia("MEDIA:~/a.png\nMEDIA:C:\\w\\b.mp3").paths).toEqual(["~/a.png", "C:\\w\\b.mp3"]);
  });
});

describe("kinds and labels", () => {
  it("picks the kind from the extension; HEIC and unknown types are files", () => {
    expect(mediaKind("/w/a.JPG")).toBe("image");
    expect(mediaKind("/w/a.m4v")).toBe("video");
    expect(mediaKind("/w/a.ogg")).toBe("audio");
    expect(mediaKind("/w/a.heic")).toBe("file");
    expect(mediaKind("/w/Makefile")).toBe("file");
  });

  it("names and sizes", () => {
    expect(fileName("C:\\w\\report.pdf")).toBe("report.pdf");
    expect(extOf("/w/archive.tar.gz")).toBe("gz");
    expect(fileSize(900)).toBe("900 B");
    expect(fileSize(1536)).toBe("1.5 KB");
    expect(fileSize(80 * 1024 * 1024)).toBe("80 MB");
  });
});
