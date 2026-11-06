> Translated in full from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6 `showreel/references/audio.md` (MIT, Copyright (c) 2026 Minho Hwang (revfactory); `toolkit/LICENSE.upstream`, provenance in `toolkit/upstream-manifest.json`). Read it for voices and settings, music and SFX, mix targets. `$S` is `toolkit/scripts` under the loaded skill directory. Commands here are upstream's; check the upstream command map in `toolkit/README.md` before running one. Content language follows `references/brief-and-locales.md`: Korean-first defaults apply only to Korean content, the craft bar applies to every locale; host install paths are placeholders here, upstream's default narration voice is named by role and chosen only through voice_policy, inline OMH notes mark where OMH policy overrides an upstream default, and the provider scripts are opt-in with the user's own key.

# Audio: narration, music, sound effects, mix

## Contents

- ElevenLabs key and plan
- Voices and models
- Narration generation and pronunciation verification
- Music
- Sound effects
- Mix standards
- Common problems

## ElevenLabs key and plan

Check the key, voices, and models with `python3 scripts/eleven.py check`. If there is no key, give the user the procedure below exactly as written (the same content is in `KEY_HELP` in `eleven.py`).

1. Sign up or log in at https://elevenlabs.io -> bottom left Developers (or the profile) -> API Keys -> Create API Key
2. Permissions: turn on Text to Speech, Speech to Text, Sound Effects, Music, Voices (Read), and User (Read). User Read is required to query the remaining credits. The key is shown only once, so copy it right away.
3. Save it in the shell config: `echo 'export ELEVENLABS_API_KEY="sk_..."' >> ~/.zshrc && source ~/.zshrc`, or as `ELEVENLABS_API_KEY=sk_...` in `.env` in the project folder

Features blocked by plan (measured):

| Feature | Free | Paid (Starter $6 and up) |
| --- | --- | --- |
| Library voices (the verified Korean narrator etc.) | Blocked with 402 | Available |
| Music API | Blocked with 402 | Available |
| 192kbps output | 403 (Creator and up) | Creator and up |
| Sound effects, STT | Available | Available |
| Commercial use | Not allowed (attribution required) | Allowed |

- The concurrent request limit is 2 to 5 depending on the plan. Exceeding it returns 429, and `eleven.py` waits and retries. The scripts' default concurrency is 2 for TTS and 3 for sound effects.
- If `/v1/user/subscription` returns 401 (missing user_read), it is only a key permission problem; the key itself is fine. Tell the user to check credits on the dashboard.
- When something is blocked, do not work around it; report it right away. There has been a case where the user paid on the spot.

## Voices and models

| Voice | voice_id | Character | Recommended model |
| --- | --- | --- | --- |
| Verified Korean narrator | `ibCGc01503OQd2R6i1n1` | Deep, calm baritone, Seoul accent, for reading aloud. The voice the settings below were verified on (F0 about 78 to 83Hz) | `eleven_multilingual_v2` (fine-tuned) |
| Do Hyeon | `FQ3MuLxZh0jHcZmA5vW1` | Deep middle-aged male | `eleven_v3` |
| Yohan Koo | `4JJwo477JUAx3HV0T7n7` | Confident, authoritative | v2, v4 |
| 안재동 Jaedong Ahn | `ZcZcEsYxXAIc3nNSev1H` | Calm middle-aged male | v2 |
| Kwan | `eMzlsWTml7eAEDvSiETn` | Energy, passion | v2 |
| Anna Kim | `uyVNoMrnUku1dZyVEXwD` | Young female, composed (whisper acting `[whispers]`) | v3, v4 |
| Sujin | `8zHuDw1bbkbkL93Inv5N` | Bright, lively female | v2 |

> OMH note: this table lists Korean voices because upstream makes Korean films. Choose a voice through the brief's voice_policy for the content locale; `eleven.py` and `narrate.py` require the voice and language to be named and run only with the user's own ELEVENLABS_API_KEY.

Find other voices with `eleven.py voices --lang ko` (my voices) and `--library` (public library search).

Model choice:

- `eleven_multilingual_v2` (default): `previous_text` and `next_text` carry intonation across sentences, and style and speed can be used. The verified Korean narrator is fine-tuned on this model.
- `eleven_v3`: uses audio tags (`[serious]`, `[whispers]`). There has been a case where it read names and numbers more accurately than v2 (이훈희 (the name Lee Hoon-hee), 2026). Use stability 0.5: 0.0 added words that were not there, and 1.0 misread. It does not accept `previous_text`. When switching only a problem line to v3, check that the pitch connects with the lines before and after.
- `eleven_v4`: accepts only stability and similarity. The verified Korean narrator is not fine-tuned on v4, so the timbre can change.

Verified Korean narrator reading settings: stability 0.42 to 0.5, similarity 0.8 to 0.82, style 0.38 to 0.45, speed 0.97 to 1.05, speaker boost on. Raising style makes it less monotonous.

## Voice crossing

Alternating several voices in one video conveys scene changes through sound as well. Write `"voice"` (and if needed `"model"`, `"settings"`) separately on each line of `script.json`. `narrate.py` passes surrounding context only between lines of the same voice, and `mix.py` levels each line, so the loudness does not jump when the voice changes.

Ways to use it:

| Approach | Example | Where it fits |
| --- | --- | --- |
| Main narrator + quote voices | The verified Korean narrator leads, and only a person's words or a customer's voice use another voice | Profiles, brand films |
| A voice per chapter | Chapter 1 the verified Korean narrator, chapter 2 Yohan Koo, chapter 3 Anna Kim | Introductions that show several perspectives |
| One word each, in relay | Four voices say "기획." "원고." "목소리." "영상." (planning, script, voice, video) one at a time | Opening intros, montages |
| The same sentence in several voices | Play the same sentence back to back, changing only the voice | Voice or feature demos |
| Whisper, acting | Anna Kim `eleven_v3` + `[whispers]` | The twist in a teaser |

- Use at most three or four voices. Beyond that it gets confusing who is speaking.
- On a line where the voice changes, also change something on screen (scene transition, speaker name label, color).
- A serious personal profile uses one main narrator by default, and uses crossing only for the opening and quotes.
- Each voice has its own pronunciation habits, so run `--stt` verification on every line.

## Narration generation and pronunciation verification

```bash
python3 scripts/narrate.py <project>/script.json --stt
```

- Each line is generated with `/with-timestamps`, and the character-level alignment (`<id>.align.json`) is saved. For Korean, use `alignment`. `normalized_alignment` returns Hangul romanized.
- `--stt`: transcribes with Scribe and compares against whichever of the on-screen spelling and the pronunciation spelling is closer. A similarity below 0.85 or a differing number is ✗.
- Only changed lines are regenerated. To regenerate specific lines, use `--only n03,n07 --force`.
- `takes`: generates N times with different seeds and uses the take with the most accurate STT as the main file. The rest remain as `<id>.t2.mp3` and so on.

When a ✗ appears, fix it in this order.

1. Fix the pronunciation spelling (write numbers and abbreviations in Hangul)
2. Break the reading with commas or ellipses ("이공, 이육!" (twenty, twenty-six!), "언리얼… 아이돌." (Unreal... idol.))
3. Change the sentence: drop the particle after a brand name, avoid homonyms
4. `takes` 3 to 5
5. For that line only, `"model": "eleven_v3"`, and `[serious]` before the text

Changing stability or swapping the model wholesale had no effect.

**A clip can pass STT on its own and still be wrong in the finished mix.** Music and sound effects cover it. So transcribe the finished cut as well with `qa_check.py --stt`. STT results can vary from run to run, so fix a line when it is wrong twice in a row.

## Music

### 1) One spec, two paths

Write `audio/music/spec.json` once, and both the ElevenLabs plan and the synthesized music can be made from it.

```json
{"duration": 60, "mood": "cinematic", "bpm": 90, "key": "D", "minor": true,
 "global_styles": ["<genre, instruments, and texture set by the concept, in English>", "instrumental"],
 "sections": [{"name": "Cold Open", "start": 0, "energy": 0.2},
              {"name": "Reveal", "start": 8.5, "energy": 0.6, "style": "massive braam on the first beat"},
              {"name": "Rise", "start": 18, "energy": 0.8}, {"name": "Climax", "start": 40, "energy": 0.95},
              {"name": "Finale", "start": 52, "energy": 0.3}],
 "events": [{"t": 8.5, "type": "hit"}, {"t": 39.6, "type": "riser", "dur": 2}, {"t": 30, "type": "stop", "dur": 0.8},
            {"t": 56, "type": "boom"}, {"t": 57.5, "type": "chime"}]}
```

- The character of the track is decided in the concept. Write the genre, instruments, and texture in English, like `"global_styles": ["glitchy breakbeat with janggu percussion", "crisp clicks", "instrumental"]`, and the ElevenLabs plan uses that wording. Set what to exclude with `"negative_styles"` and the ending of the last section with `"ending"` (default "final big hit then long reverb ring out").
- Without `global_styles`, the default wording for the mood is used: `cinematic` (orchestra and taiko, trailer-like) / `pulse` (electronic pulse) / `soft` (piano and strings) / `playful` (upbeat pop). The `synth_music.py` fallback path can make only these four, so write the mood as well for the fallback path.
- For a showreel, align the sections with the segments in `concept.md`. If the sonic texture must change per segment, write the instrument change in the section `style`.
- The energy (0 to 1) of sections sets the number of layers. In the plan it becomes a sentence that fits the mood ("orchestra" does not get into a tech mood).
- Set sections in 4-bar units (8 seconds at bpm 120, 10.67 seconds at 90). If a boundary does not fall on a bar, `plan` warns. The API does not accept sections shorter than 3 seconds, so `plan` pushes the boundary to the 3-second point or merges it into the previous section.
- events: hit, boom, braam, riser (ends at t), whoosh, chime, stop (briefly cut only the music - a silence effect)

### 2) ElevenLabs Music

```bash
python3 scripts/music_tools.py plan audio/music/spec.json            # → audio/music/plan.json
python3 scripts/eleven.py music audio/music/music.mp3 --plan audio/music/plan.json
```

- Sections must be 3 seconds or longer. `plan` merges short sections into the previous section.
- **Do not include artist, composer, or track names.** "Hans Zimmer style" was rejected twice with 400. When rejected, `eleven.py` shows the alternative prompt from the response.
- Generation takes 1 to 2 minutes for a 60-second track. With the same plan you can change `--seed` to make two tracks and choose. Giving `--prompt` and `--seed` together returns 422, so `eleven.py` sends without the seed.
- On 402, go to synthesized music.
- The generated track length can differ from the request (a case where a 10-second request produced 7 seconds). Fit it to the video length with `music_tools.py fit`, then analyze.
- Generated tracks are usually flat (in evaluation, 82 to 85% of both tracks was within 3dB of maximum loudness). When `analyze` warns, pull down the music before a big hit in the mix. If you write [time, dB] in `music` in `script.json`, like `"automation": [[0, 0], ["line.n07-2.5", 0], ["line.n07-0.3", -10], ["line.n07", 0]]`, `mix.py` changes the music volume along that curve. Time can be seconds, a cue name, or "cue±seconds". Pulling down to -8 to -12dB 2 to 3 seconds before a hit and returning to 0dB on the hit frame makes an anticipation -> impact structure audible even in the same track.
- When writing the spec, put contrast in section energy. Keep the climax (0.9 or above) within 25% of the whole, one breakdown of 0.3 to 0.45 around the middle, and write instrument changes in `style` for neighboring sections (e.g. "strings drop out, only ticking pulse", "add brass stabs and choir"). `plan` warns about a flat spec.
- A stop (silence effect) in the plan was often ignored (confirmed on a 2-minute track). After generation, find the first beat of the next phrase with `analyze` and cut up to that point: `python3 scripts/music_tools.py gap audio/music/music.mp3 audio/music/music_edit.wav 103.2-103.97`. Change `music.file` in `script.json` to `audio/music/music_edit.wav` and rerun from `timeline.py`.

### 3) Synthesized music (fallback path)

```bash
python3 scripts/synth_music.py music audio/music/spec.json audio/music/music.wav
```

It is made with numpy, without source audio. The same input gives the same sound, and it finishes in a few seconds. It is simpler than ElevenLabs Music, so state in the delivery report that it is synthesized music.

### 4) Analyze, then fit the scenes

**ElevenLabs Music does not keep the plan's section lengths.** It usually converges on 4-bar phrases (8 seconds at 120 BPM). Always analyze after generation.

```bash
python3 scripts/music_tools.py analyze audio/music/music.mp3     # → analysis.json: bpm, beats, downbeats, hits, energy
```

- Look at the analysis and move the scene boundaries to the actual hits and downbeats. Passing `timeline.py --music-analysis` creates `music.hit1…` cues, and `REEL.TL.music.hits` and `downbeats` can be used on screen.
- If a drop or climax is weak, generate only that stretch separately ("starts immediately with a massive hit on the first beat", negative "slow intro"), splice it in, and re-analyze the hits to align.
- If the length is slightly off, fit it with `music_tools.py fit in.mp3 out.wav --dur 60` (within 6%, a fine tempo adjustment; otherwise trim or pad + fade).
- **If the drop comes late, cut and splice by the beat.** There was a case where a 15-second reel requested the drop at 3 seconds and both seeds put it at 7.8 seconds. Look at the beat times in the analysis and cut at the same beat phase (bar start to bar start).

```bash
python3 scripts/music_tools.py splice audio/music/music.mp3 audio/music/music_edit.wav \
  --segments 0-3.90,7.78-19.5 --snap audio/music/analysis.json      # front of the build-up + from the drop -> drop pulled to about 3.9 s
python3 scripts/music_tools.py analyze audio/music/music_edit.wav   # re-analyze and align the scene boundaries
```

## Sound effects

```bash
python3 scripts/eleven.py sfx-kit audio/sfx --names impact,whoosh,riser,logo_hit,glitch,ui_blip   # ElevenLabs
python3 scripts/synth_music.py sfx audio/sfx --names impact,whoosh,riser,logo_hit                 # synthesized (free, instant)
```

Preset names and prompts are in `assets/sfx_presets.json`: sub_boom, impact, braam, logo_hit, final_hit, riser, reverse_swell, whoosh, whoosh_deep, glitch, shimmer, ui_blip, ui_ticks, typing, stamp, shutter, counter, heartbeat, clock_tick, crowd, pop, ding, chime, drone. Make a new sound effect with `eleven.py sfx "prompt" out.mp3 --dur 2`. Length is 0.5 to 30 seconds.

Placement principles:

- **Do not repeat the same whoosh on every transition.** Putting the same sound on every scene sounds repetitive and monotonous. Make sounds that match the material on screen (paper, glass, liquid, metal, electronic) separately with `eleven.py sfx "prompt"`, and use the generic whoosh only at a few big transitions.
- Align impact sounds (impact, logo_hit) to the on-screen hit frame with `align: peak`, but **keep them 0.2 to 0.3 seconds off the key word of the narration.** There was a case where a logo hit covered "커넥트" (Connect) and STT transcribed it as "Summit".
- Use `align: end` for risers so the end lands on the hit time. Start 1 to 2 seconds earlier.
- If there is an object on screen that makes a sound (a counter, a keyboard), put that sound on the same frame.
- The same event must be on screen and in sound together. Hang sound effect times on cues in `script.json`, using the same numbers as the screen (`REEL.cue`).

## Mix standards

```bash
python3 scripts/mix.py <project>/timeline.json
```

| Item | Standard |
| --- | --- |
| Source normalization | Narration speech RMS -20dBFS, music -16 LUFS, sound effects peak -3dBFS (then `gain_db`) |
| Narration chain | High-pass 70Hz, 220Hz -2dB, 3.2kHz +3dB, 9kHz shelving +1.5dB, compressor 3:1 |
| Narration reverb | None by default (`--hall 0`). The same goes for a grand tone; create the grand feel with music and sound effects. Only when a sense of space is truly needed, `--hall 0.04~0.08` (1.4-second hall, pre-delay 30ms, 300 to 5000Hz). The `--hall` value is the wet/dry ratio over speech (0.06 = wet -24dB) |
| Speech tail reverb | When reverb is used, `mix.py` shows the tail reverb level 0.05 to 0.35 seconds after the end of speech before a pause, compared with the speech. -32dB or below ✓, above -28dB ✗. The previous default (2.4-second hall, `--hall 0.12`) was -22.8dB and drew the complaint that there was too much echo |
| Music | `gain_db` -6 to -10, ducking 0.7 to 0.8 (deeper in the speech band) |
| Sound effects | Lowered 45% over speech (`--sfx-duck`) |
| Per-line narration vs background | 9dB or more ✓, 6 to 9dB △, under 6dB ✗ |
| Master | Limiter -> 2-pass loudnorm -14 LUFS, true peak -2.0 dBTP. The peak rises 0.5 to 0.9dB after AAC encoding, and the share file is encoded once more, so leave headroom (`finish.py` re-measures the share file's peak and lowers it if it is over) |
| Video without narration | `mix.py` shows the "sound effect vs music" dB for each sound effect. Impact sounds need +3dB or more to be heard |

Order for fixing a ✗ line: lower the `gain_db` of sound effects near that line or move their time -> that line's `gain_db` +2 to 3 -> `--duck 0.8`. If the cause is unclear, turn things off one at a time with `--mute music` / `--mute sfx` and look again.

## Common problems

| Symptom | Cause and fix |
| --- | --- |
| `CERTIFICATE_VERIFY_FAILED` in Python | A certificate problem with the python.org distribution. Do not turn off verification. `eleven.py` uses curl |
| The mp3 does not play ("Failed to find two consecutive MPEG audio frames") | An error JSON was saved under the mp3 name. `eleven.py` checks the HTTP status and content to prevent it |
| TTS call with empty text | Returns 200 and a silent mp3. `eleven.py` blocks it in advance |
| Sound effect is nearly silent | `sfx-kit` changes the prompt and regenerates when the peak is below -24dB |
| Music section 422 | The section is shorter than 3 seconds. `music_tools.py plan` merges it |
| Too much echo or ringing on the narration | Remove `--hall` and rerun only `mix.py` -> `finish.py`. ElevenLabs source clips drop to -60dBFS within 0.1 seconds after speech ends, so the echo comes from the reverb added in the mix |
| Narration length differs from the alignment data | A clip whose length changed in post-processing (reverb, apad) needs its alignment recomputed. Do not modify the source clip; handle it in the mixer |
| Not sure whether the sound is right | Claude cannot hear sound. Check by numbers (VO vs background, LUFS, STT, spectrogram) and ask the user to listen |
