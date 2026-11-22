// Pictures a program prints in a SESSIONS terminal: sixel, iTerm2's inline images (OSC 1337 File=...;inline=1) and
// the Kitty graphics protocol, drawn by xterm's image add-on on a layer over the text. The add-on's chunk loads the
// first time a terminal wants it (with Settings > Terminal > Show images on), never with the app.
//
// What is kept: only the decoded pictures, in this terminal's memory, up to IMAGE_STORAGE_MB for the add-on's and the
// Kitty virtual placements' (kitty-placeholders.ts) together (the oldest go first);
// a closed or parked terminal drops them. Nothing is written to disk or sent anywhere. Kitty's file and shared-memory
// transfers (a program naming a path for the terminal to read) are refused by the add-on: only bytes the program
// prints are drawn.
import type { IImageAddonOptions, ImageAddon } from "@xterm/addon-image";
import type { Terminal } from "@xterm/xterm";
import { attachPlaceholders, type Placeholders } from "./kitty-overlay";
import type { Transmitted } from "./kitty-placeholders";

/** Decoded pictures one terminal keeps, in MB (Orca's figure); past it the oldest are dropped. */
export const IMAGE_STORAGE_MB = 32;
/** The largest encoded picture sequence one image may take (bytes): bounds the decoder's work on a runaway stream. */
export const IMAGE_SEQUENCE_BYTES = 8 * 1024 * 1024;
/** The most pixels one picture may have: one picture can never be larger than the whole store (4 bytes a pixel). */
export const PIXEL_LIMIT = (IMAGE_STORAGE_MB * 1_000_000) / 4;

/** The add-on's options: one picture can never be larger than the whole store (4 bytes a pixel). */
export function imageOptions(): IImageAddonOptions {
  return {
    storageLimit: IMAGE_STORAGE_MB,
    pixelLimit: PIXEL_LIMIT,
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
const addons = new WeakMap<Terminal, { addon: ImageAddon; windowOptions: Terminal["options"]["windowOptions"]; virtual: Placeholders | null }>();

/** The add-on's decoded pictures (bytes). */
const addonBytes = (addon: ImageAddon): number => Math.max(0, Math.round(addon.storageUsage * 1_000_000));

/** What the add-on kept for a Kitty id (`a=t` without U=1), read from its internals after checking their shape
 *  (`_handlers.get("kitty")._kittyStorage.getImage`); undefined when they are not there (another add-on version). */
function addonTransmitted(addon: ImageAddon, id: number): Transmitted | undefined {
  type KittyStore = { getImage?(id: number): unknown };
  const handlers = (addon as unknown as { _handlers?: unknown })._handlers;
  if (!(handlers instanceof Map)) return undefined;
  const store = (handlers.get("kitty") as { _kittyStorage?: KittyStore } | undefined)?._kittyStorage;
  if (typeof store?.getImage !== "function") return undefined;
  const t = store.getImage(id) as Partial<Transmitted> | undefined;
  if (!t || !(t.data instanceof Blob) || (t.format !== 24 && t.format !== 32 && t.format !== 100)) return undefined;
  return { data: t.data, width: Number(t.width) || 0, height: Number(t.height) || 0, format: t.format, compression: t.compression };
}

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
    // Kitty Unicode placeholders (virtual placements, U=1), which the add-on does not draw: registered after it, so
    // its handler is asked first and passes every other Kitty command on to the add-on. Both share one budget: the
    // virtual store leaves room for the add-on's pictures, and drops its oldest when the add-on adds one
    let virtual: Placeholders | null = null;
    try {
      const a = addon;
      virtual = attachPlaceholders(term, undefined, { used: () => addonBytes(a), transmitted: (id) => addonTransmitted(a, id) });
      const v = virtual;
      v.subs.push(a.onImageAdded(() => v.store.fit()));
    } catch {
      /* pictures still drawn by the add-on */
    }
    addons.set(term, { addon, windowOptions, virtual });
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
    a.virtual?.dispose();
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
    return addonBytes(a.addon) + (a.virtual?.store.usage ?? 0);
  } catch {
    return 0;
  }
}

/** `term`'s Kitty virtual placements (Unicode placeholders), null with pictures off. e2e reads it. */
export const virtualImages = (term: Terminal): Placeholders | null => addons.get(term)?.virtual ?? null;
