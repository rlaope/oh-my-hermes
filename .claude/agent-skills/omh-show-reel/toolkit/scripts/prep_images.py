# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/prep_images.py: messages in English, Pillow is an explicit prerequisite (HOLD without it),
# and the macOS cutout tool compiles into <out>/.tools/ instead of the installed toolkit folder.
# Full permission/warranty: ../LICENSE.upstream. Standalone, not an OMH import.
"""Image post-processing: tidy generated and collected images for use in the video.

Usage
  prep_images.py <input folder or files> --out assets/img [--width 2400] [--blur] [--cutout]
  prep_images.py --sheet <folder> --out qa/sheet_images.png        (thumbnail sheet for review)

Processing
  - Letterbox removal: a model given a mismatched instruction such as "16:9 (1536x1024)" paints black bars above and
    below; rows are found by brightness and cut away.
  - EXIF rotation fixed, long side resized to --width with Lanczos plus a light sharpen, JPG quality 92 (transparent PNG stays PNG).
  - --blur: also writes a blurred copy (<name>_blur.jpg) for backgrounds and transitions.
  - --cutout: on macOS, a subject cutout PNG (<name>_cut.png) via Vision. Compiles tools/cutout.swift with swiftc once (about 20 s).
Never generate photos of real people; use real photos with their source recorded. A cutout leaves the subject pixels unchanged.
"""
import argparse
import platform
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
except ImportError:
    sys.exit("HOLD: prep_images.py needs Pillow in the interpreter you run it with; nothing is installed for you")

HERE = Path(__file__).resolve().parent
EXTS = {".png", ".jpg", ".jpeg", ".webp", ".heic"}


def letterbox(im):
    g = im.convert("L")
    w, h = g.size
    px = g.load()
    def row_dark(y):
        vals = [px[x, y] for x in range(0, w, max(1, w // 200))]
        return max(vals) < 24 and sum(vals) / len(vals) < 6
    top = 0
    while top < h // 4 and row_dark(top):
        top += 1
    bot = 0
    while bot < h // 4 and row_dark(h - 1 - bot):
        bot += 1
    if top > 8 or bot > 8:
        return im.crop((0, top, w, h - bot)), (top, bot)
    return im, (0, 0)


def cutout_bin(out):
    b = out / ".tools" / "cutout"
    if not b.exists():
        b.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["swiftc", "-O", str(HERE / "tools" / "cutout.swift"), "-o", str(b)], capture_output=True, text=True)
        if r.returncode != 0:
            print("cutout tool failed to compile (needs Xcode Command Line Tools):\n" + r.stderr[-400:])
            return None
    return b


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*")
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=2400)
    ap.add_argument("--blur", action="store_true")
    ap.add_argument("--cutout", action="store_true")
    ap.add_argument("--sheet")
    a = ap.parse_args()

    if a.sheet:
        files = sorted(p for p in Path(a.sheet).iterdir() if p.suffix.lower() in EXTS)
        raw = [(p.name, ImageOps.exif_transpose(Image.open(p)).convert("RGB")) for p in files]
        portrait = sum(im.height > im.width for _, im in raw) > len(raw) / 2
        cols, tw, th = (6, 300, 534) if portrait else (4, 480, 320)   # portrait images are shown large and upright
        ims = []
        for n, im in raw:
            im.thumbnail((tw, th))
            ims.append((n, im))
        rows = (len(ims) + cols - 1) // cols
        th = max(im.height for _, im in ims)   # row height follows the real thumbnails (no empty band under 16:9)
        sheet = Image.new("RGB", (cols * (tw + 8), rows * (th + 30)), (24, 24, 26))
        d = ImageDraw.Draw(sheet)
        for i, (n, im) in enumerate(ims):
            x, y = (i % cols) * (tw + 8) + 4, (i // cols) * (th + 30) + 4
            sheet.paste(im, (x, y + 22))
            d.text((x, y + 4), f"{n} {im.width}x{im.height}", fill=(255, 214, 90))
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        sheet.save(a.out)
        print(a.out)
        return

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for i in a.inputs:
        p = Path(i)
        files += sorted(x for x in p.iterdir() if x.suffix.lower() in EXTS) if p.is_dir() else [p]
    cb = cutout_bin(out) if a.cutout and platform.system() == "Darwin" else None
    if a.cutout and not cb:
        print("cutout is built in only on macOS; elsewhere use your own matting tool")
    for p in files:
        im = ImageOps.exif_transpose(Image.open(p))
        alpha = im.mode in ("RGBA", "LA") and im.getextrema()[-1][0] < 255
        im = im.convert("RGBA" if alpha else "RGB")
        im, (t, b) = letterbox(im) if not alpha else (im, (0, 0))
        scale = a.width / max(im.size)
        if abs(scale - 1) > 0.02:
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            if scale > 1:
                im = im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
        dst = out / (p.stem + (".png" if alpha else ".jpg"))
        im.save(dst, **({} if alpha else {"quality": 92}))
        note = f" letterbox removed (top {t}px, bottom {b}px)" if t or b else ""
        print(f"{dst} {im.width}x{im.height}{note}")
        if a.blur and not alpha:
            im.resize((im.width // 2, im.height // 2)).filter(ImageFilter.GaussianBlur(14)).save(out / f"{p.stem}_blur.jpg", quality=85)
        if cb:
            r = subprocess.run([str(cb), str(dst), str(out / f"{p.stem}_cut.png")], capture_output=True, text=True)
            print("  cutout: " + (r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:]))


if __name__ == "__main__":
    main()
