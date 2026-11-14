# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/motion_check.py: native-cadence change-area profiles and intentional holds.
# Full permission/warranty: ../LICENSE.upstream. Metrics never certify artistic or flash safety.
"""Native-cadence movement/brightness diagnostics, not an artistic quality score."""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

from new_project import no_links
from timeline import number, read_spec


def _uncovered(start, end, holds):
    """Subtract the union of authored holds without exempting an entire run."""
    cursor = start
    for hold in holds:
        if hold[1] <= cursor:
            continue
        if hold[0] >= end:
            break
        if hold[0] > cursor:
            yield cursor, min(end, hold[0])
        cursor = max(cursor, hold[1])
    if cursor < end:
        yield cursor, end


def analyze_series(areas, lumas, *, fps, profile="general", holds=(), endcard=0):
    """Analyze one change-area interval per frame at ``fps`` (at most 600 s).

    Equal-length lumas are the mean luma of each interval's frame; the first
    brightness delta is unknown. An extra leading luma supplies that baseline
    (as used by the decoder and raw-frame wrapper). Holds subtract from still
    runs only, never from still_share. The tail is removed before all metrics.
    """
    fps = number(fps, "diagnostic fps", 1, 60)
    if profile not in ("general", "kinetic"):
        raise ValueError("profile must be general or kinetic")
    if not areas or len(areas) > 36000 or len(lumas) not in (len(areas), len(areas) + 1):
        raise ValueError("nonempty change areas and aligned lumas required, <=36000 intervals")
    duration = len(areas) / fps
    number(duration, "decoded seconds", 0, 600)
    areas = [number(a, "change area", 0, 1) for a in areas]
    lumas = [number(l, "mean luma", 0, 255) for l in lumas]
    endcard = number(endcard, "endcard seconds", 0, duration)
    seconds = duration - endcard
    if seconds <= 0:
        raise ValueError("endcard must leave a nonempty measurement interval")
    holds = list(holds)
    if len(holds) > 4096:
        raise ValueError("at most 4096 intentional holds")
    bounds = []
    for hold in holds:
        if not isinstance(hold, dict) or not {"start", "end", "reason"} <= hold.keys():
            raise ValueError("intentional hold needs start, end and reason")
        # A hold can include the leading baseline frame of a decoded clip.
        start = number(hold["start"], "hold start", 0, duration + 1 / fps)
        end = number(hold["end"], "hold end", 0, duration + 1 / fps)
        if end <= start or not isinstance(hold["reason"], str) or not hold["reason"].strip():
            raise ValueError("intentional hold needs ordered bounds and an authored reason")
        bounds.append((start, end))
    bounds.sort()
    count = min(len(areas), math.ceil(seconds * fps - 1e-9))
    extra_luma = len(lumas) == len(areas) + 1
    deltas = [lumas[i + 1] - lumas[i] for i in range(len(areas))] if extra_luma else [0.] + [b - a for a, b in zip(lumas, lumas[1:])]
    runs = []
    run_start = None
    still_seconds = high_seconds = area_seconds = 0.
    cuts = 0
    pairs = []
    pending = None
    for i in range(count):
        t = i / fps
        end = min((i + 1) / fps, seconds)
        weight = end - t
        area = areas[i]
        still = area < .015
        if still:
            still_seconds += weight
            if run_start is None:
                run_start = t
        elif run_start is not None:
            runs.append((run_start, t))
            run_start = None
        area_seconds += area * weight
        if area > .12:
            high_seconds += weight
        delta = deltas[i]
        if area > .45 and (abs(delta) > 18 or area > .6):
            cuts += 1
        if abs(delta) > 40:
            sign = 1 if delta > 0 else -1
            if pending is not None and sign != pending[1] and t - pending[0] <= 1:
                pairs.append((pending[0], t))
                pending = None  # Do not count the return as another flash's start.
            elif pending is None or t - pending[0] > 1:
                # Same-direction steps extend one excursion; retain its onset.
                pending = (t, sign)
    if run_start is not None:
        runs.append((run_start, seconds))
    maximum = left = 0
    for right, pair in enumerate(pairs):
        while left <= right and pair[1] - pairs[left][0] > 1:
            left += 1
        maximum = max(maximum, right - left + 1)
    limit = 1.0 if profile == "general" else .6
    issues = []
    longest = 0.
    for start, end in runs:
        for a, b in _uncovered(start, end, bounds):
            longest = max(longest, b - a)
            if b - a > limit + 1e-9:
                issues.append({"kind": "unannotated_stillness", "at": round(a, 9), "duration": round(b - a, 9)})
    still_share = still_seconds / seconds
    if profile == "kinetic" and still_share > .40 + 1e-9:
        issues.append({"kind": "still_share_exceeded", "actual": still_share, "maximum": .40})
    if maximum > 3:
        issues.append({"kind": "flash_review_required", "max_flashes_per_s": maximum})
    return {
        "verdict": "REVISE" if issues else "PASS", "profile": profile,
        "metrics": {"fps": fps, "seconds": seconds, "still_share": still_share,
                    "still_runs": [[round(a, 9), round(b - a, 9)] for a, b in runs if b - a >= .3 - 1e-9],
                    "longest_unannotated_still_s": round(longest, 9), "cuts_per_10s": cuts * 10 / seconds,
                    "max_flashes_per_s": maximum, "mean_change_area": area_seconds / seconds,
                    "high_motion_share": high_seconds / seconds},
        "issues": issues,
        "policy": {"fps": fps, "size": [320, 180], "luma_change_threshold": 24,
                   "still_change_area": .015, "max_unannotated_still_s": limit,
                   "max_still_share": .40 if profile == "kinetic" else None,
                   "cut_change_area": .45, "cut_luma_delta": 18, "cut_area_alone": .6,
                   "flash_luma_delta": 40, "max_flashes_per_s": 3,
                   "endcard_seconds": endcard, "intentional_holds": holds},
        "artistic": "not_observed",
        "limitations": ["Heuristic diagnostic only; not a quality/safety score or certification",
                        "320x180 luma change area is not optical flow; small motion and chromatic flashes may be missed",
                        "Native average cadence (capped at 60 fps); variable-frame-rate timing is approximated",
                        "Opposing mean-luma pairs are a review trigger, not a photosensitive-seizure safety test"],
    }


def analyze_frames(frames, *, fps=8, holds=()):
    """Compatibility wrapper: raw equal-size gray frames, general profile."""
    if len(frames) < 2 or len(frames) > 36001 or not frames[0] or any(len(f) != len(frames[0]) for f in frames):
        raise ValueError("at least two equal nonempty decoded frames required, <=36001")
    areas = [sum(abs(a - b) > 24 for a, b in zip(left, right)) / len(left) for left, right in zip(frames, frames[1:])]
    lumas = [sum(frame) / len(frame) for frame in frames]
    return analyze_series(areas, lumas, fps=fps, holds=holds)


def _artifact(path):
    path = no_links(path)
    if not path.is_file() or path.stat().st_size > 536_870_912:
        raise ValueError("regular motion artifact <=512 MiB required")
    return path


def _yavg(path, ffmpeg, filters):
    """ffmpeg does pixel arithmetic; only bounded scalar metadata enters Python."""
    result = subprocess.run([ffmpeg, "-v", "error", "-xerror", "-nostdin", "-i", str(path),
                             "-map", "0:v:0", "-an", "-sn", "-dn", "-t", "600", "-vf",
                             filters + ",signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
                             "-f", "null", "-"], capture_output=True, text=True, check=True, timeout=180)
    if len(result.stdout) > 8_388_608:
        raise ValueError("oversized motion metadata")
    values = [float(line.partition("=")[2]) for line in result.stdout.splitlines() if line.startswith("lavfi.signalstats.YAVG=")]
    if not values or len(values) > 36001:
        raise ValueError("missing or oversized decoded motion series")
    return values


def inspect(path, *, ffmpeg, ffprobe="ffprobe", profile="general", holds=(), endcard=0):
    path = _artifact(path)
    probe = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=avg_frame_rate,r_frame_rate,duration:format=duration", "-of", "json", str(path)],
                           capture_output=True, text=True, check=True, timeout=30)
    data = json.loads(probe.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise ValueError("video stream required")
    stream = streams[0]
    rate = stream.get("avg_frame_rate", "0/0")
    if rate in ("0/0", "0"):
        rate = stream.get("r_frame_rate", "0/0")
    native_fps = float(Fraction(rate))
    number(native_fps, "native fps", 1, 1000)
    number(float(stream.get("duration", data.get("format", {}).get("duration", "nan"))), "artifact seconds", 0, 600)
    fps = min(native_fps, 60.)
    # Preserve each native frame below the cap, including NTSC fractional rates.
    filters = ("fps=60," if native_fps > 60 else "") + "scale=320:180:flags=area,format=gray"
    lumas = _yavg(path, ffmpeg, filters)
    areas = [value / 255 for value in _yavg(path, ffmpeg, filters + ",tblend=all_mode=difference,lut=y='if(gt(val,24),255,0)'")]
    if len(lumas) != len(areas) + 1:
        raise ValueError("truncated or misaligned motion decode")
    report = analyze_series(areas, lumas, fps=fps, profile=profile, holds=holds, endcard=endcard)
    report["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--ffprobe")
    parser.add_argument("--profile", choices=("general", "kinetic"), default="general")
    parser.add_argument("--holds", type=Path)
    parser.add_argument("--endcard", type=float, default=0)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    sibling_probe = Path(args.ffmpeg).with_name("ffprobe" + (".exe" if Path(args.ffmpeg).suffix == ".exe" else ""))
    ffprobe = args.ffprobe or (str(sibling_probe) if sibling_probe.is_file() else shutil.which("ffprobe") or "ffprobe")
    holds = read_spec(args.holds, list) if args.holds else []
    report = inspect(args.artifact, ffmpeg=args.ffmpeg, ffprobe=ffprobe, profile=args.profile, holds=holds, endcard=args.endcard)
    if args.reference:
        # Compare like-for-like profile/tail policy, but never inherit target holds.
        reference = inspect(args.reference, ffmpeg=args.ffmpeg, ffprobe=ffprobe, profile=args.profile, endcard=args.endcard)
        report["reference"] = {"path": str(args.reference), "artifact_sha256": reference["artifact_sha256"], "metrics": reference["metrics"]}
    print(json.dumps(report, indent=2, allow_nan=False))
    raise SystemExit(0 if report["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
