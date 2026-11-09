import { describe, expect, it } from "vitest";
import { attachKind, badgeFor, limitReason, MAX_BYTES, previewKind, promptText } from "./attachFiles";

describe("attachFiles", () => {
  it("routes images, PDFs and everything else to the matching Hermes attach call", () => {
    expect(attachKind("a.PNG")).toBe("image");
    expect(attachKind("scan.jpeg")).toBe("image");
    expect(attachKind("report.pdf")).toBe("pdf");
    expect(attachKind("blob", "application/pdf")).toBe("pdf");
    expect(attachKind("clip.mp4")).toBe("file");
    expect(attachKind("photo.heic")).toBe("file"); // not an image Hermes takes
    expect(attachKind("notes")).toBe("file");
  });

  it("previews images and video, cards for the rest", () => {
    expect(previewKind("a.webp")).toBe("image");
    expect(previewKind("clip.mov")).toBe("video");
    expect(previewKind("x.bin", "video/quicktime")).toBe("video");
    expect(previewKind("r.pdf")).toBe("file");
    expect(badgeFor("r.pdf")).toBe("PDF");
    expect(badgeFor("archive.tar.gzip")).toBe("GZIP");
    expect(badgeFor("README")).toBe("FILE");
  });

  it("20 files, 100 MB each", () => {
    expect(limitReason(MAX_BYTES, 0)).toBeNull();
    expect(limitReason(MAX_BYTES + 1, 0)).toBe("Over 100 MB");
    expect(limitReason(10, 19)).toBeNull();
    expect(limitReason(10, 20)).toBe("Over 20 files");
  });

  it("puts @file refs before the typed text; with no text the attach lines stand in", () => {
    const img = { kind: "image" as const, name: "a.png", ref_text: "", text: "[User attached image: a.png]" };
    const file = { kind: "file" as const, name: "n.txt", ref_text: "@file:attachments/n.txt", text: "" };
    expect(promptText("  look  ", [img, file])).toBe("@file:attachments/n.txt\n\nlook");
    expect(promptText("", [img])).toBe("[User attached image: a.png]");
    expect(promptText("", [img, file])).toBe("@file:attachments/n.txt\n\n[User attached image: a.png]");
    expect(promptText("hi", [])).toBe("hi");
  });
});
