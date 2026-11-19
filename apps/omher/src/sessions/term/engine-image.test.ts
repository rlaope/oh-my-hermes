// engine-image.ts: the image add-on's limits, and attach/detach against a real, unopened xterm with the real add-on
// (it changes the terminal's size-report switches; drawing is checked on a page by e2e/term-images.spec.ts).
import { Terminal } from "@xterm/xterm";
import { ImageAddon } from "@xterm/addon-image";
import { afterEach, describe, expect, it } from "vitest";
import { IMAGE_SEQUENCE_BYTES, IMAGE_STORAGE_MB, attachImages, detachImages, drawsImages, imageBytes, imageOptions, loadImages, resetImageLoad } from "./engine-image";


afterEach(() => resetImageLoad());

describe("engine-image", () => {
  it("keeps 32 MB of pictures per terminal, one picture no larger than that, and every protocol on", () => {
    expect(IMAGE_STORAGE_MB).toBe(32);
    expect(imageOptions()).toEqual({
      storageLimit: 32,
      pixelLimit: 8_000_000,
      sixelSupport: true,
      sixelSizeLimit: IMAGE_SEQUENCE_BYTES,
      iipSupport: true,
      iipSizeLimit: IMAGE_SEQUENCE_BYTES,
      kittySupport: true,
      kittySizeLimit: IMAGE_SEQUENCE_BYTES,
    });
    // the add-on's own defaults are larger (128 MB, 4096x4096): these are ours, not its
    expect(imageOptions().pixelLimit! * 4).toBeLessThanOrEqual(IMAGE_STORAGE_MB * 1_000_000);
  });

  it("loads the chunk once, and tries again after a failed load", async () => {
    let calls = 0;
    const fail = () => {
      calls++;
      return Promise.reject(new Error("offline"));
    };
    await expect(loadImages(fail)).rejects.toThrow("offline");
    const ok = () => {
      calls++;
      return Promise.resolve({ ImageAddon });
    };
    expect(await loadImages(ok)).toBe(ImageAddon);
    expect(await loadImages(ok)).toBe(ImageAddon);
    expect(calls).toBe(2);
  });

  // drawing needs a canvas (a page): e2e/term-images.spec.ts feeds real pictures to a terminal on the page
  it("attaches once per terminal, and detaching drops its pictures", () => {
    const t = new Terminal({ cols: 20, rows: 5, allowProposedApi: true });
    expect(drawsImages(t)).toBe(false);
    expect(attachImages(t, ImageAddon)).toBe(true);
    expect(drawsImages(t)).toBe(true);
    expect(attachImages(t, ImageAddon)).toBe(true);
    expect(imageBytes(t)).toBe(0);
    detachImages(t);
    expect(drawsImages(t)).toBe(false);
    detachImages(t); // twice is nothing
    t.dispose();
  });

  it("puts the size reports back as they were when the add-on goes", () => {
    const t = new Terminal({ cols: 20, rows: 5, allowProposedApi: true });
    expect(t.options.windowOptions?.getCellSizePixels).toBeFalsy();
    attachImages(t, ImageAddon);
    expect(t.options.windowOptions?.getCellSizePixels).toBe(true);
    // another terminal, made while this one draws pictures, does not get them on
    const other = new Terminal({ cols: 20, rows: 5, allowProposedApi: true });
    expect(other.options.windowOptions?.getCellSizePixels).toBeFalsy();
    detachImages(t);
    expect(t.options.windowOptions?.getCellSizePixels).toBeFalsy();
    t.dispose();
    other.dispose();
  });

  it("an add-on that will not start leaves the terminal without pictures and says so", () => {
    const t = new Terminal({ cols: 20, rows: 5, allowProposedApi: true });
    class Broken extends ImageAddon {
      override activate(): void {
        throw new Error("no canvas");
      }
    }
    expect(attachImages(t, Broken)).toBe(false);
    expect(drawsImages(t)).toBe(false);
    t.dispose();
  });
});
