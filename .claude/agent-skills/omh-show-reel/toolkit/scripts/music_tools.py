# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/music_tools.py: messages in English, optional --ffmpeg/--ffprobe, outputs must be new,
# numpy imported only by the commands that analyze samples (plan/splice/fit run without it), and
# plan also reads synth_music.py's event keys (kind/at); gap writes 16-bit PCM, the only depth mix.py reads.
# Full permission/warranty: ../LICENSE.upstream. Standalone, not an OMH import.
"""Music tools: spec -> ElevenLabs composition plan, analysis of a generated track (tempo, hits, energy), length fitting.

Usage
  music_tools.py plan audio/music/spec.json [--out audio/music/plan.json]
      Builds an ElevenLabs Music composition_plan from the same spec synth_music.py reads (duration, mood, bpm, sections, events).
      -> eleven.py music audio/music/music.mp3 --plan audio/music/plan.json   (opt-in, your own key)
  music_tools.py analyze audio/music/music.mp3 [--out audio/music/analysis.json]      (needs numpy)
      Tempo, beats, downbeats, strong hits and a 0.5 s energy curve. ElevenLabs Music does not keep section lengths
      exactly (it usually converges on 4-bar phrases), so always analyze after generating and put scene boundaries on
      the real hits (timeline.py --music-analysis creates music.hitN and barN cues).
  music_tools.py splice in.mp3 out.wav --segments 0-3.9,7.78-19 [--snap analysis.json] [--xfade 0.006]
      Joins segments. When the generated drop arrives late, splice the drop a few beats after the end of the build-up
      to pull it to the time you want. --snap moves inner boundaries to the nearest beat. Cut at the same beat phase
      (for example bar start to bar start).
  music_tools.py fit in.mp3 out.wav --dur 60 [--fade 2.5]
      Within 6% length difference, fine-tunes the tempo (atempo); otherwise trims or pads, then fades the end. Source level -16 LUFS.
  music_tools.py gap in.wav out.wav 30-30.8[,103.2-103.97]                             (needs numpy)
      Cuts the music briefly for a silence beat.

sections[].energy (0..1) becomes words in the plan. sections[].style adds a direct description (English recommended).
To set the track's character outside the four moods (cinematic, pulse, soft, playful), use "global_styles": ["...", ...].
  global_styles then replace the mood's default words ("negative_styles" lists what to exclude) and energy words turn
  genre-neutral. "mood" stays for the synth_music.py fallback path.
Note: artist, composer or song names ("Hans Zimmer style" and the like) are rejected with 400 by the copyright filter.
  Describe genre, instruments and atmosphere only.
"""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

MOOD_STYLES = {
    "cinematic": (["epic cinematic trailer score", "hybrid orchestral with modern pulse synths", "big taiko and orchestral percussion",
                   "majestic, inspiring, premium brand film", "instrumental", "high production value"],
                  ["vocals", "singing", "lyrics", "rap", "lo-fi", "comedy", "acoustic guitar", "cheesy"]),
    "pulse": (["modern cinematic electronic", "tech keynote energy", "driving synth pulse and arpeggios", "precise, confident, inventive",
               "instrumental", "high production value"], ["vocals", "singing", "lyrics", "rap", "lo-fi", "acoustic guitar", "comedy"]),
    "soft": (["emotional cinematic piano and strings", "warm, intimate, hopeful", "gentle build", "instrumental"],
             ["vocals", "singing", "lyrics", "drums heavy", "EDM", "comedy"]),
    "playful": (["upbeat playful pop instrumental", "bright plucks, claps and bells", "bouncy groove", "cute and cheerful", "instrumental"],
                ["vocals", "singing", "lyrics", "dark", "horror", "heavy distortion"]),
}


ENERGY_WORDS = {   # words per energy step for each mood (so a tech mood never gets "full orchestra"); neutral is for global_styles
    "neutral": [["sparse and quiet", "minimal"], ["building tension"], ["driving", "full arrangement"], ["peak energy", "maximum energy"]],
    "cinematic": [["sparse and quiet", "minimal, atmospheric"], ["building tension", "restrained pulse"],
                  ["driving rhythm", "full arrangement"], ["epic climax", "powerful drums and full orchestra", "maximum energy"]],
    "pulse": [["sparse and quiet", "minimal synth texture"], ["building tension", "filtered pulse"],
              ["driving beat", "full arrangement"], ["peak energy", "big drop with punchy drums and bass", "maximum energy"]],
    "soft": [["sparse and quiet", "solo piano"], ["gentle build", "warm strings enter"],
             ["flowing", "full warm arrangement"], ["emotional peak", "soaring strings"]],
    "playful": [["light and sparse", "plucks only"], ["bouncy build", "claps enter"],
                ["groovy", "full bouncy arrangement"], ["peak energy", "big cheerful drop"]],
}


def numpy():
    try:
        import numpy as np
    except ModuleNotFoundError:
        raise SystemExit("HOLD: this command needs numpy in the interpreter you run it with; nothing is installed for you")
    return np


def new_output(path):
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise SystemExit(f"existing output refused: {path}; choose a new path")
    return path


def energy_words(e, mood="cinematic"):
    w = ENERGY_WORDS.get(mood, ENERGY_WORDS["cinematic"])
    return list(w[0 if e < 0.25 else 1 if e < 0.5 else 2 if e < 0.75 else 3])


def cmd_plan(a):
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    dur = float(spec["duration"])
    mood = spec.get("mood", "cinematic")
    if spec.get("global_styles"):          # the track character the concept chose; mood defaults are not used
        pos, neg = list(spec["global_styles"]), list(spec.get("negative_styles", ["vocals", "singing", "lyrics"]))
        ew = "neutral"
    else:
        pos, neg = MOOD_STYLES.get(mood, MOOD_STYLES["cinematic"])
        pos, neg = list(pos), list(neg) + list(spec.get("negative_styles", []))
        ew = mood
    if spec.get("bpm"):
        pos.append(f"{int(spec['bpm'])} BPM")
    if spec.get("key"):
        pos.append(f"{spec['key']} {'minor' if spec.get('minor', mood == 'cinematic') else 'major'}")
    pos += spec.get("styles", [])
    secs = sorted(spec.get("sections", [{"start": 0, "energy": 0.6}]), key=lambda s: s["start"])
    # Sections must be at least 3 s long (API). A short section merges into the previous one, which keeps its start and
    # name; energy takes the larger value and styles are joined. A short first section merges with the next one.
    def merge(a_, b_):
        m = dict(a_)
        m["energy"] = max(float(a_.get("energy", 0.5)), float(b_.get("energy", 0.5)))
        m["style"] = ", ".join(x for x in (a_.get("style"), b_.get("style")) if x)
        m["name"] = a_.get("name") or b_.get("name")
        return m
    merged = []
    for s in secs:
        s = dict(s)
        if merged and (s["start"] - merged[-1]["start"]) < 3.0:
            gap = s["start"] - merged[-1]["start"]
            if gap >= 1.8:   # keep a build-up -> drop structure by pushing the boundary to the 3 s mark (when 3 s remain after it)
                if dur - (merged[-1]["start"] + 3.0) >= 3.0:   # later sections get pushed by the same rule in turn
                    print(f"  . moved boundary of '{s.get('name', s['start'])}' {s['start']}s -> {merged[-1]['start'] + 3.0:.2f}s (3 s minimum section)"
                          " - after generating, read the real position with analyze and fix it with splice")
                    s["start"] = round(merged[-1]["start"] + 3.0, 3)
                    merged.append(s)
                    continue
            print(f"  . merged '{s.get('name', s['start'])}' ({s['start']}s): less than 3 s after the previous section")
            merged[-1] = merge(merged[-1], s)
            continue
        merged.append(s)
    while len(merged) > 1 and dur - merged[-1]["start"] < 3.0:
        last = merged.pop()
        print(f"  . merged the last section '{last.get('name', last['start'])}' into the previous one: shorter than 3 s")
        merged[-1] = merge(merged[-1], last)
    events = spec.get("events", [])
    if spec.get("bpm"):
        bar = 4 * 60 / float(spec["bpm"])
        off = [s for s in merged[1:] if abs(s["start"] / bar - round(s["start"] / bar)) > 0.1]
        if off:
            print(f"  ! sections not on a 4-bar ({bar * 4:.2f}s) or 1-bar ({bar:.3f}s) boundary: " + ", ".join(f"{s['start']}s" for s in off)
                  + " - music is usually generated in 4-bar units; check the real positions with analyze after generating")
    sections = []
    for i, s in enumerate(merged):
        st = s["start"]
        en = merged[i + 1]["start"] if i + 1 < len(merged) else dur
        local = energy_words(float(s.get("energy", 0.5)), ew) + ([s["style"]] if s.get("style") else [])
        lneg = []
        for ev in events:
            # OMH's synth_music.py spec writes events as {"kind", "at"}; upstream writes {"type", "t"}.
            ev = {**ev, "t": ev.get("t", ev.get("at")), "type": ev.get("type", ev.get("kind"))}
            t = float(ev["t"])
            if abs(t - st) < 0.4 and ev["type"] in ("hit", "boom", "braam"):
                local.append("starts immediately with a massive hit on the first beat")
                lneg += ["slow intro", "fade in"]
            elif st + 0.4 <= t < en - 0.2 and ev["type"] in ("hit", "boom", "braam"):
                local.append(f"a big hit about {t - st:.1f} seconds into this section")
            if ev["type"] == "stop" and st < t <= en + 0.01 and abs(t - en) < 1.5:
                local.append("ends abruptly in silence")
            # a riser belongs to this section when its end (t) is inside it or on its end boundary
            if ev["type"] == "riser" and st < t <= en + 0.4:
                local.append("rising tension into the next section")
        if i == len(merged) - 1:
            local.append(spec.get("ending", "final big hit then long reverb ring out"))
        sections.append({"section_name": s.get("name") or f"Part {i + 1}", "positive_local_styles": local,
                         "negative_local_styles": lneg, "duration_ms": int(round((en - st) * 1000)), "lines": []})
    diff = int(round(dur * 1000)) - sum(x["duration_ms"] for x in sections)
    sections[-1]["duration_ms"] += diff
    plan = {"model_id": spec.get("model_id", "music_v1"),
            "composition_plan": {"positive_global_styles": pos, "negative_global_styles": neg, "sections": sections}}
    # Energy curve check: one intensity held for long makes the generated track flat (a 2-minute track came out with 16-112 s at one level)
    span = [(float(m.get("energy", 0.5)), (merged[i + 1]["start"] if i + 1 < len(merged) else dur) - m["start"]) for i, m in enumerate(merged)]
    high = sum(d for e, d in span if e >= 0.75)
    if high > 0.5 * dur:
        print(f"  ! energy >= 0.75 covers {high:.0f}s ({high / dur * 100:.0f}%) - the track will be flat. Keep the climax (>= 0.9) within 25% of the total "
              "and add one breakdown that drops to 0.3-0.45 in the middle")
    if dur >= 45 and not any(e <= 0.45 for e, _ in span[1:-1]):
        print("  ! no section between the first and last drops to 0.45 or below - without a breath before a big hit the hit sounds weak")
    for x, y in zip(sections, sections[1:]):
        if x["positive_local_styles"][:2] == y["positive_local_styles"][:2] and not any(k in merged[sections.index(y)] for k in ("style",)):
            print(f"  ! '{x['section_name']}' and '{y['section_name']}' have the same description - write an instrument change in the later section's style"
                  " (for example 'strings drop out, only ticking pulse', 'add brass stabs and choir', 'half-time drums')")
    out = new_output(a.out if a.out else Path(a.spec).with_name("plan.json"))
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{out}: {len(sections)} sections | " + " | ".join(f"{x['section_name']} {x['duration_ms'] / 1000:.1f}s" for x in sections))


def decode(path, ffmpeg, sr=22050):
    np = numpy()
    raw = subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def _positive_number(value, label, *, zero=False):
    value = float(value)
    if not math.isfinite(value) or value < 0 or (not zero and value == 0):
        raise ValueError(f"{label} must be finite and {'nonnegative' if zero else 'positive'}")
    return value


def _alternatives(bpm):
    return [round(b, 2) for b in (bpm * 2, bpm / 2) if 60 <= b <= 200]


def _legacy_tempo(values, rate):
    """The original 60..180 BPM autocorrelation, interpolated and folded to 75..165."""
    mean = sum(values) / len(values)
    centered = [v - mean for v in values]
    first, last = max(1, math.ceil(rate / 3)), min(len(values) - 2, math.floor(rate))
    if first > last or not any(centered):
        return 120.0
    ac = {lag: sum(centered[i] * centered[i + lag] for i in range(len(values) - lag))
          for lag in range(max(0, first - 1), last + 2)}
    lag = max(range(first, last + 1), key=ac.__getitem__)
    y0, y1, y2 = ac[lag - 1], ac[lag], ac[lag + 1]
    den = y0 - 2 * y1 + y2
    refined = lag + (0.5 * (y0 - y2) / den if den else 0)
    bpm = 60 * rate / refined
    while bpm < 75:
        bpm *= 2
    while bpm > 165:
        bpm /= 2
    return bpm


def _phase_fit(values, rate, bpm):
    """Mean onset support on a grid; missing beats lower the score, not just its sum."""
    step = 60 * rate / bpm
    best, phase = -1.0, 0.0
    # Half-frame phase resolution; evaluate the grid rather than snap detected peaks.
    for k in range(max(1, math.ceil(2 * step))):
        p = k / 2
        total, count, t = 0.0, 0, p
        while t < len(values) - 0.5:
            total += values[int(t + 0.5)]
            count += 1
            t += step
        score = total / count if count else 0.0
        if score > best:
            best, phase = score, p / rate
    return max(0.0, best), phase


def fit_grid(envelope, frame_rate, *, bpm_hint=None, start=0, window=0):
    """Fit a periodic onset envelope, returning bpm, phase (seconds) and evidence.

    The hint limits the search to +/-8%, without octave folding. start/window select
    only the fitting stretch; phase remains relative to the original envelope's zero.
    grid_strength is baseline-subtracted onset support per predicted beat (0..1),
    not an artistic judgment or a probability that the meter is correct.
    """
    rate = _positive_number(frame_rate, "frame_rate")
    start = _positive_number(start, "start", zero=True)
    window = _positive_number(window, "window", zero=True)
    hint = _positive_number(bpm_hint, "bpm_hint") if bpm_hint is not None else None
    values = [float(v) for v in envelope]
    if not values or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("envelope must contain finite nonnegative samples")
    if start >= len(values) / rate:
        raise ValueError("start is outside the envelope")
    if hint is not None and hint * 1.08 > 60 * rate:
        raise ValueError("bpm_hint exceeds the envelope's frame resolution")
    lo = math.ceil(start * rate)
    hi = min(len(values), math.ceil((start + window) * rate)) if window else len(values)
    selected = values[lo:hi]
    if not selected:
        raise ValueError("fit window contains no frames")
    baseline = math.fsum(selected) / len(selected)
    # Rounding noise is not an onset: a flat envelope must leave no peaks on any
    # interpreter (float sum() rounds differently before Python 3.12).
    noise = 1e-9 * max(1.0, max(selected))
    evidence = [v - baseline if v - baseline > noise else 0.0 for v in selected]
    peaks = sorted(v for v in evidence if v > 0)
    scale = peaks[min(len(peaks) - 1, int(0.95 * len(peaks)))] if peaks else 1.0
    evidence = [min(1.0, v / scale) for v in evidence]
    legacy = _legacy_tempo(selected, rate)
    if hint is None:
        bpm = legacy
        score, phase = _phase_fit(evidence, rate, bpm)
    else:
        lower, upper = hint * 0.92, hint * 1.08
        # Coarse search followed by a centi-BPM refinement. The hint is one
        # candidate, not the answer: timing evidence chooses the result.
        step = max(0.05, (upper - lower) / 600)
        candidates = [lower + i * step for i in range(int((upper - lower) / step) + 1)] + [hint, upper]
        score, phase, bpm = -1.0, 0.0, hint
        if peaks:
            for candidate in candidates:
                strength, ph = _phase_fit(evidence, rate, candidate)
                if strength > score:
                    score, phase, bpm = strength, ph, candidate
            center = bpm
            for i in range(-10, 11):
                candidate = center + i * step / 10
                if lower <= candidate <= upper:
                    strength, ph = _phase_fit(evidence, rate, candidate)
                    if strength > score:
                        score, phase, bpm = strength, ph, candidate
        else:
            score = 0.0
    period = 60 / bpm
    result = {"bpm": bpm, "phase": (phase + lo / rate) % period,
              "grid_strength": max(0.0, min(1.0, score)), "alternatives": _alternatives(bpm)}
    if hint is not None and peaks:
        unconstrained, _ = _phase_fit(evidence, rate, legacy)
        if unconstrained > score * 1.5 and unconstrained - score > 0.15:
            result["warning"] = "tempo hint disagrees with the track"
    return result


def find_drops(rms, frame_rate, downbeats, bpm):
    """Rank up to three sustained loudness rises at downbeats, then return by time.

    rise is mean RMS in the following two bars / mean RMS in the preceding bar.
    Only full windows qualify. A local maximum prevents the lookahead window
    from labelling the bar *before* a rise as another drop. Bar numbers are 1-based.
    """
    rate = _positive_number(frame_rate, "frame_rate")
    bpm = _positive_number(bpm, "bpm")
    values = [float(v) for v in rms]
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("rms must contain finite nonnegative samples")
    times = [float(t) for t in downbeats]
    if any(not math.isfinite(t) or t < 0 for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("downbeats must be finite, nonnegative and strictly increasing")
    if not values:
        return []
    bar = 240 / bpm
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    candidates = []
    floor = max(max(values) * 0.01, 1e-12)
    for i, t in enumerate(times):
        left, mid, right = (round(s * rate) for s in (t - bar, t, t + 2 * bar))
        if left < 0 or right > len(values) or not left < mid < right:
            continue
        before = (prefix[mid] - prefix[left]) / (mid - left)
        after = (prefix[right] - prefix[mid]) / (right - mid)
        rise = after / max(before, floor)
        if rise >= 1.5 and after > floor:
            candidates.append({"t": round(t, 3), "rise": round(rise, 3), "bar": i + 1})
    selected = []
    for item in sorted(candidates, key=lambda d: (-d["rise"], d["t"])):
        if all(abs(item["t"] - d["t"]) > bar * 1.01 for d in selected):
            selected.append(item)
            if len(selected) == 3:
                break
    return sorted(selected, key=lambda d: d["t"])


def cmd_analyze(a):
    np = numpy()
    sr = 22050
    x = decode(a.file, a.ffmpeg, sr)
    n, h = 2048, 512
    fr = np.lib.stride_tricks.sliding_window_view(np.concatenate([x, np.zeros(n)]), n)[::h]
    S = np.abs(np.fft.rfft(fr * np.hanning(n), axis=1))
    flux = np.maximum(0, np.diff(np.log1p(10 * S), axis=0)).sum(1)
    flux = np.concatenate([[0], flux])
    flux /= np.percentile(flux, 99.5) + 1e-9
    ft = (np.arange(len(flux)) * h + n / 2) / sr          # window centre, not frame start (corrects a 0.046 s early bias)
    lowb = max(2, int(150 / (sr / n)))                     # below 150 Hz = kick and bass; beat phase comes from this band (not pulled by off-beat hats)
    lflux = np.maximum(0, np.diff(np.log1p(10 * S[:, :lowb]), axis=0)).sum(1)
    lflux = np.concatenate([[0], lflux])
    lflux /= np.percentile(lflux, 99.5) + 1e-9
    # tempo: flux autocorrelation (60-180 BPM)
    fl = flux - flux.mean()
    ac = np.correlate(fl, fl, mode="full")[len(fl) - 1:]
    lags = np.arange(len(ac)) * h / sr
    ok = (lags >= 60 / 180) & (lags <= 60 / 60)
    k0 = np.flatnonzero(ok)[np.argmax(ac[ok])]
    # parabolic interpolation, finer than one hop (23 ms)
    if 0 < k0 < len(ac) - 1:
        y0, y1, y2 = ac[k0 - 1], ac[k0], ac[k0 + 1]
        den = y0 - 2 * y1 + y2
        k0 = k0 + (0.5 * (y0 - y2) / den if den != 0 else 0)
    period = k0 * h / sr
    bpm = 60 / period
    while bpm < 75:
        bpm *= 2
    while bpm > 165:
        bpm /= 2
    period = 60 / bpm
    # phase: the phase with the largest flux sum on the beat grid
    best, ph_best = -1, 0
    for ph in np.arange(0, period, 0.005):
        idx = np.round((np.arange(ph, ft[-1], period) * sr - n / 2) / h).astype(int)
        idx = idx[(idx >= 0) & (idx < len(flux))]
        sc = (2.0 * lflux[idx] + flux[idx]).sum()
        if sc > best:
            best, ph_best = sc, ph
    hint = getattr(a, "bpm", None)
    start, window = getattr(a, "start", 0), getattr(a, "window", 0)
    grid = fit_grid(2 * lflux + flux if hint is not None else flux, sr / h,
                    bpm_hint=hint, start=start, window=window)
    if hint is not None or start or window:
        bpm = grid["bpm"]
        period = 60 / bpm
        ph_best = (grid["phase"] + n / (2 * sr)) % period
    beats = np.arange(ph_best, ft[-1], period)
    # downbeat: the one of four beats with the most low-band energy
    low = (S[:, : int(150 / (sr / n))] ** 2).sum(1)
    sc4 = []
    for k in range(4):
        idx = np.round((beats[k::4] * sr - n / 2) / h).astype(int)
        idx = idx[(idx >= 0) & (idx < len(low))]
        sc4.append(low[idx].mean() if len(idx) else 0)
    downbeats = beats[int(np.argmax(sc4))::4]
    # strong hits: flux peaks (top 3%, 0.25 s apart)
    thr = np.percentile(flux, 97)
    hits, last = [], -9
    w = int(0.08 * sr / h)
    for i in range(w, len(flux) - w):
        if flux[i] >= thr and flux[i] == flux[i - w:i + w].max() and ft[i] - last > 0.25:
            hits.append(round(float(ft[i]), 3))
            last = ft[i]
    rms = np.sqrt((fr ** 2).mean(1))
    hop_half = int(0.5 * sr / h)
    energy = [[round(i * h / sr, 2), round(float(20 * np.log10(rms[i:i + hop_half].mean() + 1e-9)), 1)] for i in range(0, len(rms), hop_half)]
    res = {"file": str(a.file), "duration": round(len(x) / sr, 3), "bpm": round(float(bpm), 2),
           "beats": [round(float(b), 3) for b in beats], "downbeats": [round(float(b), 3) for b in downbeats],
           "hits": hits, "energy": energy, "grid_strength": round(grid["grid_strength"], 4),
           "alternatives": _alternatives(bpm),
           "drops": find_drops(rms, sr / h, downbeats, bpm)}
    if "warning" in grid:
        res["warning"] = grid["warning"]
    out = new_output(a.out if a.out else Path(a.file).with_name("analysis.json"))
    out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"{out}\nlength {res['duration']}s | tempo {res['bpm']} BPM (beat {period:.3f}s, bar {period * 4:.3f}s) | first downbeat {downbeats[0] if len(downbeats) else 0:.2f}s")
    print("strong hits: " + ", ".join(f"{t:.2f}" for t in hits[:40]))
    top = max(e[1] for e in energy)
    print("energy (0.5 s, low..high): " + "".join(" .:-=+*#"[max(0, min(7, int((e[1] - top + 30) / 30 * 8)))] for e in energy))
    body = np.array([e[1] for e in energy if 5 <= e[0] <= res["duration"] - 5])
    if len(body) > 20:
        flat = float((body >= np.percentile(body, 95) - 3).mean())
        if flat > 0.6:
            print(f"! {flat * 100:.0f}% of the track is within 3 dB of its peak level - a flat track. Splice in a breathing section (cut in a quiet phrase), "
                  "make a silence with gap, or regenerate from a plan with stronger section contrast")


def cmd_splice(a):
    """Pick segments and join them: move a drop to the time you want, or remove 4 bars to fit the length."""
    segs = []
    for part in a.segments.split(","):
        x, y = part.split("-")
        segs.append([float(x), float(y)])
    if a.snap:
        an = json.loads(Path(a.snap).read_text(encoding="utf-8"))
        grid = an.get("beats") or []
        if grid:
            end = float(an.get("duration", 1e9))
            def snap(t):   # keep the very start (near 0 s) and end; only inner boundaries move to the nearest beat
                if t < 0.3 or t > end - 0.3:
                    return t
                g = min(grid, key=lambda b: abs(b - t))
                return float(g) if abs(g - t) < 0.25 else t
            segs = [[snap(x), snap(y)] for x, y in segs]
    xf = a.xfade
    filt = []
    for i, (x, y) in enumerate(segs):
        filt.append(f"[0:a]atrim={x:.4f}:{y:.4f},asetpts=PTS-STARTPTS[s{i}]")
    cur = "s0"
    for i in range(1, len(segs)):
        filt.append(f"[{cur}][s{i}]acrossfade=d={xf}:c1=tri:c2=tri[c{i}]")
        cur = f"c{i}"
    out = new_output(a.out)
    subprocess.run([a.ffmpeg, "-v", "error", "-nostdin", "-n", "-i", a.src, "-filter_complex", ";".join(filt), "-map", f"[{cur}]",
                    "-ar", "48000", "-ac", "2", str(out)], check=True)
    r = subprocess.run([a.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True)
    pos, lay = 0.0, []
    for x, y in segs:
        lay.append(f"source {x:.3f}-{y:.3f}s -> result {pos:.3f}s")
        pos += (y - x) - xf
    print(f"{out} {float(r.stdout):.3f}s\n  " + "\n  ".join(lay) + "\n-> analyze again and realign the scene boundaries")


def cmd_gap(a):
    """Cut only the music briefly (a silence beat). ElevenLabs Music often ignores a plan's stop, so make it here after generating.
    Fades out shortly into the start and reopens at the end (the first beat of the next phrase). Several: '103.2-103.97,30-30.8'."""
    np = numpy()
    sr = 48000
    raw = subprocess.run([a.ffmpeg, "-v", "error", "-nostdin", "-i", a.src, "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32).reshape(-1, 2).copy()
    t = np.arange(len(x)) / sr
    g = np.ones(len(x), np.float32)
    for part in a.ranges.split(","):
        s, e = (float(v) for v in part.split("-"))
        fo, fi = a.fade_out, a.fade_in
        m = (t >= s - fo) & (t < s)
        g[m] = np.minimum(g[m], (s - t[m]) / fo)
        g[(t >= s) & (t < e)] = 0
        m = (t >= e) & (t < e + fi)
        g[m] = np.minimum(g[m], (t[m] - e) / fi)
    x *= g[:, None]
    out = new_output(a.out)
    subprocess.run([a.ffmpeg, "-v", "error", "-nostdin", "-n", "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", "-", "-c:a", "pcm_s16le", str(out)],
                   input=x.tobytes(), check=True)
    print(f"{out}: silenced {a.ranges} (fade out {a.fade_out * 1000:.0f}ms, reopen {a.fade_in * 1000:.0f}ms)")


def cmd_fit(a):
    r = subprocess.run([a.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.src], capture_output=True, text=True, check=True)
    got = float(r.stdout.strip())
    want = a.dur
    tempo = got / want
    filt = []
    if abs(tempo - 1) <= 0.06 and abs(tempo - 1) > 0.004:
        filt.append(f"atempo={tempo:.5f}")
    filt += [f"apad=whole_dur={want:.3f}", f"atrim=0:{want:.3f}", f"afade=t=out:st={max(0, want - a.fade):.3f}:d={a.fade:.3f}",
             "loudnorm=I=-16:TP=-1.5:LRA=11"]
    out = new_output(a.out)
    subprocess.run([a.ffmpeg, "-v", "error", "-nostdin", "-n", "-i", a.src, "-af", ",".join(filt), "-ar", "48000", "-ac", "2", str(out)], check=True)
    print(f"{out}: {got:.2f}s -> {want:.2f}s ({'atempo ' + format(tempo, '.4f') if filt[0].startswith('atempo') else 'trim/pad'})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("plan"); p.add_argument("spec"); p.add_argument("--out"); p.set_defaults(fn=cmd_plan)
    p = sp.add_parser("analyze"); p.add_argument("file"); p.add_argument("--out"); p.set_defaults(fn=cmd_analyze)
    p.add_argument("--bpm", type=float, help="tempo hint; search within +/-8%% without octave folding")
    p.add_argument("--window", type=float, default=0, help="seconds to fit (0: to the end)")
    p.add_argument("--start", type=float, default=0, help="start of the fitting stretch, in seconds")
    p = sp.add_parser("splice"); p.add_argument("src"); p.add_argument("out"); p.add_argument("--segments", required=True)
    p.add_argument("--xfade", type=float, default=0.006); p.add_argument("--snap"); p.set_defaults(fn=cmd_splice)
    p = sp.add_parser("fit"); p.add_argument("src"); p.add_argument("out"); p.add_argument("--dur", type=float, required=True)
    p.add_argument("--fade", type=float, default=2.5); p.set_defaults(fn=cmd_fit)
    p = sp.add_parser("gap"); p.add_argument("src"); p.add_argument("out"); p.add_argument("ranges", help="start-end[,start-end...] seconds")
    p.add_argument("--fade-out", type=float, default=0.06); p.add_argument("--fade-in", type=float, default=0.03); p.set_defaults(fn=cmd_gap)
    a = ap.parse_args()
    try:
        a.fn(a)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"tool failed ({exc.returncode}): {' '.join(map(str, exc.cmd[:4]))} ...")


if __name__ == "__main__":
    main()
