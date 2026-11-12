# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/narrate.py: OPT-IN, run only by a user with their own ELEVENLABS_API_KEY (see eleven.py).
# script.json must name the voice and the language; there is no default voice. Messages in English.
# Full permission/warranty: ../LICENSE.upstream. OMH core never imports or runs this file.
"""Generate script.json's narration lines with ElevenLabs (character timestamps included) and check pronunciation with STT.

Opt-in: sends the narration text to ElevenLabs with your own ELEVENLABS_API_KEY; without it, exits 2 and sends nothing.

Usage
  narrate.py <project>/script.json [--stt] [--only n03,n07] [--force] [--workers 2] [--ffmpeg ffmpeg --ffprobe ffprobe]

script.json (the single source for narration and cues; timeline.py reads it too)
{
  "duration": 60,
  "voice": "<voice id chosen by voice_policy>", "language": "<BCP47 or ISO code of the narration>",
  "model": "eleven_multilingual_v2", "stt_language": "<optional STT language code>",
  "settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.4, "speed": 1.0},
  "lines": [
    {"id": "n01", "text": "<on-screen and subtitle text>",
              "tts": "<pronunciation text: numbers and abbreviations spelled out; defaults to text>",
              "at": 3.2,                                 <- time speech starts (s); otherwise previous line end + gap
              "cues": {"kbs": "<substring of tts>"},     <- the time that substring is spoken becomes a cue
              "takes": 3, "seed": 11, "model": "...", "settings": {...},  <- optional: several takes for proper nouns, STT picks
              "voice": "<other voice id>"}                                   <- optional: a different voice for this line only
  ],
  "sfx": [...], "music": {...}   <- used by timeline.py and the mix
}

Output: <project>/audio/vo/<id>.mp3, <id>.align.json, report.json
  --stt   transcribe each line with Scribe and score similarity against the expected sentence (text or tts, whichever
          is closer). Below 0.85 is FAIL: fix the wording or the phrasing breaks.
  takes   generate N seeds and keep the take with the best STT similarity as <id>.mp3 (others stay as <id>.t2.mp3 ...).
Only changed lines are regenerated (same text, voice, model, settings and seed are skipped). Use --only to save credits.
"""
import argparse
import difflib
import hashlib
import itertools
import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import eleven


def norm(s):
    s = s.lower()
    s = re.sub(r"\[[^\]]*\]", "", s)              # drop v3/v4 audio tags
    s = re.sub(r"[\s\.,!?·…'\"“”‘’()\-–—:;~]", "", s)
    return s


def similarity(stt_text, line):
    """STT mixes pronunciation and on-screen spellings (a number written as digits, an acronym as letters).
    Align the words of the on-screen and pronunciation texts and also compare every mix of the two per differing block."""
    text, say = line.get("text", ""), line.get("tts", "") or line.get("text", "")
    cands = [text, say] + line.get("alt", [])
    tw, sw = text.split(), say.split()
    blocks = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [norm(w) for w in tw], [norm(w) for w in sw]).get_opcodes():
        if op == "equal":
            blocks.append((" ".join(tw[i1:i2]),))
        elif i2 - i1 == j2 - j1:   # same word count: choose per word
            blocks += [(tw[i], sw[j]) for i, j in zip(range(i1, i2), range(j1, j2))]
        else:
            blocks.append((" ".join(tw[i1:i2]), " ".join(sw[j1:j2])))
    if 1 < len(blocks) <= 14:
        cands += [" ".join(c) for c in itertools.islice(itertools.product(*blocks), 4096)]
    got = norm(stt_text)
    return max(difflib.SequenceMatcher(None, got, norm(c)).ratio() for c in cands if c)


def digits_ok(stt_text, line):
    """One wrong digit changes the meaning (2026 -> 2025). Digits STT wrote must equal the on-screen digits exactly."""
    got = re.findall(r"\d+", stt_text.replace(",", ""))
    if not got:
        return True   # STT spelled the number out: judged by similarity only
    want = re.findall(r"\d+", (line.get("text", "") + " " + " ".join(line.get("alt", []))).replace(",", ""))
    return all(g in want for g in got)


def judge(stt_text, line):
    sim = similarity(stt_text, line)
    return sim, (sim >= 0.85 and digits_ok(stt_text, line))


def speech_span(al, dur):
    chars = al.get("characters") or []
    st = al.get("character_start_times_seconds") or []
    en = al.get("character_end_times_seconds") or []
    # punctuation characters stretch over the following silence, so only letters and digits bound the speech
    idx = [i for i, c in enumerate(chars) if c.isalnum()]
    if not idx:
        return 0.0, dur
    return float(st[idx[0]]), float(en[idx[-1]])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script")
    ap.add_argument("--stt", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe")
    a = ap.parse_args()
    eleven.TOOLS.update(ffmpeg=a.ffmpeg, ffprobe=a.ffprobe)
    if not eleven.api_key():
        print("FAIL ELEVENLABS_API_KEY is not set; nothing was sent.\n" + eleven.KEY_HELP, file=sys.stderr)
        sys.exit(2)

    sp = Path(a.script).resolve()
    proj = sp.parent
    cfg = json.loads(sp.read_text(encoding="utf-8"))
    lines = cfg["lines"]
    out = proj / "audio" / "vo"
    out.mkdir(parents=True, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None
    ids = [line["id"] for line in lines]
    if len(ids) != len(set(ids)):
        sys.exit("FAIL duplicate line ids")
    for line in lines:
        if not (line.get("tts") or line.get("text", "")).strip():
            sys.exit(f"FAIL {line['id']}: empty text")
        if not line.get("voice", cfg.get("voice")):
            print(f"FAIL {line['id']}: no voice; set script.json \"voice\" from the brief's voice_policy (there is no default)", file=sys.stderr)
            sys.exit(2)
        if not line.get("language", cfg.get("language")):
            print(f"FAIL {line['id']}: no language; set script.json \"language\" to the narration's content locale (there is no default)", file=sys.stderr)
            sys.exit(2)
    rep_path = out / "report.json"
    report = json.loads(rep_path.read_text(encoding="utf-8")) if rep_path.exists() else {}

    def job(i):
        line = lines[i]
        lid = line["id"]
        say = (line.get("tts") or line["text"]).strip()
        voice = line.get("voice", cfg.get("voice"))
        model = line.get("model", cfg.get("model", eleven.DEFAULT_MODEL))
        language = line.get("language", cfg.get("language"))
        settings = {**cfg.get("settings", {}), **line.get("settings", {})}
        seed = line.get("seed", cfg.get("seed"))
        takes = int(line.get("takes", 1))
        # context goes only between lines of the same voice, so another speaker's intonation never bleeds in
        same = [x for x in lines if x.get("voice", cfg.get("voice")) == voice]
        k = next(j for j, x in enumerate(same) if x["id"] == lid)
        prev_t = " ".join((x.get("tts") or x["text"]) for x in same[max(0, k - 2):k]) or None
        next_t = (same[k + 1].get("tts") or same[k + 1]["text"]) if k + 1 < len(same) else None
        sig = hashlib.sha1(json.dumps([say, voice, model, language, settings, seed, takes, a.stt], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
        mp3 = out / f"{lid}.mp3"
        if only is not None and lid not in only and mp3.exists():
            return lid, report.get(lid, {}), "skip"
        if not a.force and mp3.exists() and report.get(lid, {}).get("sig") == sig:
            r = report[lid]
            alf = mp3.with_suffix(".align.json")
            if alf.exists():   # recompute without credits if the alignment reading rule changed
                s0, s1 = speech_span(json.loads(alf.read_text(encoding="utf-8")), r.get("dur", 0))
                r.update({"speech_start": round(s0, 3), "speech_end": round(s1, 3),
                          "rate": round(r.get("chars", 0) / max(0.1, s1 - s0), 2)})
                if r.get("stt"):
                    sim, okv = judge(r["stt"], line)
                    r["sim"], r["ok"] = round(sim, 3), okv
            return lid, r, "skip"
        cands = []
        for k in range(takes):
            f = mp3 if k == 0 else out / f"{lid}.t{k + 1}.mp3"
            sd = (seed if seed is not None else 1000 + i * 17) + k if (takes > 1 or seed is not None) else None
            al = eleven.tts(say, f, voice=voice, model=model, settings=settings, seed=sd, previous_text=prev_t, next_text=next_t, language_code=language)
            dur = eleven.duration(f)
            s0, s1 = speech_span(al, dur)
            info = {"file": f.name, "seed": sd, "dur": round(dur, 3), "speech_start": round(s0, 3), "speech_end": round(s1, 3)}
            if a.stt or takes > 1:
                try:
                    st = eleven.stt(str(f), lang=cfg.get("stt_language"))
                    info["stt"] = st.get("text", "")
                    sim, okv = judge(info["stt"], line)
                    info["sim"], info["ok"] = round(sim, 3), okv
                except eleven.ElevenError as e:
                    info["stt"], info["sim"] = f"(STT failed: {e})", None
            cands.append((f, info))
        best_f, best = max(cands, key=lambda c: (bool(c[1].get("ok")), c[1].get("sim") or 0))
        if best_f != mp3:   # the most accurate take becomes the main file
            shutil.copy2(mp3, out / f"{lid}.t1.mp3")
            shutil.copy2(mp3.with_suffix(".align.json"), out / f"{lid}.t1.align.json")
            shutil.copy2(best_f, mp3)
            shutil.copy2(best_f.with_suffix(".align.json"), mp3.with_suffix(".align.json"))
            best = {**best, "file": mp3.name, "picked": best_f.name}
            cands[0] = (out / f"{lid}.t1.mp3", {**cands[0][1], "file": f"{lid}.t1.mp3"})   # the first take moved to t1
        chars = len(re.findall(r"\w", re.sub(r"\[[^\]]*\]", "", say)))   # letters and digits only (no punctuation or spaces)
        best = dict(best)   # copy so the take list never contains itself
        best.update({"sig": sig, "text": line["text"], "tts": say, "chars": chars,
                     "rate": round(chars / max(0.1, best["speech_end"] - best["speech_start"]), 2),
                     "takes": [dict(c[1]) for c in cands] if takes > 1 else None})
        return lid, best, "new"

    todo = list(range(len(lines)))
    try:
        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:   # concurrent TTS limit is 2-5 by plan; 2 is safe
            results = list(ex.map(job, todo))
    except eleven.ElevenError as e:
        print("FAIL " + str(e), file=sys.stderr)
        sys.exit(e.code)
    bad = []
    total_speech = 0.0
    total_chars = 0
    print(f"{'id':6s} {'state':5s} {'len':>6s} {'speech':>6s} {'ch/s':>5s} {'STT':>5s}  text")
    for lid, r, state in results:
        report[lid] = r
        sp_len = r.get("speech_end", 0) - r.get("speech_start", 0)
        total_speech += sp_len
        total_chars += r.get("chars", 0)
        sim = r.get("sim")
        okv = r.get("ok", sim is not None and sim >= 0.85)
        mark = "" if sim is None else (" ok" if okv else " FAIL")
        if sim is not None and not okv:
            bad.append(lid)
        print(f"{lid:6s} {state:5s} {r.get('dur', 0):6.2f} {sp_len:6.2f} {r.get('rate', 0):5.1f} {('' if sim is None else f'{sim:.2f}'):>5s}{mark} {r.get('text', '')}")
        if sim is not None and not okv:
            print(f"       STT: {r.get('stt')}")
    rep_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nspeech total {total_speech:.1f}s | {total_chars} characters (letters and digits only) | average {total_chars / max(0.1, total_speech):.1f} ch/s")
    if cfg.get("duration"):
        d = float(cfg["duration"])
        print(f"speech share of the {d:g}s target: {total_speech / d * 100:.0f}% (showreel 65-75% recommended, education 85-90%)")
    if bad:
        print(f"FAIL check pronunciation: {', '.join(bad)} -> try in order: phrasing breaks (commas, ellipses), spelled-out numbers and abbreviations, rewording, more takes, another model (v2 <-> v3)")
    print(f"-> next: python3 {Path(__file__).parent}/timeline.py {sp}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
