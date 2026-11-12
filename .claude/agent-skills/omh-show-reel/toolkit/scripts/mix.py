# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/mix.py: cue placement, speech envelope and gain automation adapted to stdlib PCM.
# Full permission/warranty: ../LICENSE.upstream. Required tracks fail closed; no paid audio client.
"""Mix explicit local stereo PCM WAV inputs with speech-aware bed ducking and stems."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import wave

from new_project import no_links
from synth_music import audio_settings, place, write_wav
from timeline import number, read_spec

MODES = ("muted", "music-only", "narration", "narration+bed/SFX")


def read_wav(path, rate):
    try:
        with wave.open(str(no_links(path)), "rb") as source:
            if source.getnchannels() != 2 or source.getsampwidth() != 2 or source.getframerate() != rate or source.getcomptype() != "NONE":
                raise ValueError("HOLD: supply stereo 16-bit PCM WAV at the explicit sample rate; no implicit decoder/resampler")
            if source.getnframes() > 5_760_000:
                raise ValueError("input audio exceeds sample budget")
            count = source.getnframes()
            raw = source.readframes(count)
    except wave.Error as exc:
        raise ValueError(f"invalid WAV: {path}") from exc
    if len(raw) != count * 4:
        raise ValueError("truncated PCM data")
    pcm = array.array("h")
    pcm.frombytes(raw)
    if sys.byteorder != "little":
        pcm.byteswap()
    return array.array("f", (v / 32768 for v in pcm))


def asset(root, name):
    if not isinstance(name, str) or not name or "\\" in name or any(not re.fullmatch(r"[A-Za-z0-9._-]+", p) or p in (".", "..") for p in name.split("/")):
        raise ValueError("unsafe local audio path")
    root = no_links(root).resolve()
    path = no_links(root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("audio escapes explicit root")
    return path


def parse_loudnorm(text):
    chunks = re.findall(r"\{[^{}]+\}", text)
    for chunk in reversed(chunks):
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if all(k in data for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")):
            result = {k: float(data[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
            if not all(math.isfinite(v) for v in result.values()):
                raise ValueError("HOLD: loudnorm is nonfinite/unmeasured (including silence)")
            return result
    raise ValueError("HOLD: loudnorm measurements missing/unparseable")


def measure_loudness(path, ffmpeg, target=-14):
    result = subprocess.run([str(ffmpeg), "-nostdin", "-v", "info", "-i", str(path), "-af", f"loudnorm=I={target}:TP=-1:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True, check=True, timeout=120)
    return parse_loudnorm(result.stderr)


def mix(spec, root):
    duration, rate, count = audio_settings(spec)
    mode = spec["mode"]
    if mode not in MODES:
        raise ValueError("explicit supported audio mode required")
    empty = lambda: array.array("f", [0.]) * (2*count)
    voice, music, sfx = empty(), empty(), empty()
    if mode == "muted":
        if any(spec.get(k) for k in ("music", "narration", "sfx")):
            raise ValueError("muted mode cannot silently discard requested tracks")
        return empty(), {"narration": voice, "bed": music, "sfx": sfx}, {"mode": mode, "loudness": "not_applicable_muted", "buried_hits": []}
    required = ["music"] if mode == "music-only" else ["narration"] if mode == "narration" else ["narration", "music"]
    for key in required:
        if not isinstance(spec.get(key), dict) or not spec[key].get("file"):
            raise ValueError(f"HOLD: {mode} requires {key}")
    if mode == "music-only" and spec.get("narration") or mode == "narration" and (spec.get("music") or spec.get("sfx")):
        raise ValueError("audio mode contradicts requested tracks")
    # Load/validate every required/requested track before creating any output.
    tracks = {key: read_wav(asset(root, spec[key]["file"]), rate) for key in ("music", "narration") if spec.get(key)}
    effects = [(row, read_wav(asset(root, row["file"]), rate)) for row in spec.get("sfx", [])]
    for key, buffer in (("narration", voice), ("music", music)):
        if key in tracks:
            config = spec[key]
            at = number(config.get("start", 0), "track start", 0, duration)
            gain = 10**(number(config.get("gain_db", 0), "gain_db", -80, 12)/20)
            place(buffer, tracks[key], at, rate, gain)
    automation = spec.get("music", {}).get("automation", [])
    points = [(number(t, "automation time", 0, duration), number(db, "automation dB", -80, 12)) for t, db in automation]
    if any(b[0] <= a[0] for a, b in zip(points, points[1:])):
        raise ValueError("automation times must strictly increase")
    def gain_at(t):
        if not points:
            return 1
        if t <= points[0][0]:
            return 10**(points[0][1]/20)
        for a, b in zip(points, points[1:]):
            if t <= b[0]:
                return 10**((a[1]+(b[1]-a[1])*(t-a[0])/(b[0]-a[0]))/20)
        return 10**(points[-1][1]/20)
    placed = []
    for event, clip in effects:
        at = event.get("at")
        if isinstance(at, str):
            if at not in spec.get("cues", {}):
                raise ValueError("unknown sound cue")
            at = spec["cues"][at]
        at, gain = number(at, "SFX at", 0, duration), 10**(number(event.get("gain_db", -9), "SFX dB", -80, 12)/20)
        place(sfx, clip, at, rate, gain, event.get("align", "start"))
        frames = len(clip) // 2
        align = event.get("align", "start")
        offset = 0 if align == "start" else frames if align == "end" else max(range(frames), key=lambda i: abs(clip[2*i]) + abs(clip[2*i+1]))
        placed.append((at, event["file"], clip, gain, round(at * rate) - offset))
    hop = max(1, rate // 100)
    active = [max(abs(v) for v in voice[i:i+2*hop]) > 10**(-42/20) for i in range(0, len(voice), 2*hop)]
    envelope = 0.
    bed = empty()
    active_samples = 0
    duck_db = number(spec.get("duck_db", -12), "duck_db", -40, 0)
    for frame in range(count):
        # Closed input mask with deterministic lookahead; smoothing is computed anew per whole mix, not seeking state.
        target = float(any(active[frame//hop:min(len(active), frame//hop+6)]))
        envelope += (target-envelope) * (1-math.exp(-1/(rate*(.015 if target > envelope else .08))))
        duck = 1-envelope*(1-10**(duck_db/20))
        auto = gain_at(frame/rate)
        active_samples += int(active[frame//hop])
        for ch in (0, 1):
            index = 2*frame+ch
            bed[index] = music[index]*duck*auto
    buried = []
    window = max(1, round(rate * .1))
    def rms_db(buffer, first, last):
        values = buffer[2*first:2*last]
        power = sum(v*v for v in values) / len(values) if values else 0
        return 20*math.log10(math.sqrt(power)) if power > 0 else -math.inf
    for at, name, clip, gain, start in placed:
        # The window opens where the clip's first sample lands (same offset rule as place()).
        first, last = max(0, start), min(count, start + min(len(clip) // 2, window))
        if last <= first:
            continue
        hit = array.array("f", (v * gain for v in clip[2*(first-start):2*(last-start)]))
        sfx_db, bed_db = rms_db(hit, 0, last-first), rms_db(bed, first, last)
        if sfx_db < bed_db:
            buried.append({"at": at, "file": name, "sfx_db": round(sfx_db, 2), "bed_db": round(bed_db, 2)})
    ceiling = 10**(-1/20)
    output = array.array("f", (max(-ceiling, min(ceiling, v+b+s)) for v, b, s in zip(voice, bed, sfx)))
    peak = max(abs(v) for v in output)
    return output, {"narration": voice, "bed": bed, "sfx": sfx}, {"mode": mode, "speech_active_samples": active_samples, "sample_peak_dbfs": 20*math.log10(peak) if peak else None, "loudness": "not_measured", "listening": "not_observed", "buried_hits": buried}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path)
    parser.add_argument("--target-lufs", type=float, default=-14)
    args = parser.parse_args()
    spec = read_spec(args.spec)
    output, stems, report = mix(spec, args.spec.parent)
    targets = [args.out, args.out.with_suffix(".receipt.json"), *(args.out.with_name(args.out.stem+"_"+key+".wav") for key in stems)]
    for path in targets:
        no_links(path)
        if path.exists():
            raise FileExistsError("existing mix/stem/receipt preserved")
    write_wav(args.out, output, spec.get("sample_rate", 48000))
    for key, stem in stems.items():
        write_wav(args.out.with_name(args.out.stem+"_"+key+".wav"), stem, spec.get("sample_rate", 48000))
    if args.ffmpeg and spec["mode"] != "muted":
        report["loudness"] = measure_loudness(args.out, args.ffmpeg, number(args.target_lufs, "target LUFS", -30, -5))
    report.update(artifact_sha256=hashlib.sha256(args.out.read_bytes()).hexdigest(), limitations=["Sample limiter is not true-peak certification", "Post-AAC must be measured separately", "No listening/artistic approval"])
    args.out.with_suffix(".receipt.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
