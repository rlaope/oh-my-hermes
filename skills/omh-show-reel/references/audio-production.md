# Local score, cue-aligned SFX, stems and honest audio gates

Choose muted/music-only/narration/narration+bed/SFX from the brief, not from the
conversation language. No default voice, provider, STT, download or paid call.
The opt-in `eleven.py`/`narrate.py` (narration, SFX, music, STT) and
`codex_ref_image.sh` run only when the user asks for them with their own
`ELEVENLABS_API_KEY` or signed-in codex; they refuse without it, and the film
falls back to local music and on-screen text.
Each run that reaches ElevenLabs or codex spends the user's own subscription
credits or plan usage, so it goes through `omh-spend-gate` before it runs: show
the target (which lines, voice and model, or which SFX, music, STT or image job
and its length) and the expected credits from the estimates in
`references/craft-brief.md`, then run it only after the person's typed yes to
that card. That yes is the exact-target approval for that run and nothing
wider; a regenerated line, a new take or a changed voice is a new card.
`eleven.py check` and `eleven.py voices` only read the account and spend nothing.
Audio comes before scenes: music beats and narration words set the picture's
times. Craft depth (voices, music plans, SFX design, mix targets) is in
`references/craft-audio.md`. `music_tools.py analyze` reads tempo, downbeats and
hits from the chosen track; `timeline.py script.json --music-analysis` turns them
into `barN`/`music.hitN`/`music.dropN` cues and `reel/timeline.js` for
`REEL.cue`/`bar`/`beat`/`level`.

Fit the passage the film uses with `music_tools.py analyze FILE --bpm HINT
--start SECONDS --window SECONDS [--out analysis.json]`. `--bpm` constrains the
tempo/phase search to within ±8% of the hint, without folding it into a slower
tempo band. `--start` and `--window` bound the fitted stretch; they are not a
source-audio trim or a film start delay. Without `--bpm`, tempo selection retains
its existing behavior and `alternatives` lists half/double-tempo candidates in
60–200 BPM. Inspect those when a beat grid appears to follow every second accent.

Read `grid_strength` (0..1) and review
`warning: "tempo hint disagrees with the track"` if an unconstrained fit is
clearly stronger. A forced hint must not hide
a poor grid. `drops` contains up to three time-ordered `{t, rise, bar}` rows:
`rise` compares loudness over two bars after a downbeat to one bar before it.
Choose a useful musical turn with actual listening when available, not the ratio
alone. `timeline.py` carries `drops` into its music timeline and produces
`music.drop1..N`, shifted by the music start offset just like `barN`. Use these
cue IDs for scene/SFX anchors; recompile after changing the track or its start.
Read `references/kinetic-type.md` only for a selected kinetic launch/teaser's
beat-sheet and source-trim formula.

Read `toolkit/README.md` and `scripts/synth_music.py`, `mix.py`, `qa_check.py`
relative to that toolkit. The local seeded score is a modest fallback: section
notes/energy/BPM and tick/boom/whoosh events are parameters, not a musical-quality
promise. Licensed imported local music is equally valid; record its rights/hash.

Timeline cues are explicit IDs with seconds/frame indices or acyclic after+offset,
or script.json scenes/SFX placed on music and narration cues. A narration cue comes
from the provider's character alignment of the approved tts text; never derive a
screen event by guessing where a substring is spoken without that alignment. Audio events use numeric `at` or an exact cue ID and start/peak/end anchor.
Measure the PCM event anchor and A/V cue against decoded frames, not a guessed
hearing result. Unknown cues, missing required tracks, corrupt or wrong-rate audio
must fail closed before a usable final mix. Muted cannot silently discard tracks.

Mix uses explicit stereo 16-bit PCM WAV in one declared sample rate; host decode/
resample is a separate observed action. Retain narration/bed/SFX stems, authored
gain automation, speech-aware bed ducking and recovery outside speech. Compare
speech/non-speech intervals numerically, then listen to the actual final encoded
mix if that capability is observed. A sample limiter is not true-peak certification.
`--ffmpeg` on mix measures loudness, not normalization; master explicitly and
measure post-AAC LUFS/true peak with the chosen policy. No parse/decode/tool failure
becomes zero or a PASS. Silent/nonfinite required-audio metrics are HOLD.

Keep synthesis, mastering, final-AAC measurements, STT, pronunciation review and
listening as different observations. STT only when speech exists and separately
approved tooling is available; it never proves naturalness, consent or listening.
A musical accent must support the shot/cut, not mask every change with a boom.
