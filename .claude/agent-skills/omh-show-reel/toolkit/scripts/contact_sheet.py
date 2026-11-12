# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/contact_sheet.py: messages in English, optional --ffmpeg/--ffprobe, explicit --label-font
# (no font search), an FFmpeg tile path when Pillow is absent (labels then print to stdout), and
# -fps_mode in place of -vsync, which FFmpeg 8+ removed.
# Full permission/warranty: ../LICENSE.upstream. Standalone, not an OMH import.
"""Build review contact sheets (labelled thumbnail grids). Open the PNG with a file reader and look at it.

Usage
  stills folder:  contact_sheet.py --dir qa/stills --out qa/sheet_stills.png
  video interval: contact_sheet.py --video out/video.mp4 --every 1 --out qa/sheet.png [--from 0 --to 60]
  given times:    contact_sheet.py --video out/video.mp4 --times 1.2,3.4,8 --out qa/sheet_t.png
  around cuts:    contact_sheet.py --video out/video.mp4 --around 3.0,6.1 --frames 3 --out qa/sheet_cuts.png
                  (each time's +-3 frames on one row: blank frames, ghosting, overlaps)
  common:         [--timeline timeline.json] adds scene ids to labels. [--cols 4] [--thumb 480] [--per 24]

More than --per cells split into out_01.png, out_02.png ...
Labels are drawn with Pillow so FFmpeg needs no drawtext; frames are pulled by exact frame number with select.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None


def font(size, path):
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def probe(video, ffprobe):
    out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate,nb_frames,duration:format=duration", "-of", "json", video],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    st = d["streams"][0]
    num, den = st["r_frame_rate"].split("/")
    fps = float(num) / float(den)
    dur = float(st.get("duration") or d["format"]["duration"])
    return fps, dur


def extract(video, frames, tmp, ffmpeg):
    """Pull exact frame numbers in batches."""
    frames = sorted(set(frames))
    paths = {}
    for i in range(0, len(frames), 40):  # more than ~100 eq() terms in one select makes ffmpeg run out of memory
        part = frames[i:i + 40]
        expr = "+".join(f"eq(n\\,{f})" for f in part)
        pat = os.path.join(tmp, f"b{i:05d}_%04d.png")
        subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-y", "-i", video, "-vf", f"select='{expr}'", "-fps_mode", "vfr", pat], check=True)
        got = sorted(glob.glob(os.path.join(tmp, f"b{i:05d}_*.png")))
        for f, p in zip(part, got):
            paths[f] = p
    return paths


def scene_at(tl, t):
    if not tl:
        return ""
    cur = ""
    for s in tl.get("scenes", []):
        if s["start"] <= t + 1e-6:
            cur = s["id"]
    return cur


def page_path(out, index, pages):
    return out if pages == 1 else re.sub(r"(\.\w+)$", f"_{index + 1:02d}\\1", out)


def build(items, out, cols, thumb, per, label_font=None, title=None):
    """items: [(image_path, label)]"""
    outs = []
    pages = [items[i:i + per] for i in range(0, len(items), per)] or [[]]
    f = font(max(13, thumb // 26), label_font)
    for pi, page in enumerate(pages):
        if not page:
            continue
        im0 = Image.open(page[0][0])
        w = thumb
        h = round(im0.height * thumb / im0.width)
        lab = max(20, thumb // 18)
        rows = (len(page) + cols - 1) // cols
        top = lab + 6 if title else 0
        sheet = Image.new("RGB", (cols * (w + 4) + 4, top + rows * (h + lab + 4) + 4), (24, 24, 26))
        d = ImageDraw.Draw(sheet)
        if title:
            d.text((8, 3), title, fill=(200, 200, 200), font=f)
        for i, (p, label) in enumerate(page):
            img = Image.open(p).convert("RGB").resize((w, h), Image.LANCZOS)
            x = 4 + (i % cols) * (w + 4)
            y = top + 4 + (i // cols) * (h + lab + 4)
            sheet.paste(img, (x, y + lab))
            d.text((x + 4, y + 2), label, fill=(255, 214, 90), font=f)
        path = page_path(out, pi, len(pages))
        sheet.save(path)
        outs.append(path)
    return outs


def build_ffmpeg(items, out, cols, thumb, per, ffmpeg, tmp):
    """Without Pillow: FFmpeg tiles the same grid unlabelled; the cell labels are printed in reading order."""
    outs = []
    pages = [items[i:i + per] for i in range(0, len(items), per)]
    for pi, page in enumerate(pages):
        seq = os.path.join(tmp, f"page{pi:03d}")
        os.makedirs(seq)
        for i, (p, _) in enumerate(page):
            shutil.copyfile(p, os.path.join(seq, f"{i:06d}.png"))
        rows = (len(page) + cols - 1) // cols
        path = page_path(out, pi, len(pages))
        subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-y", "-i", os.path.join(seq, "%06d.png"), "-vf",
                        f"scale={thumb}:-2:flags=lanczos,tile={cols}x{rows}:padding=4:margin=4:color=0x18181a", "-frames:v", "1", path], check=True)
        print(f"{path} (no Pillow: unlabelled) cells: " + " | ".join(label for _, label in page))
        outs.append(path)
    return outs


def compose(items, a, tmp):
    if Image is None:
        return build_ffmpeg(items, a.out, a.cols, a.thumb, a.per, a.ffmpeg, tmp)
    return build(items, a.out, a.cols, a.thumb, a.per, a.label_font)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir")
    ap.add_argument("--video")
    ap.add_argument("--out", required=True)
    ap.add_argument("--every", type=float)
    ap.add_argument("--times")
    ap.add_argument("--around")
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--from", dest="start", type=float, default=0.0)
    ap.add_argument("--to", dest="end", type=float, default=0.0)
    ap.add_argument("--timeline")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--thumb", type=int, default=480)
    ap.add_argument("--per", type=int, default=24)
    ap.add_argument("--label-font", help="explicit TTF/OTF for labels (default: Pillow's built-in font)")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tl = json.load(open(a.timeline, encoding="utf-8")) if a.timeline and os.path.exists(a.timeline) else None
    # Working files stay in the project (beside the sheet) and are removed afterwards; no system temp folder.
    tmp = os.path.join(os.path.dirname(os.path.abspath(a.out)), f".frames_{os.getpid()}")   # parallel sheets never mix
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        if a.dir:
            files = sorted(glob.glob(os.path.join(a.dir, "*.png")) + glob.glob(os.path.join(a.dir, "*.jpg")))
            items = []
            for p in files:
                m = re.search(r"t(\d+\.\d+)", os.path.basename(p))
                if m:
                    t = float(m.group(1))
                    items.append((p, f"{t:.2f}s {scene_at(tl, t)}".strip()))
                else:
                    items.append((p, os.path.basename(p)))
            outs = compose(items, a, tmp)
        else:
            fps, dur = probe(a.video, a.ffprobe)
            end = a.end or dur
            if a.around:
                cols = 2 * a.frames + 1
                frames, items_spec = [], []
                for t in [float(x) for x in a.around.split(",")]:
                    c = round(t * fps)
                    for k in range(-a.frames, a.frames + 1):
                        f = min(max(0, c + k), round(dur * fps) - 1)
                        frames.append(f)
                        items_spec.append((f, f"{t:.2f}s {'+' if k >= 0 else ''}{k}f"))
                a.cols, a.per = cols, cols * 6
            else:
                if a.times:
                    ts = [float(x) for x in a.times.split(",")]
                else:
                    step = a.every or 1.0
                    ts, x = [], a.start
                    while x < end - 1e-6:
                        ts.append(x)
                        x += step
                frames = [min(round(t * fps), round(dur * fps) - 1) for t in ts]
                items_spec = [(f, f"{f / fps:.2f}s f{f} {scene_at(tl, f / fps)}".strip()) for f in frames]
            paths = extract(a.video, frames, tmp, a.ffmpeg)
            items = [(paths[f], lab) for f, lab in items_spec if f in paths]
            outs = compose(items, a, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for o in outs:
        print(o)


if __name__ == "__main__":
    main()
