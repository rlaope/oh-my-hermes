# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/timeline.py: explicit cue graph (timing.json), plus the upstream script.json
# composition (narration lines, scenes, SFX, music analysis -> timeline.json and reel/timeline.js)
# with a stdlib loudness envelope in place of numpy.
# Full permission/warranty: ../LICENSE.upstream. Standalone, not an OMH import.
"""Validate first, then emit a language-neutral, narration-optional cue timeline.

  timeline.py timing.json [--out compiled.json]          explicit cue graph (seconds/frame/after)
  timeline.py <project>/script.json [--music-analysis audio/music/analysis.json] [--ffmpeg ffmpeg]
      upstream composition: writes <project>/timeline.json (mixer/QA) and <project>/reel/timeline.js
      (window.TL for REEL.cue/bar/beat/level/charTimes). Narration lines need narrate.py output in
      audio/vo first; with "lines": [] only scenes, SFX and music are placed. Errors exit 1.
"""
from __future__ import annotations

import argparse
import array
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys


def system_alias(part):
    # macOS ships /etc, /tmp and /var (home of the default temp dir) as links
    # into /private. Only root can create a top-level entry, so trust exactly
    # those three, and only when the link names the same directory there.
    if sys.platform != "darwin" or part.parent != Path("/") or part.name not in ("etc", "tmp", "var"):
        return False
    try:
        return os.readlink(part) in ("private/" + part.name, "/private/" + part.name)
    except OSError:
        return False


def read_spec(path, expected=dict):
    path = Path(path).absolute()
    # The file, its folder and that folder's parent; above is the operator's own layout.
    if any(p.is_symlink() and not system_alias(p) for p in (path, path.parent, path.parent.parent)) or not path.is_file() or path.stat().st_size > 1_048_576:
        raise ValueError("spec must be a regular symlink-free UTF-8 JSON file <=1 MiB")
    def invalid_constant(value):
        raise ValueError(f"nonfinite JSON constant: {value}")
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid_constant)
    if not isinstance(value, expected):
        raise ValueError("spec has incorrect JSON root type")
    return value


def number(value, label, minimum: float=0, maximum: float=600):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be finite in [{minimum}, {maximum}]")
    return float(value)


def settings(duration, fps, width=1920, height=1080):
    duration = number(duration, "duration", 1 / 60, 600)
    fps = number(fps, "fps", 1, 60)
    frames = duration * fps
    if abs(frames - round(frames)) > 1e-7 or frames > 36000:
        raise ValueError("duration * fps must be an integer <= 36000 frames")
    for label, size in (("width", width), ("height", height)):
        number(size, label, 16, 4096)
        if int(size) != size or size % 2:
            raise ValueError(f"{label} must be an even integer")
    if width * height * frames > 20_000_000_000:
        raise ValueError("render pixel budget exceeded")
    return {"duration": duration, "fps": fps, "frames": round(frames), "width": int(width), "height": int(height)}


def compile_timeline(spec):
    config = settings(spec["duration"], spec["fps"], spec.get("width", 1920), spec.get("height", 1080))
    rows = spec.get("cues", [])
    if not isinstance(rows, list) or len(rows) > 4096:
        raise ValueError("cues must be a list of <=4096 entries")
    by_id = {}
    for row in rows:
        key = row.get("id")
        if not isinstance(key, str) or not key or len(key) > 128 or any(ord(c) < 32 for c in key) or key in by_id:
            raise ValueError("invalid/duplicate cue id")
        if sum(k in row for k in ("seconds", "frame", "after")) != 1:
            raise ValueError(f"cue {key}: choose exactly seconds, frame or after")
        by_id[key] = row
    resolved = {}
    pending = dict(by_id)
    while pending:
        progressed = False
        for key, row in list(pending.items()):
            if "after" in row:
                if row["after"] not in by_id:
                    raise ValueError(f"unknown cue: {row['after']}")
                if row["after"] not in resolved:
                    continue
                value = resolved[row["after"]] + number(row.get("offset", 0), "offset", -600, 600)
            elif "frame" in row:
                frame = number(row["frame"], "frame", 0, config["frames"])
                if frame != int(frame):
                    raise ValueError("cue frame must be integer")
                value = frame / config["fps"]
            else:
                value = row["seconds"]
            resolved[key] = round(number(value, f"cue {key}", 0, config["duration"]), 10)
            del pending[key]
            progressed = True
        if not progressed:
            raise ValueError("cyclic cue graph")
    return {**config, "cues": resolved, "alignment": spec.get("alignment", []), "alignment_evidence": "caller_supplied_not_verified"}


def envelope(path, dt, db_floor=None, ffmpeg="ffmpeg"):
    """Loudness curve 0..1: narration is peak per block over the line maximum, music is RMS mapped db_floor..0 dB."""
    rate = 8000
    raw = subprocess.run([str(ffmpeg), "-v", "error", "-nostdin", "-i", str(path), "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"],
                         capture_output=True, timeout=120).stdout
    samples = array.array("f")
    samples.frombytes(raw[:len(raw) // 4 * 4])
    if sys.byteorder != "little":
        samples.byteswap()
    hop = int(rate * dt)
    blocks = [samples[i * hop:(i + 1) * hop] for i in range(len(samples) // hop)]
    if len(blocks) < 2:
        return []
    if db_floor is None:
        peaks = [max(abs(v) for v in block) for block in blocks]
        top = max(peaks) + 1e-9
        values = [v / top for v in peaks]
    else:
        db = [20 * math.log10(math.sqrt(sum(v * v for v in block) / hop) + 1e-9) for block in blocks]
        top = max(db)
        values = [min(1.0, max(0.0, (d - top - db_floor) / -db_floor)) for d in db]
    return [round(float(v), 2) for v in values]


def generated(path):
    """timeline.json and reel/timeline.js are regenerated on every run; never through a link."""
    path = Path(path).absolute()
    if any(p.is_symlink() and not system_alias(p) for p in (path, path.parent, path.parent.parent)):
        raise ValueError(f"generated output refuses symlink: {path}")
    return path


def compose(script_path, music_analysis=None, ffmpeg="ffmpeg"):
    sp = Path(script_path).absolute()
    proj = sp.parent
    cfg = read_spec(sp)
    fps = cfg.get("fps", 30)
    dur = float(cfg.get("duration", 60))
    vo_dir = proj / "audio" / "vo"
    rep = read_spec(vo_dir / "report.json") if (vo_dir / "report.json").exists() else {}
    cues, errors, warns = {}, [], []

    def resolve(x, ctx=""):
        if isinstance(x, (int, float)):
            return float(x)
        m = re.fullmatch(r"\s*([^\s+]+?)\s*(?:([+-])\s*([\d.]+))?\s*", str(x))
        if not m:
            errors.append(f"{ctx}: cannot read time expression '{x}'")
            return None
        name, sign, off = m.groups()
        try:
            base = float(name)
        except ValueError:
            if name not in cues:
                errors.append(f"{ctx}: cue '{name}' is not defined (not yet defined, or a typo)")
                return None
            base = cues[name]
        return base + (float(off) * (1 if sign == "+" else -1) if off else 0.0)

    # Music analysis first, so narration, scenes and SFX can all use "bar9" and "music.hit2".
    music_tl = None
    ma = music_analysis or (cfg.get("music") or {}).get("analysis")
    ma_path = (Path(ma) if Path(ma).is_absolute() else proj / ma) if ma else None
    if ma_path and ma_path.exists():
        an = read_spec(ma_path)
        off = float((cfg.get("music") or {}).get("start", 0))
        hits = [round(h + off, 3) for h in an.get("hits", [])]
        for k, h in enumerate(hits):
            cues[f"music.hit{k + 1}"] = h
        for k, b in enumerate(an.get("downbeats", [])):
            cues[f"bar{k + 1}"] = round(b + off, 3)
        drops = [{**drop, "t": round(drop["t"] + off, 3)} for drop in an.get("drops", [])]
        for k, drop in enumerate(drops):
            cues[f"music.drop{k + 1}"] = drop["t"]
        music_tl = {"bpm": an.get("bpm"), "hits": hits, "beats": [round(b + off, 3) for b in an.get("beats", [])],
                    "downbeats": [round(b + off, 3) for b in an.get("downbeats", [])], "drops": drops}

    vo = []
    prev_end = None
    for line in cfg.get("lines", []):
        lid = line["id"]
        r = rep.get(lid)
        alf = vo_dir / f"{lid}.align.json"
        if not r or not alf.exists():
            errors.append(f"{lid}: narration not generated yet -> run narrate.py first")
            continue
        al = read_spec(alf)
        s0, s1 = r["speech_start"], r["speech_end"]
        if "at" in line:
            start = resolve(line["at"], lid)
            if start is None:
                continue
        elif prev_end is None:
            start = float(cfg.get("first_at", 0.6))
        else:
            start = prev_end + float(line.get("gap", cfg.get("gap", 0.35)))
        end = start + (s1 - s0)
        clip_start = start - s0
        chars = al.get("characters") or []
        cst = al.get("character_start_times_seconds") or []
        cen = al.get("character_end_times_seconds") or []
        joined = "".join(chars)
        words, cur, w0, w1 = [], "", None, None
        for c, a0, a1 in zip(chars, cst, cen):
            if c.isspace():
                if cur:
                    words.append([cur, round(clip_start + w0, 3), round(clip_start + w1, 3)])
                cur, w0 = "", None
                continue
            if w0 is None:
                w0 = a0
            cur += c
            w1 = a1
        if cur:
            words.append([cur, round(clip_start + w0, 3), round(clip_start + w1, 3)])
        for w in words:  # alignment can stretch the last word over trailing silence
            w[2] = round(min(w[2], end), 3)
            w[1] = round(min(w[1], w[2]), 3)
        cues[f"line.{lid}"] = round(start, 3)
        cues[f"line.{lid}.end"] = round(end, 3)
        for name, sub in (line.get("cues") or {}).items():
            k = joined.find(sub)
            if k < 0:
                k2 = joined.replace(" ", "").find(sub.replace(" ", ""))
                if k2 >= 0:
                    k = [j for j, c in enumerate(chars) if not c.isspace()][k2]
            if k < 0:
                errors.append(f"{lid}: cue '{name}' text '{sub}' not found in the pronunciation text (tts); copy the tts string exactly")
                continue
            cues[name] = round(clip_start + cst[k], 3)
        if prev_end is not None and start < prev_end + 0.12:
            errors.append(f"{lid}: overlaps the previous line ({start:.2f}s < previous end {prev_end:.2f}s + 0.12); delay 'at' or shorten the previous line")
        if end > dur - 0.4:
            errors.append(f"{lid}: runs past the target length {dur:g}s (ends {end:.2f}s); shorten it or pull earlier lines forward")
        vo.append({"id": lid, "text": line["text"], "sub": line.get("sub", line["text"]), "nosub": bool(line.get("nosub")), "nosrt": bool(line.get("nosrt")),
                   "start": round(start, 3), "end": round(end, 3), "clip": f"audio/vo/{lid}.mp3",
                   "clip_start": round(clip_start, 3), "gain_db": line.get("gain_db", 0), "words": words})
        prev_end = end

    scenes = []
    for s in cfg.get("scenes", []):
        st = resolve(s["start"], f"scene {s['id']}")
        en = resolve(s["end"], f"scene {s['id']}") if "end" in s else None
        if st is None:
            continue
        cues[f"scene.{s['id']}"] = round(st, 3)
        if en is not None:
            cues[f"scene.{s['id']}.end"] = round(en, 3)
        scenes.append({"id": s["id"], "start": round(st, 3), "end": round(en, 3) if en is not None else None})
    for i, s in enumerate(scenes):
        if s["end"] is None:
            s["end"] = scenes[i + 1]["start"] if i + 1 < len(scenes) else dur
            cues[f"scene.{s['id']}.end"] = round(s["end"], 3)

    sfx = []
    for e in cfg.get("sfx", []):
        t = resolve(e.get("at", 0), f"sfx {e.get('name')}")
        if t is None:
            continue
        t += float(e.get("offset", 0))
        f = e.get("file")
        if not f:  # provider mp3 or synthesized wav
            f = next((c for c in (f"audio/sfx/{e['name']}.mp3", f"audio/sfx/{e['name']}.wav") if (proj / c).exists()), f"audio/sfx/{e['name']}.mp3")
        if not (proj / f).exists():
            warns.append(f"sfx {e['name']}: missing file {f} (make it with synth_music.py or the opt-in eleven.py sfx)")
        sfx.append({"name": e["name"], "file": f, "t": round(t, 3), "gain_db": e.get("gain_db", -6), "align": e.get("align", "start")})

    music = cfg.get("music")
    if music and music.get("file") and not (proj / music["file"]).exists():
        warns.append(f"missing music file: {music['file']}")
    for v in vo:
        v["env"] = {"t0": v["clip_start"], "dt": 0.02, "v": envelope(proj / v["clip"], 0.02, ffmpeg=ffmpeg)}
    if music and music.get("file") and (proj / music["file"]).exists():
        music_tl = music_tl or {}
        music_tl["energy"] = {"t0": float(music.get("start", 0)), "dt": 0.05, "v": envelope(proj / music["file"], 0.05, db_floor=-30, ffmpeg=ffmpeg)}

    tl = {"duration": dur, "fps": fps, "vo": [{k: x for k, x in v.items() if k != "env"} for v in vo], "cues": dict(sorted(cues.items(), key=lambda x: x[1])),
          "scenes": scenes, "sfx": sfx, "music": music,
          "music_tl": {k: x for k, x in music_tl.items() if k != "energy"} if music_tl else None}
    page_tl = {"duration": dur, "cues": tl["cues"], "scenes": scenes, "music": music_tl,
               "vo": [{k: v[k] for k in ("id", "text", "sub", "nosub", "start", "end", "words", "env")} for v in vo]}
    generated(proj / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    (proj / "reel").mkdir(exist_ok=True)
    generated(proj / "reel" / "timeline.js").write_text("// Written by timeline.py; edit script.json and rerun instead of editing this file.\nwindow.TL = " + json.dumps(page_tl, ensure_ascii=False) + ";\n", encoding="utf-8")
    return tl, warns, errors


def report(tl, warns, errors, proj):
    vo, dur = tl["vo"], tl["duration"]
    print(f"{'id':6s} {'start':>6s} {'end':>6s} {'len':>5s}  subtitle")
    for v in vo:
        print(f"{v['id']:6s} {v['start']:6.2f} {v['end']:6.2f} {v['end'] - v['start']:5.2f}  {v['sub']}")
    bar = ["."] * int(dur)
    for v in vo:
        for s in range(int(v["start"]), min(int(dur), int(v["end"]) + 1)):
            bar[s] = "#"
    speech = sum(v["end"] - v["start"] for v in vo)
    print("speech map (1 cell = 1 s): " + "".join(bar))
    print(f"speech {speech:.1f}s / {dur:g}s = {speech / dur * 100:.0f}% | {len(tl['cues'])} cues | {len(tl['sfx'])} sfx")
    for w in warns:
        print("WARN " + w)
    for e in errors:
        print("FAIL " + e)
    print(f"-> {proj / 'timeline.json'} | {proj / 'reel' / 'timeline.js'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("timing", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--music-analysis")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    spec = read_spec(args.timing)
    if any(key in spec for key in ("lines", "scenes", "sfx", "music")):
        tl, warns, errors = compose(args.timing, args.music_analysis, args.ffmpeg)
        report(tl, warns, errors, Path(args.timing).absolute().parent)
        raise SystemExit(1 if errors else 0)
    result = compile_timeline(spec)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
