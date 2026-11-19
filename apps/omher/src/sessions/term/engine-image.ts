// Pictures a program prints in a SESSIONS terminal: sixel, iTerm2's inline images (OSC 1337 File=...;inline=1) and
// the Kitty graphics protocol, drawn by xterm's image add-on on a layer over the text. The add-on's chunk loads the
// first time a terminal wants it (with Settings > Terminal > Show images on), never with the app.
//
// What is kept: only the decoded pictures, in this terminal's memory, up to IMAGE_STORAGE_MB (the oldest go first);
// a closed or parked terminal drops them. Nothing is written to disk or sent anywhere. Kitty's file and shared-memory
// transfers (a program naming a path for the terminal to read) are refused by the add-on: only bytes the program
// prints are drawn.
import type { IImageAddonOptions, ImageAddon } from "@xterm/addon-image";
import type { Terminal } from "@xterm/xterm";

/** Decoded pictures one terminal keeps, in MB (Orca's figure); past it the oldest are dropped. */
export const IMAGE_STORAGE_MB = 32;
/** The largest encoded picture sequence one image may take (bytes): bounds the decoder's work on a runaway stream. */
export const IMAGE_SEQUENCE_BYTES = 8 * 1024 * 1024;

/** The add-on's options: one picture can never be larger than the whole store (4 bytes a pixel). */
export function imageOptions(): IImageAddonOptions {
  return {
    storageLimit: IMAGE_STORAGE_MB,
    pixelLimit: (IMAGE_STORAGE_MB * 1_000_000) / 4,
    sixelSupport: true,
    sixelSizeLimit: IMAGE_SEQUENCE_BYTES,
    iipSupport: true,
    iipSizeLimit: IMAGE_SEQUENCE_BYTES,
    kittySupport: true,
    kittySizeLimit: IMAGE_SEQUENCE_BYTES,
  };
}

type ImageCtor = typeof ImageAddon;
let imageLoad: Promise<ImageCtor> | null = null;
/** The chunk, once; a failed load is tried again by the next terminal that wants it. */
export const loadImages = (load: () => Promise<{ ImageAddon: ImageCtor }> = () => import("@xterm/addon-image")): Promise<ImageCtor> =>
  (imageLoad ??= load().then(
    (m) => m.ImageAddon,
    (e) => {
      imageLoad = null;
      throw e;
    },
  ));

/** Tests: forget the loaded chunk. */
export function resetImageLoad(): void {
  imageLoad = null;
}

/** Each terminal's add-on, and its size-report switches as they were before the add-on turned them on (CSI 14 t /
 *  16 t / 18 t: a program asks the window and cell size in pixels to fit a picture). */
const addons = new WeakMap<Terminal, { addon: ImageAddon; windowOptions: Terminal["options"]["windowOptions"] }>();

/** Draws pictures in `term` from now on. False when the add-on would not start (the terminal keeps going without). */
export function attachImages(term: Terminal, Ctor: ImageCtor): boolean {
  if (addons.has(term)) return true;
  let addon: ImageAddon | null = null;
  const windowOptions = { ...term.options.windowOptions };
  try {
    // the add-on turns the reports on in the object it finds there, which for a new terminal is xterm's default
    // shared by every terminal: this one gets its own, so the others (and terminals made later) are untouched
    term.options.windowOptions = { ...windowOptions };
    addon = new Ctor(imageOptions());
    term.loadAddon(addon);
    addons.set(term, { addon, windowOptions });
    return true;
  } catch {
    try {
      addon?.dispose();
    } catch {
      /* never fully started */
    }
    return false;
  }
}

/** Stops drawing pictures in `term` and drops the ones it kept. */
export function detachImages(term: Terminal): void {
  const a = addons.get(term);
  if (!a) return;
  addons.delete(term);
  try {
    a.addon.dispose();
    // the add-on leaves the size reports on when it goes: off again, as before it came
    term.options.windowOptions = a.windowOptions;
  } catch {
    /* the terminal went first */
  }
}

/** Whether `term` draws pictures now. */
export const drawsImages = (term: Terminal): boolean => addons.has(term);

/** What `term`'s pictures take now (bytes), 0 with none or with the add-on off. e2e reads it. */
export function imageBytes(term: Terminal): number {
  const a = addons.get(term);
  if (!a) return 0;
  try {
    return Math.max(0, Math.round(a.addon.storageUsage * 1_000_000));
  } catch {
    return 0;
  }
}
