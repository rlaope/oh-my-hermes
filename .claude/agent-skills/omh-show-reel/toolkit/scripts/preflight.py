# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/preflight.py: local-only. It reports tools at the paths you pass and the presence of an
# opt-in key in the environment; it never calls a provider, installs, downloads or scans home fonts.
# Full permission/warranty: ../LICENSE.upstream. Standalone, not an OMH import.
"""Check the production environment before starting: what exists, what is missing, and which paths remain.

Usage: preflight.py [--browser /explicit/chrome-headless-shell] [--dependency-root /explicit/node_modules]
                    [--ffmpeg ffmpeg] [--ffprobe ffprobe] [--json]
Feed the "available paths" into the concept (no narration -> a concept told by music and picture; no provider music -> synthesized music).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--browser")
    ap.add_argument("--dependency-root")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows, fix, caps = [], [], {}

    def row(name, ok, info, how=None):
        rows.append(("ok" if ok else "missing", name, info))
        if not ok and how:
            fix.append(f"{name}: {how}")

    code, out = run(["node", "--version"])
    row("node", code == 0, out.splitlines()[0] if code == 0 else "not found", "install Node.js LTS yourself")
    code, out = run([a.ffmpeg, "-hide_banner", "-filters"])
    has_ff = code == 0
    flt = {f: (f" {f} " in out) for f in ("loudnorm", "ebur128", "tmix", "freezedetect", "signalstats", "zscale")}
    code_enc, enc = run([a.ffmpeg, "-hide_banner", "-encoders"])
    x264 = code_enc == 0 and " libx264 " in enc
    row("ffmpeg", has_ff and x264 and all(v for k, v in flt.items() if k != "zscale"),
        ("filters " + ", ".join(k for k, v in flt.items() if v) + (", libx264" if x264 else ", NO libx264")) if has_ff else "not found",
        "an FFmpeg with libx264 and loudnorm/ebur128/tmix/freezedetect/signalstats")
    if has_ff and not flt["zscale"]:
        row("ffmpeg zscale", False, "absent: render.mjs needs --color swscale (matrix/range conversion, as upstream)")
    code, out = run([a.ffprobe, "-version"])
    row("ffprobe", code == 0, out.splitlines()[0][:60] if code == 0 else "not found")
    browser = Path(a.browser) if a.browser else None
    row("browser", bool(browser and browser.is_file()), str(browser) if browser and browser.is_file() else "pass --browser /explicit/chrome-headless-shell",
        "pass the Chrome or chrome-headless-shell executable you already have")
    dep = Path(a.dependency_root) / "puppeteer-core" / "package.json" if a.dependency_root else None
    row("puppeteer-core", bool(dep and dep.is_file()), json.loads(dep.read_text())["version"] if dep and dep.is_file() else "pass --dependency-root /explicit/node_modules",
        "point --dependency-root at a node_modules that already holds puppeteer-core")
    try:
        import numpy  # noqa: F401
        row("python numpy", True, f"python {sys.version.split()[0]} (music_tools.py analyze/gap)")
    except ImportError:
        row("python numpy", False, "absent: music_tools.py analyze/gap unavailable", f"{sys.executable} -m pip install numpy (your call)")
    try:
        import PIL  # noqa: F401
        row("python Pillow", True, f"python {sys.version.split()[0]} (prep_images.py, labelled contact sheets)")
    except ImportError:
        row("python Pillow", False, "absent: prep_images.py and sheet labels unavailable", f"{sys.executable} -m pip install pillow (your call)")
    swift = bool(shutil.which("swiftc")) and sys.platform == "darwin"
    row("cutout (swiftc, macOS)", swift, "available" if swift else "unavailable: proceed without subject cutouts")
    codex = bool(shutil.which("codex"))
    row("codex CLI (opt-in images)", codex, "found on PATH" if codex else "not found: build visuals in code and from supplied photos")
    caps["image_gen"] = codex
    key = bool(os.environ.get("ELEVENLABS_API_KEY"))
    row("ELEVENLABS_API_KEY (opt-in)", key, "set (not validated; run eleven.py check yourself)" if key else "not set: no narration or provider music")
    caps.update(narration=key, music_api=key)

    if a.json:
        print(json.dumps({"rows": rows, "fix": fix, "caps": caps}, ensure_ascii=False, indent=1))
        return
    for ok, name, info in rows:
        print(f"{ok:7s} {name:28s} {info}")
    render_ok = all(r[0] == "ok" for r in rows if r[1] in ("node", "ffmpeg", "ffprobe", "browser", "puppeteer-core"))
    print("\nAvailable paths:")
    print(f"  rendering     {'possible' if render_ok else 'missing tools (see above)'}")
    print(f"  images        {'opt-in codex_ref_image.sh with your codex login' if caps['image_gen'] else 'code-drawn graphics, typography and supplied photos'}")
    print(f"  narration     {'opt-in eleven.py/narrate.py with your key' if caps['narration'] else 'none: music and captions version'}")
    print(f"  music         {'opt-in ElevenLabs Music, else synth_music.py' if caps['music_api'] else 'synth_music.py (local synthesis)'}")
    if fix:
        print("\nTo fix:")
        for f in fix:
            print("  - " + f)


if __name__ == "__main__":
    main()
