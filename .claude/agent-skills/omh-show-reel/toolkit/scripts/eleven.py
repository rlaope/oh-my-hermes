# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/eleven.py: OPT-IN provider client, run only by a user who invokes it with their own
# key. The key comes from ELEVENLABS_API_KEY in the environment only (no .env, home or config
# lookup) and reaches curl on stdin, never argv or logs. No default voice or language: the
# caller names both. curl runs with -q (no ~/.curlrc) and --form-string for values. Messages in English;
# optional --ffmpeg/--ffprobe (PATH names by default).
# Full permission/warranty: ../LICENSE.upstream. OMH core never imports or runs this file.
"""ElevenLabs helper (TTS, STT, sound effects, music, voice lookup, key check). narrate.py imports it too.

Opt-in: nothing in OMH runs this. It talks to api.elevenlabs.io only when you run it, with your own
ELEVENLABS_API_KEY exported in the shell. Without the key it exits 2 and sends nothing.

Why curl: python.org builds of Python often fail TLS verification with urllib because of their
certificate store. Verification stays on; curl follows the system certificates and proxy settings.
The key is passed only on curl's standard input (never in files, argv or temporary folders).

Usage
  eleven.py check --voice VOICE_ID                       key, voice, models and plan check (run first)
  eleven.py voices [--lang LANG] [--library] [--q QUERY] voices you can use (--library: search the public library)
  eleven.py tts "text" out.mp3 --voice VOICE_ID [--language LANG] [--model eleven_multilingual_v2]
                [--stability .45] [--similarity .8] [--style .4] [--speed 1.0] [--seed N] [--timestamps]
  eleven.py stt audio.mp3 [--lang LANG] [--json out.json]          Scribe transcription
  eleven.py sfx "prompt" out.mp3 [--dur 2.0] [--influence 0.5] [--loop]
  eleven.py sfx-kit <outdir> --names impact,whoosh,riser [--presets presets.json]   preset SFX in bulk (missing ones only)
  eleven.py music out.mp3 (--plan plan.json | --prompt "..." --length 60) [--model music_v1] [--seed N]

Voice and language follow the brief's voice_policy and content locale; this tool never picks one.

Exit codes: 0 success, 2 no key, 3 invalid key or missing permission, 4 paid plan needed, 5 request error, 6 network
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

API = "https://api.elevenlabs.io"
DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_SETTINGS = {"stability": 0.45, "similarity_boost": 0.8, "style": 0.4, "use_speaker_boost": True, "speed": 1.0}
KIT = Path(__file__).resolve().parent.parent
TOOLS = {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"}

KEY_HELP = """This opt-in tool needs your own ElevenLabs API key in the environment:
  1) Sign in at https://elevenlabs.io -> Developers (or profile) -> API Keys -> Create API Key.
  2) Permissions: Text to Speech, Speech to Text, Sound Effects, Music, Voices (Read), User (Read)
     (User Read lets `check` show remaining credits). The key is shown once; copy it then.
  3) Export ELEVENLABS_API_KEY in the shell you run this from. Nothing else is read: no .env, home or config file.
  Plans: Free has 10k credits a month, no commercial use, no library voices and no Music API.
         Starter and above allow library voices and commercial use; Music needs a paid plan."""


class ElevenError(Exception):
    def __init__(self, msg, code=5, status=None, body=None):
        super().__init__(msg)
        self.code, self.status, self.body = code, status, body


def api_key():
    k = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    return k or None


def _explain(status, body):
    try:
        d = json.loads(body)
        det = d.get("detail", d)
        if isinstance(det, dict):
            st, msg = det.get("status", ""), det.get("message", "")
        else:
            st, msg = "", str(det)
    except (ValueError, AttributeError, TypeError):
        st, msg = "", body[:300].decode("utf-8", "replace") if isinstance(body, bytes) else str(body)[:300]
    if status == 401:
        if "missing_permissions" in st or "permission" in msg:
            return ElevenError(f"the API key lacks a permission ({msg}). Enable it on the key in the ElevenLabs dashboard or create a new key.", 3, status, body)
        return ElevenError("the API key is not valid.\n" + KEY_HELP, 3, status, body)
    if status == 402:
        return ElevenError(f"this feature needs a paid plan ({msg or st}). Library voices and the Music API are blocked on Free.", 4, status, body)
    if status == 403:
        return ElevenError(f"plan limit ({msg or st}). For example 192 kbps output needs Creator or above.", 4, status, body)
    return ElevenError(f"HTTP {status}: {st} {msg}", 5, status, body)


def redact(text, key):
    """Never echo the key: a user's curl config or proxy could put headers on stderr."""
    return text.replace(key, "[redacted]") if key else text


def request(method, path, body=None, form=None, files=None, accept_audio=False, timeout=300, retries=6):
    """Call ElevenLabs and return the response bytes. 429, 5xx and network errors retry with growing waits."""
    key = api_key()
    if not key:
        raise ElevenError("ELEVENLABS_API_KEY is not set; nothing was sent.\n" + KEY_HELP, 2)
    # The key never goes into a file or argv: only curl's stdin (-H @-). The body (not secret) is an argument, so no temp file.
    # -q first: ignore ~/.curlrc, so no user config can turn on verbose/trace and print the key header.
    cmd = ["curl", "-q", "-sS", "-X", method, API + path, "-H", "@-", "--max-time", str(timeout), "-w", "\n%{http_code}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", json.dumps(body, ensure_ascii=False)]
    for k, v in (form or {}).items():   # literal values: a leading @ or < never makes curl read a file
        cmd += ["--form-string", f"{k}={v}"]
    for k, v in (files or {}).items():  # the only file uploads, named by this script
        cmd += ["-F", f"{k}=@{v}"]
    hdr = f"xi-api-key: {key}\n".encode()
    last = None
    for attempt in range(retries):
        r = subprocess.run(cmd, input=hdr, capture_output=True)
        if r.returncode != 0:
            last = ElevenError(f"network error: {redact(r.stderr.decode('utf-8', 'replace'), key)[:300]}", 6)
            time.sleep(min(30, 3 * (attempt + 1)))
            continue
        out, _, code = r.stdout.rpartition(b"\n")
        status = int(code or 0)
        if status == 200:
            if accept_audio and (out[:1] == b"{" or len(out) < 800):
                # keep an error JSON from being saved as an audio file (empty-text TTS returns 200 and a silent mp3)
                raise ElevenError(f"abnormal audio response ({len(out)}B): {out[:200]!r}", 5, status, out)
            return out
        if status == 429 or status >= 500:
            last = _explain(status, out)
            wait = min(60, 4 * 2 ** attempt)
            print(f"  ... {status} retry {attempt + 1}/{retries} (waiting {wait}s)", file=sys.stderr)
            time.sleep(wait)
            continue
        raise _explain(status, out)
    raise last or ElevenError("retries exhausted", 5)


def tts(text, out, voice, model=DEFAULT_MODEL, settings=None, seed=None,
        previous_text=None, next_text=None, timestamps=True, language_code=None, fmt="mp3_44100_192"):
    """Save an mp3. With timestamps=True, also <name>.align.json (character alignment) next to it; returns the alignment dict."""
    if not voice:
        raise ElevenError("name a voice explicitly (voice_policy); this tool has no default voice", 5)
    if not text or not text.strip():
        raise ElevenError("empty text is never sent (ElevenLabs returns 200 and a silent mp3)", 5)
    vs = {**DEFAULT_SETTINGS, **(settings or {})}
    if model.startswith("eleven_v3") or model.startswith("eleven_v4"):
        vs = {k: v for k, v in vs.items() if k in ("stability", "similarity_boost")}   # v3/v4 take no style or speed
    body = {"text": text, "model_id": model, "voice_settings": vs}
    if language_code:
        body["language_code"] = language_code
    if seed is not None:
        body["seed"] = int(seed)
    if not model.startswith("eleven_v3"):   # v3 takes no previous/next_text
        if previous_text:
            body["previous_text"] = previous_text
        if next_text:
            body["next_text"] = next_text
    ep = "/with-timestamps" if timestamps else ""
    for f in (fmt, "mp3_44100_128"):
        try:
            raw = request("POST", f"/v1/text-to-speech/{voice}{ep}?output_format={f}", body=body, accept_audio=not timestamps)
            break
        except ElevenError as e:
            if e.status == 403 and f != "mp3_44100_128":
                print("  ... plan blocks 192 kbps; asking again at 128 kbps", file=sys.stderr)
                continue
            raise
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    if timestamps:
        d = json.loads(raw)
        audio = base64.b64decode(d["audio_base64"])
        if len(audio) < 800:
            raise ElevenError("the audio is empty", 5)
        Path(out).write_bytes(audio)
        al = d.get("alignment") or d.get("normalized_alignment") or {}   # normalized_alignment romanizes some scripts; alignment first
        Path(out).with_suffix(".align.json").write_text(json.dumps(al, ensure_ascii=False), encoding="utf-8")
        return al
    Path(out).write_bytes(raw)
    return None


def stt(path, lang=None, words=True, model="scribe_v1"):
    form = {"model_id": model}
    if lang:
        form["language_code"] = lang
    if words:
        form["timestamps_granularity"] = "word"
    return json.loads(request("POST", "/v1/speech-to-text", form=form, files={"file": path}, timeout=300))


def sfx(text, out, dur=None, influence=0.5, loop=False, fmt="mp3_44100_128"):
    body = {"text": text, "model_id": "eleven_text_to_sound_v2", "prompt_influence": influence}
    if dur is not None:
        body["duration_seconds"] = max(0.5, min(30.0, float(dur)))   # allowed range 0.5-30 s
    if loop:
        body["loop"] = True
    raw = request("POST", f"/v1/sound-generation?output_format={fmt}", body=body, accept_audio=True)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(raw)


def music(out, plan=None, prompt=None, length_s=None, model="music_v1", seed=None, fmt="mp3_44100_192"):
    if plan is not None:
        body = {"composition_plan": plan, "model_id": model}
    else:
        body = {"prompt": prompt, "music_length_ms": int(max(3, length_s) * 1000), "model_id": model, "force_instrumental": True}
    if seed is not None and plan is None:   # --prompt together with seed returned 422 (2026-10 comparison)
        print("  ! --seed only goes with --plan; it is dropped for --prompt generation", file=sys.stderr)
        seed = None
    if seed is not None:
        body["seed"] = int(seed)
    for f in (fmt, "mp3_44100_128"):
        try:
            raw = request("POST", f"/v1/music?output_format={f}", body=body, accept_audio=True, timeout=900, retries=5)
            break
        except ElevenError as e:
            if e.status == 403 and f != "mp3_44100_128":
                continue
            if e.status in (400, 422) and e.body:
                try:
                    det = json.loads(e.body).get("detail", {})
                    sug = (det.get("data") or {}).get("prompt_suggestion") or (det.get("data") or {}).get("composition_plan_suggestion")
                    if sug:
                        print("rejected (artist/track names or similar copyrighted wording). Suggestion:\n" + json.dumps(sug, ensure_ascii=False, indent=1), file=sys.stderr)
                except (ValueError, AttributeError, TypeError):
                    pass
            raise
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(raw)


def peak_db(path):
    r = subprocess.run([TOOLS["ffmpeg"], "-v", "info", "-nostdin", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "max_volume" in line:
            return float(line.split("max_volume:")[1].split("dB")[0])
    return -99.0


def duration(path):
    r = subprocess.run([TOOLS["ffprobe"], "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def cmd_check(a):
    if not api_key():
        print("FAIL ELEVENLABS_API_KEY is not set; nothing was sent.\n" + KEY_HELP)
        return 2
    rep = {"key": "set"}
    try:
        models = json.loads(request("GET", "/v1/models", retries=2))
        rep["tts_models"] = [m["model_id"] for m in models if m.get("can_do_text_to_speech")]
    except ElevenError as e:
        print("FAIL key check: " + str(e))
        return e.code
    try:
        v = json.loads(request("GET", f"/v1/voices/{a.voice}", retries=2))
        rep["voice"] = {"id": a.voice, "name": v.get("name"), "category": v.get("category"), "labels": v.get("labels"),
                        "fine_tuned_models": [k for k, s in (v.get("fine_tuning", {}).get("state") or {}).items() if s == "fine_tuned"]}
    except ElevenError as e:
        rep["voice"] = f"lookup failed: {e}"
    try:
        s = json.loads(request("GET", "/v1/user/subscription", retries=1))
        rep["plan"] = {"tier": s.get("tier"), "used": s.get("character_count"), "limit": s.get("character_limit"),
                       "remaining": (s.get("character_limit") or 0) - (s.get("character_count") or 0)}
    except ElevenError as e:
        rep["plan"] = "unknown (the key has no User Read permission); see credits in the dashboard" if e.status == 401 else str(e)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    if isinstance(rep["voice"], str):
        print("Note: this voice is unavailable. Free plans block library voices; upgrade the plan or pick another voice with `eleven.py voices`.")
        return 4
    return 0


def cmd_voices(a):
    if a.library:
        q = "/v1/shared-voices?page_size=50" + (f"&language={a.lang}" if a.lang else "") + (f"&search={a.q}" if a.q else "")
        d = json.loads(request("GET", q))
        for v in d.get("voices", []):
            print(f"{v.get('voice_id')}  {v.get('name')[:40]:40s} {v.get('gender','')}/{v.get('age','')} {v.get('accent','')} {v.get('use_case','')}  {str(v.get('descriptive',''))}")
        return 0
    d = json.loads(request("GET", "/v2/voices?page_size=100" + (f"&search={a.q}" if a.q else "")))
    for v in d.get("voices", []):
        lab = v.get("labels") or {}
        langs = {lab.get("language", "")} | {x.get("language") for x in (v.get("verified_languages") or [])}
        if a.lang and a.lang not in langs:
            continue
        print(f"{v['voice_id']}  {v['name'][:44]:44s} {v.get('category',''):12s} {lab.get('gender','')}/{lab.get('age','')} {lab.get('accent','')} {lab.get('descriptive','')}")
    return 0


def cmd_tts(a):
    st = {k: v for k, v in {"stability": a.stability, "similarity_boost": a.similarity, "style": a.style, "speed": a.speed}.items() if v is not None}
    tts(a.text, a.out, voice=a.voice, model=a.model, settings=st, seed=a.seed, timestamps=a.timestamps, language_code=a.language)
    print(f"{a.out} {duration(a.out):.2f}s")
    return 0


def cmd_stt(a):
    d = stt(a.file, lang=a.lang)
    if a.json:
        Path(a.json).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(d.get("text", ""))
    return 0


def load_presets(path=None):
    p = Path(path) if path else KIT / "assets" / "sfx_presets.json"
    return {x["name"]: x for x in json.loads(p.read_text(encoding="utf-8"))}


def cmd_sfx(a):
    sfx(a.text, a.out, dur=a.dur, influence=a.influence, loop=a.loop)
    pk = peak_db(a.out)
    print(f"{a.out} {duration(a.out):.2f}s peak {pk:.1f}dB")
    if pk <= -24:   # it sometimes generates near-silence (same bar as sfx-kit)
        print(f"FAIL near silence (peak {pk:.1f}dB): change the prompt and generate again", file=sys.stderr)
        return 2
    return 0


def cmd_sfx_kit(a):
    from concurrent.futures import ThreadPoolExecutor
    presets = load_presets(a.presets)
    names = [n.strip() for n in a.names.split(",")] if a.names else list(presets)
    unknown = [n for n in names if n not in presets]
    if unknown:
        print("names not in the presets: " + ", ".join(unknown) + "\navailable: " + ", ".join(presets))
        return 5
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)

    def one(n):
        p = presets[n]
        f = out / f"{n}.mp3"
        if f.exists() and f.stat().st_size > 2000:
            return f"{n}: exists"
        for attempt in range(3):
            sfx(p["prompt"] + (", close microphone, punchy, loud" if attempt else ""), f, dur=p.get("dur"),
                influence=min(0.9, p.get("influence", 0.5) + 0.15 * attempt), loop=p.get("loop", False))
            pk = peak_db(f)
            if pk > -24:          # near-silence happens; generate again
                return f"{n}: {duration(f):.2f}s peak {pk:.1f}dB"
        return f"{n}: too quiet (peak {pk:.1f}dB); raise its gain in the mix"

    with ThreadPoolExecutor(max_workers=3) as ex:   # stay under the plan's concurrent request limit (2-5)
        for line in ex.map(one, names):
            print(line)
    return 0


def cmd_music(a):
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8")) if a.plan else None
    if plan and "composition_plan" in plan:
        model = plan.get("model_id", a.model)
        plan = plan["composition_plan"]
    else:
        model = a.model
    music(a.out, plan=plan, prompt=a.prompt, length_s=a.length, model=model, seed=a.seed)
    print(f"{a.out} {duration(a.out):.2f}s")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("check"); p.add_argument("--voice", required=True); p.set_defaults(fn=cmd_check)
    p = sp.add_parser("voices"); p.add_argument("--lang"); p.add_argument("--q"); p.add_argument("--library", action="store_true"); p.set_defaults(fn=cmd_voices)
    p = sp.add_parser("tts"); p.add_argument("text"); p.add_argument("out"); p.add_argument("--voice", required=True)
    p.add_argument("--language"); p.add_argument("--model", default=DEFAULT_MODEL); p.add_argument("--stability", type=float)
    p.add_argument("--similarity", type=float); p.add_argument("--style", type=float); p.add_argument("--speed", type=float)
    p.add_argument("--seed", type=int); p.add_argument("--timestamps", action="store_true"); p.set_defaults(fn=cmd_tts)
    p = sp.add_parser("stt"); p.add_argument("file"); p.add_argument("--lang"); p.add_argument("--json"); p.set_defaults(fn=cmd_stt)
    p = sp.add_parser("sfx"); p.add_argument("text"); p.add_argument("out"); p.add_argument("--dur", type=float)
    p.add_argument("--influence", type=float, default=0.5); p.add_argument("--loop", action="store_true"); p.set_defaults(fn=cmd_sfx)
    p = sp.add_parser("sfx-kit"); p.add_argument("outdir"); p.add_argument("--names"); p.add_argument("--presets"); p.set_defaults(fn=cmd_sfx_kit)
    p = sp.add_parser("music"); p.add_argument("out"); p.add_argument("--plan"); p.add_argument("--prompt"); p.add_argument("--length", type=float, default=60)
    p.add_argument("--model", default="music_v1"); p.add_argument("--seed", type=int); p.set_defaults(fn=cmd_music)
    a = ap.parse_args()
    TOOLS.update(ffmpeg=a.ffmpeg, ffprobe=a.ffprobe)
    try:
        sys.exit(a.fn(a))
    except ElevenError as e:
        print("FAIL " + str(e), file=sys.stderr)
        sys.exit(e.code)


if __name__ == "__main__":
    main()
