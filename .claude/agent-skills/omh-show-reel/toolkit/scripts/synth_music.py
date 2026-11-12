# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/synth_music.py: selected seeded score/SFX concepts reimplemented with stdlib PCM.
# Full permission/warranty: ../LICENSE.upstream. No model, download, or paid-service call.
"""Modest deterministic local score/SFX fallback; not orchestral or listening approval."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import wave

from timeline import number, read_spec
from new_project import no_links


def audio_settings(spec):
    duration = number(spec["duration"], "duration", 1 / 60, 600)
    rate = spec.get("sample_rate", 48000)
    if rate not in (8000, 16000, 24000, 44100, 48000):
        raise ValueError("sample_rate must be 8000/16000/24000/44100/48000")
    count = round(duration * rate)
    if count > 5_760_000:
        raise ValueError("audio budget exceeds 5760000 stereo sample frames")
    return duration, rate, count


def write_wav(path, samples, rate):
    if not samples or len(samples) % 2 or any(not math.isfinite(v) for v in samples):
        raise ValueError("nonempty finite interleaved stereo PCM required")
    pcm = array.array("h", (round(max(-1, min(1, v)) * 32767) for v in samples))
    if sys.byteorder != "little":
        pcm.byteswap()
    with no_links(path).open("xb") as stream, wave.open(stream, "wb") as output:
        output.setparams((2, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(pcm.tobytes())


def place(buffer, clip, at, rate, gain=1, align="start"):
    if align not in ("start", "peak", "end"):
        raise ValueError("align must be start/peak/end")
    frames = len(clip) // 2
    offset = 0 if align == "start" else frames if align == "end" else max(range(frames), key=lambda i: abs(clip[2*i]) + abs(clip[2*i+1]))
    start = round(at * rate) - offset
    for i in range(max(0, -start), min(frames, len(buffer) // 2 - start)):
        for ch in (0, 1):
            buffer[2*(start+i)+ch] += clip[2*i+ch] * gain


def effect(kind, rate, seed=0, duration=.4):
    if kind not in ("tick", "boom", "whoosh"):
        raise ValueError("unknown local SFX kind")
    duration = .03 if kind == "tick" else number(duration, "SFX duration", .01, 8)
    rng = random.Random(seed)
    out = array.array("f")
    for i in range(max(1, round(rate * duration))):
        t = i / rate
        p = t / duration
        if kind == "tick":
            value = (.6 * math.cos(2*math.pi*2400*t) + .4 * rng.uniform(-1, 1)) * math.exp(-260*t)
            if i == 0:
                value = 1.0  # Explicit cue impulse; peak is anchored, not a guessed playback observation.
        elif kind == "boom":
            value = (.8 * math.sin(2*math.pi*(40*t + 10*(1-math.exp(-6*t)))) + .2 * rng.uniform(-1, 1)) * math.exp(-7*t)
        else:
            value = rng.uniform(-1, 1) * math.sin(math.pi*p)**2 * .5
        out.extend((value, value))
    return out


def synthesize(spec):
    duration, rate, count = audio_settings(spec)
    seed = spec.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("integer seed required")
    rng = random.Random(seed)
    score = array.array("f", [0.]) * (count * 2)
    sfx = array.array("f", [0.]) * (count * 2)
    sections = spec.get("sections", [])
    if not isinstance(sections, list) or len(sections) > 128:
        raise ValueError("<=128 score sections required")
    for section in sections:
        start = number(section["start"], "section start", 0, duration)
        end = number(section["end"], "section end", 0, duration)
        if end <= start:
            raise ValueError("empty/inverted score section")
        energy = number(section.get("energy", .5), "energy", 0, 1)
        bpm = number(section.get("bpm", 90), "bpm", 30, 240)
        notes = section.get("notes", [48, 55, 60])
        if not isinstance(notes, list) or not 1 <= len(notes) <= 8:
            raise ValueError("1..8 MIDI notes required")
        frequencies = [440 * 2**((number(n, "MIDI note", 24, 96)-69)/12) for n in notes]
        phases = [rng.random()*math.tau for _ in notes]
        for i in range(round(start*rate), min(count, round(end*rate))):
            t = i/rate-start
            envelope = min(1, t/.08, (end-start-t)/.15)
            pulse = math.exp(-((t*bpm/60) % 1)*5)
            for channel in (0, 1):
                pad = sum(math.sin(math.tau*f*t+phase+channel*.12) + .18*math.sin(math.tau*f*2*t+phase) for f, phase in zip(frequencies, phases)) / len(notes)
                score[2*i+channel] += pad*max(0, envelope)*energy*(.14+.12*pulse)
    events = spec.get("events", [])
    if not isinstance(events, list) or len(events) > 1024:
        raise ValueError("<=1024 events required")
    for i, event in enumerate(events):
        at = event["at"]
        if isinstance(at, str):
            if at not in spec.get("cues", {}):
                raise ValueError(f"unknown cue {at}")
            at = spec["cues"][at]
        at = number(at, "event cue", 0, duration)
        clip = effect(event["kind"], rate, seed+i, event.get("duration", .4))
        gain = 10**(number(event.get("gain_db", -9), "gain_db", -80, 0)/20)
        place(sfx, clip, at, rate, gain, event.get("align", "start"))
    combined = array.array("f", (max(-.89, min(.89, a+b)) for a, b in zip(score, sfx)))
    return combined, {"score": score, "sfx": sfx}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    spec = read_spec(args.spec)
    samples, stems = synthesize(spec)
    targets = [args.out, *(args.out.with_name(args.out.stem+"_"+key+".wav") for key in stems)]
    if any(p.exists() or p.is_symlink() for p in targets):
        raise FileExistsError("existing audio/stems preserved; choose new output")
    write_wav(args.out, samples, spec.get("sample_rate", 48000))
    for key, stem in stems.items():
        write_wav(args.out.with_name(args.out.stem+"_"+key+".wav"), stem, spec.get("sample_rate", 48000))
    print(json.dumps({"status": "generated_not_listened", "sample_frames": len(samples)//2, "sha256": hashlib.sha256(args.out.read_bytes()).hexdigest(), "stems": list(stems), "limitations": ["Local synthesis fallback, not artistic approval", "No LUFS or post-AAC measurement from PCM generation"]}))


if __name__ == "__main__":
    main()
