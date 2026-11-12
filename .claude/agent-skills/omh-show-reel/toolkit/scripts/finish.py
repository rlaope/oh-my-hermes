# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/finish.py: messages and file suffixes in English (_share.mp4, _poster.jpg), optional
# --ffmpeg/--ffprobe, outputs must be new, and a spec failure exits 1 instead of 0.
# Full permission/warranty: ../LICENSE.upstream. Standalone, not an OMH import.
"""Finish: silent rendered video + mix -> delivery set (master, share copy, poster, subtitles) + spec check.

Usage
  finish.py --video out/video.mp4 --audio audio/mix.wav --name "Jane_Doe_reel_60s" [--outdir out]
            [--poster 57.5] [--timeline timeline.json] [--no-web]

Writes (under outdir)
  <name>.mp4          master: video stream copied (no re-encode), AAC 320k 48 kHz, faststart, BT.709 tags
  <name>_share.mp4    messenger/social copy: x264 CRF 23, max 8 Mbps, AAC 192k (usually 1/3 to 1/5 of the master)
  <name>_poster.jpg   the frame at --poster seconds (default 1.5 s before the end, usually the end card)
  <name>.srt          subtitle file when --timeline has narration (the same data as burned-in subtitles)
Finally ffprobe and ebur128 check the spec and print a table (yuv420p, tv range, frame count, LUFS, true peak).
If only the audio changed, do not re-render the video; rerun only this script (with a new --name or --outdir).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

TOOLS = {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"}


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"failed: {' '.join(map(str, cmd[:6]))} ...\n{r.stderr[-800:]}")
    return r


def probe(path):
    d = json.loads(run([TOOLS["ffprobe"], "-v", "error", "-count_frames", "-show_entries",
                        "stream=codec_type,codec_name,width,height,pix_fmt,color_range,color_space,color_primaries,r_frame_rate,nb_read_frames,sample_rate,channels,bit_rate"
                        ":format=duration,size", "-of", "json", str(path)]).stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    au = next((s for s in d["streams"] if s["codec_type"] == "audio"), {})
    return v, au, d["format"]


def loud(path):
    r = subprocess.run([TOOLS["ffmpeg"], "-hide_banner", "-nostats", "-nostdin", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    s = r[r.rfind("Summary:"):]
    g = lambda k: float(re.search(k + r":\s+(-?[\d.]+)", s).group(1)) if re.search(k + r":\s+(-?[\d.]+)", s) else None
    return g("I"), g("LRA"), g("Peak")


def srt_time(t):
    t = max(0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True)
    ap.add_argument("--audio")
    ap.add_argument("--name", required=True)
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--poster", type=float)
    ap.add_argument("--timeline")
    ap.add_argument("--no-web", action="store_true")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe")
    a = ap.parse_args()
    TOOLS.update(ffmpeg=a.ffmpeg, ffprobe=a.ffprobe)
    od = Path(a.outdir)
    od.mkdir(parents=True, exist_ok=True)
    planned = [od / f"{a.name}.mp4", od / f"{a.name}_poster.jpg", od / f"{a.name}.srt"] + ([] if a.no_web else [od / f"{a.name}_share.mp4"])
    existing = [str(p) for p in planned if p.exists() or p.is_symlink()]
    if existing:
        raise SystemExit("existing output refused: " + ", ".join(existing) + "; choose a new --name or --outdir")
    v, _, fmt = probe(a.video)
    vdur = float(fmt["duration"])
    master = od / f"{a.name}.mp4"
    # Pin the colour VUI to BT.709; some players read untagged video differently.
    bsf = ["-bsf:v", "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0"]
    cmd = [a.ffmpeg, "-v", "error", "-nostdin", "-n", "-i", a.video]
    if a.audio:
        cmd += ["-i", a.audio, "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "320k", "-ar", "48000"]
    cmd += ["-c:v", "copy", *bsf, "-t", f"{vdur:.3f}", "-movflags", "+faststart", str(master)]
    run(cmd)
    outs = [master]
    if not a.no_web:
        web = od / f"{a.name}_share.mp4"
        cmd = [a.ffmpeg, "-v", "error", "-nostdin", "-n", "-i", str(master), "-c:v", "libx264", "-preset", "slow", "-crf", "23",
               "-maxrate", "8M", "-bufsize", "16M", *(["-level:v", "4.2"] if int(probe(master)[0].get("height") or 0) <= 1080 else []), "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
               "-color_trc", "bt709", "-color_range", "tv"]
        if a.audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-t", f"{vdur:.3f}", "-movflags", "+faststart", str(web)]
        run(cmd)
        if a.audio:   # a second AAC encode raises peaks; if over, lower only the audio (video copied), re-measure, at most 3 times
            for _ in range(3):
                _, _, tp = loud(web)
                if tp is None or tp <= -1.0:
                    break
                tmp = web.with_name(web.stem + ".tmp.mp4")
                tmp.unlink(missing_ok=True)
                run([a.ffmpeg, "-v", "error", "-nostdin", "-n", "-i", str(web), "-c:v", "copy", "-af", f"volume={-1.6 - tp:.2f}dB",
                     "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(tmp)])
                tmp.replace(web)
        outs.append(web)
    pt = a.poster if a.poster is not None else max(0, vdur - 1.5)
    poster = od / f"{a.name}_poster.jpg"
    run([a.ffmpeg, "-v", "error", "-nostdin", "-n", "-ss", f"{pt:.3f}", "-i", str(master), "-frames:v", "1", "-q:v", "2", str(poster)])
    outs.append(poster)
    if a.timeline and Path(a.timeline).exists():
        tl = json.loads(Path(a.timeline).read_text(encoding="utf-8"))
        vo = [x for x in tl.get("vo", []) if not x.get("nosrt")]   # nosub (kept out of burn-in) still goes into the SRT
        if vo:
            lines = []
            for i, x in enumerate(vo):
                end = x["end"] + 0.3
                if i + 1 < len(vo):
                    end = min(end, vo[i + 1]["start"] - 0.05)
                lines.append(f"{i + 1}\n{srt_time(x['start'] - 0.05)} --> {srt_time(end)}\n{x.get('sub') or x['text']}\n")
            srt = od / f"{a.name}.srt"
            srt.write_text("\n".join(lines), encoding="utf-8")
            outs.append(srt)

    print(f"{'file':40s} {'size':>8s}  spec")
    ok = True
    for f in outs:
        size = f"{f.stat().st_size / 1e6:.1f}MB"
        if f.suffix == ".mp4":
            v, au, fm = probe(f)
            I, LRA, TP = loud(f) if au else (None, None, None)
            spec = (f"{v.get('width')}x{v.get('height')} {v.get('r_frame_rate')} {v.get('pix_fmt')}/{v.get('color_range')} "
                    f"{v.get('nb_read_frames')}f {float(fm['duration']):.2f}s")
            if au:
                spec += f" | AAC {au.get('sample_rate')}Hz I {I} LUFS LRA {LRA} peak {TP}dBFS"
            flags = []
            if v.get("pix_fmt") != "yuv420p" or v.get("color_range") not in ("tv", None):
                flags.append("colour range (not yuv420p/tv)")
            if au and I is not None and not (-15.5 <= I <= -12.5):
                flags.append(f"loudness {I} LUFS (target -14)")
            if au and TP is not None and TP > -0.9:
                flags.append(f"peak {TP}dBFS (target <= -1)")
            if flags:
                ok = False
            print(f"{f.name:40s} {size:>8s}  {spec}" + ("  FAIL " + ", ".join(flags) if flags else "  ok"))
        else:
            print(f"{f.name:40s} {size:>8s}")
    print("all outputs:\n" + "\n".join(f"  {f.resolve()}" for f in outs))
    if not ok:
        print("FAIL: spec problems above")
        sys.exit(1)


if __name__ == "__main__":
    main()
