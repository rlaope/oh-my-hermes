# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/qa_check.py: local audio-mode-aware decode/measurements, no STT/client/hearing assumption.
# Full permission/warranty: ../LICENSE.upstream. Standalone, never imported by OMH core.
"""Strict local technical report; PASS means only the listed measured technical checks."""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from mix import MODES, measure_loudness
from new_project import no_links
from timeline import read_spec


def run_tool(command):
    result = subprocess.run([str(v) for v in command], capture_output=True, check=True, timeout=120)
    if len(result.stdout) + len(result.stderr) > 2_097_152:
        raise ValueError("tool diagnostic output limit exceeded")
    return result.stdout.decode("utf-8", errors="strict")


def decode_errors(command):
    """Run a decode and return its error text; a nonzero exit always yields text."""
    result = subprocess.run([str(v) for v in command], capture_output=True, check=False, timeout=300)
    text = result.stderr.decode("utf-8", errors="replace")[:65536].strip()
    return text or (f"decoder exited {result.returncode}" if result.returncode else "")


def inspect(artifact, *, audio_mode, ffprobe="ffprobe", ffmpeg="ffmpeg", policy=None):
    if audio_mode not in MODES:
        raise ValueError("explicit supported audio_mode required")
    report = {"verdict": "HOLD", "measurements": None, "checks": [], "audio_mode": audio_mode,
              "artistic": "not_observed", "playback": "not_observed", "listening": "not_observed", "native_language": "not_observed",
              "limitations": ["Technical evidence is not hearing, playback, artistic or accessibility certification", "No automatic STT or model/provider calls"], "artifact_sha256": None}
    try:
        path = no_links(artifact)
        if not path.is_file():
            raise ValueError("regular artifact file required")
        if path.stat().st_size > 536_870_912:
            raise ValueError("artifact exceeds 512 MiB inspection bound")
        report["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        probed = json.loads(run_tool([ffprobe, "-v", "error", "-count_frames", "-show_format", "-show_streams", "-of", "json", path]))
        video = next((s for s in probed["streams"] if s["codec_type"] == "video"), None)
        audio = next((s for s in probed["streams"] if s["codec_type"] == "audio"), None)
        if video is None:
            raise ValueError("missing video stream")
        duration = float(video.get("duration", probed["format"]["duration"]))
        fps = float(Fraction(video["avg_frame_rate"]))
        frames = int(video["nb_read_frames"])
        if not all(math.isfinite(v) and v > 0 for v in (duration, fps, frames)) or duration > 600 or fps > 60 or frames > 36000:
            raise ValueError("invalid/unbounded video duration/fps/frame observations")
        run_tool([ffmpeg, "-v", "error", "-xerror", "-nostdin", "-i", path, "-f", "null", "-"])
        measurements = {"duration": duration, "fps": fps, "frames": frames, "bytes": path.stat().st_size,
                        "width": video["width"], "height": video["height"], "codec": video["codec_name"],
                        "h264_level": video.get("level") if video["codec_name"] == "h264" and isinstance(video.get("level"), int) and video["level"] > 0 else None,
                        "color": {k: video.get(k) for k in ("color_range", "color_space", "color_transfer", "color_primaries")}}
        report["measurements"] = measurements
        report["checks"].append({"name": "full_decode", "status": "PASS"})
        failures = []
        if audio_mode == "muted":
            report["audio"] = "not_applicable_muted"
            if audio is not None:
                failures.append("muted mode contains undeclared audio")
        elif audio is None:
            report["audio"] = "required_audio_missing"
            failures.append("required audio stream missing")
        else:
            loudness = measure_loudness(path, ffmpeg)
            report["audio"] = {"sample_rate": int(audio["sample_rate"]), "codec": audio["codec_name"], "loudness": loudness}
            measurements.update(lufs=loudness["input_i"], true_peak=loudness["input_tp"])
        holds = []
        for key, expected in (policy or {}).items():
            actual = measurements.get(key)
            if key == "max_h264_level":
                level = measurements["h264_level"]
                if level is None or level > expected:
                    failures.append("max_h264_level")
            elif key == "hardware_decode":
                if expected is not True:
                    raise ValueError("hardware_decode policy must be true when present")
                if sys.platform != "darwin":
                    holds.append({"name": "hardware_decode", "status": "HOLD", "reason": "not observable on this host"})
                    continue
                errors = decode_errors([ffmpeg, "-v", "error", "-nostdin", "-hwaccel", "videotoolbox", "-i", path, "-f", "null", "-"])
                if errors:
                    failures.append("hardware_decode")
                    report["hardware_decode_errors"] = errors.splitlines()[:20]
                else:
                    report["checks"].append({"name": "hardware_decode", "status": "PASS"})
            elif key == "max_bytes":
                if measurements["bytes"] > expected:
                    failures.append("max_bytes")
            elif key == "lufs":
                if actual is None or abs(actual-expected) > 1:
                    failures.append("lufs outside +/-1")
            elif key == "true_peak":
                if actual is None or actual > expected:
                    failures.append("true_peak ceiling")
            elif actual is None or abs(actual-expected) > (1/fps if key == "duration" else 1e-6):
                failures.append(key)
        report["checks"].extend({"name": v, "status": "REVISE"} for v in failures)
        report["checks"].extend(holds)
        report["verdict"] = "REVISE" if failures else "HOLD" if holds else "PASS"
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError, subprocess.SubprocessError) as exc:
        report["measurements"] = None
        report["checks"].append({"name": "probe_decode_measure", "status": "HOLD", "reason": str(exc)})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--audio-mode", choices=MODES, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--policy", type=Path)
    args = parser.parse_args()
    report = inspect(args.artifact, audio_mode=args.audio_mode, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe, policy=read_spec(args.policy) if args.policy else None)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
