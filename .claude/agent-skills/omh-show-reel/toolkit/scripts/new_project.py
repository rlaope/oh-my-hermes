# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/new_project.py: same folder layout and engine template; fonts are explicit local
# files (no font search/download), no npm setup, and an existing project is never touched.
# Full permission/warranty: ../LICENSE.upstream. Standalone, not an OMH import.
"""Initialize a NEW show-reel project: upstream folder layout, engine template and explicit fonts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct

from timeline import settings, system_alias

KIT = Path(__file__).resolve().parents[1]
ENGINE = KIT / "assets/engine"
FOLDERS = ("research", "assets/img", "assets/photos", "assets/gen", "assets/cutout", "assets/logo",
           "audio/vo", "audio/music", "audio/sfx", "reel/fonts", "qa", "out")
RATIOS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}
FONT_FORMATS = {".ttf": "truetype", ".otf": "opentype", ".woff": "woff", ".woff2": "woff2"}
SCENES_STUB = """/* Scene code. Write it fresh from the per-segment art direction in concept.md.
 * API examples live in _example_scenes.js (not loaded) and references/craft-engine.md. Do not start from the example screens.
 * For many segments split into scenes_s01.js ... and add each to index.html and to render_files in project.json. */
const { ease, prog, win, kf, spring, clamp, lerp, rand, noise, split, stagger, css, h, s, cue } = REEL;
REEL.config({ duration: %(dur)s, fps: %(fps)s, width: %(w)s, height: %(h)s, audio: null });
"""


def no_links(path, root=None):
    """Refuse a symlink at the root's own parent, the root, or any component below it.

    Without an explicit root the path's parent is the root. Components above it are the
    operator's own layout (macOS reaches every temp dir through `/var`), not this input.
    macOS's own /etc, /tmp and /var links are accepted wherever they fall (`system_alias`).
    """
    path = Path(path).absolute()
    root = Path(root).absolute() if root is not None else path.parent
    if path != root and root not in path.parents:
        raise ValueError(f"path escapes its root: {path}")
    chain = [root.parent, root, *(p for p in reversed(path.parents) if root in p.parents), path]
    for component in chain:
        if component.is_symlink() and not system_alias(component):
            raise ValueError(f"symlink input/destination refused: {component}")
    return path


def font_face(data, fallback):
    """Family and CSS weight read from an sfnt's name/fvar/OS-2 tables; unreadable keeps the stem and full range."""
    try:
        if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
            raise ValueError("not an sfnt")
        tables = {}
        for i in range(struct.unpack(">H", data[4:6])[0]):
            tag, _, offset, length = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
            tables[tag] = data[offset:offset + length]
        names = tables[b"name"]
        _, count, strings = struct.unpack(">HHH", names[:6])
        found = {}
        for i in range(count):
            platform, encoding, _, name_id, length, offset = struct.unpack(">6H", names[6 + 12 * i:18 + 12 * i])
            if name_id in (1, 16) and (platform, encoding) in ((3, 1), (3, 10), (0, 3), (0, 4)):
                found.setdefault(name_id, names[strings + offset:strings + offset + length].decode("utf-16-be"))
        family = (found.get(16) or found[1]).strip()
        weight = "100 900"
        if b"fvar" in tables:
            fvar = tables[b"fvar"]
            axes, axis_count, axis_size = struct.unpack(">H2xHH", fvar[4:12])
            for i in range(axis_count):
                tag, low, _, high = struct.unpack(">4siii", fvar[axes + i * axis_size:axes + i * axis_size + 16])
                if tag == b"wght":
                    weight = f"{round(low / 65536)} {round(high / 65536)}"
        elif b"OS/2" in tables:
            weight = str(struct.unpack(">H", tables[b"OS/2"][4:6])[0])
    except (KeyError, ValueError, struct.error, UnicodeDecodeError):
        return fallback, "100 900"
    if not family or len(family) > 64 or any(c in family for c in "\"\\<>{};,"):
        return fallback, weight
    return family, weight


def fonts_css(faces):
    lines = ["/* new_project.py writes this from the explicit --font files only. Use weights a face covers, or the browser fakes them. */"]
    for family, weight, name in faces:
        fmt = FONT_FORMATS[Path(name).suffix.lower()]
        lines.append(f'@font-face {{ font-family: {json.dumps(family)}; src: url("{name}") format("{fmt}"); font-weight: {weight}; font-display: block; }}')
    families = ", ".join(dict.fromkeys(json.dumps(f) for f, _, _ in faces))
    # Upstream tokens name Pretendard/Noto Serif KR/Anton/JetBrains Mono; these name the fonts actually supplied.
    lines.append(f":root {{ --display: {families}, sans-serif; --serif: {families}, serif; --num: {families}, sans-serif; --mono: {families}, monospace; }}")
    lines.append(f"#stage {{ font-family: {families}, sans-serif; }}")
    return "\n".join(lines) + "\n"


def initialize(destination, *, duration=60, fps=30, width=1920, height=1080, language="en", direction="ltr", fonts=(), assets=(), seed=7):
    config = settings(duration, fps, width, height)
    if direction not in ("ltr", "rtl") or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,34}", language):
        raise ValueError("explicit BCP47-like language and ltr/rtl direction required")
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 2**31 - 1:
        raise ValueError("seed must be an integer in [0, 2147483647]")
    destination = no_links(destination)
    if destination.exists():
        raise FileExistsError(f"preserving existing project: {destination}; select a new directory")
    if not fonts:
        raise ValueError("HOLD: supply explicit licensed local --font; no automatic font discovery/download")
    inputs = []
    seen = set()
    for source in (*fonts, *assets):
        path = no_links(source)
        if not path.is_file():
            raise FileNotFoundError(f"HOLD: local input missing: {path}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", path.name) or path.name.casefold() in seen or path.name == "fonts.css":
            raise ValueError("unsafe/colliding local asset name")
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("local asset exceeds 32 MiB limit")
        seen.add(path.name.casefold())
        inputs.append(path)
    for font in fonts:
        if Path(font).suffix.lower() not in FONT_FORMATS:
            raise ValueError("font must be explicit TTF/OTF/WOFF/WOFF2; font load validated by renderer")
    # Read/preflight every source before creating destination. No partial success on refusal.
    payloads = {"reel/" + name: (ENGINE / name).read_bytes() for name in ("engine.js", "fx.js", "index.html")}
    payloads["reel/_example_scenes.js"] = (ENGINE / "scenes.js").read_bytes()
    faces = []
    for font in fonts:
        data = Path(font).read_bytes()
        family, weight = font_face(data, re.sub(r"[^A-Za-z0-9]", "", Path(font).stem) or "ReelFont")
        payloads["reel/fonts/" + Path(font).name] = data
        faces.append((family, weight, Path(font).name))
    payloads.update({"assets/" + Path(a).name: Path(a).read_bytes() for a in assets})
    families = ",".join(dict.fromkeys(f for f, _, _ in faces))
    page = payloads["reel/index.html"].decode("utf-8")
    page = page.replace('<html lang="ko" data-fonts="Pretendard">', f'<html lang="{language}" dir="{direction}" data-fonts="{families}">', 1)
    payloads["reel/index.html"] = page.encode("utf-8")
    payloads["reel/fonts/fonts.css"] = fonts_css(faces).encode("utf-8")
    payloads["reel/scenes.js"] = (SCENES_STUB % {"dur": f"{config['duration']:g}", "fps": f"{config['fps']:g}", "w": config["width"], "h": config["height"]}).encode("utf-8")
    payloads["reel/timeline.js"] = b"window.TL = window.TL || { cues: {}, vo: [], scenes: [] };\n"
    config.update(language=language, direction=direction, seed=seed,
                  fonts=[{"family": family, "weight": weight, "file": "reel/fonts/" + name} for family, weight, name in faces],
                  audio_mode="muted", texts=[],
                  input_sha256={name: hashlib.sha256(data).hexdigest() for name, data in payloads.items() if name.startswith(("reel/fonts/", "assets/")) and not name.endswith(".css")})
    config["render_files"] = sorted([*(n for n in payloads if n != "reel/_example_scenes.js"), "project.json"])
    payloads["project.json"] = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    try:
        for folder in FOLDERS:
            (destination / folder).mkdir(parents=True, exist_ok=True)
        for name, data in payloads.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (destination / "timing.json").write_text(json.dumps({"duration": duration, "fps": fps, "cues": [{"id": "opening", "seconds": 0}]}, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError):
        shutil.rmtree(destination)
        raise
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--ratio", choices=sorted(RATIOS), help="sets width/height as upstream does (16:9 = 1920x1080)")
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--language", default="en")
    parser.add_argument("--direction", choices=("ltr", "rtl"), default="ltr")
    parser.add_argument("--font", action="append", type=Path, default=[])
    parser.add_argument("--asset", action="append", type=Path, default=[])
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    width, height = RATIOS[args.ratio] if args.ratio else (args.width, args.height)
    config = initialize(args.destination, duration=args.duration, fps=args.fps, width=width, height=height, language=args.language, direction=args.direction, fonts=args.font, assets=args.asset, seed=args.seed)
    print(json.dumps({"status": "initialized_not_rendered", **config}, ensure_ascii=False))


if __name__ == "__main__":
    main()
