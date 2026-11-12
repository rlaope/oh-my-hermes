# Kinetic-type lane

## Select the lane, do not default to it

Use this opt-in page only after concept selection chooses kinetic typography for
a hype launch or teaser. Never apply it to explainers or evidence films: those
need the time and visual emphasis their evidence requires. Existing source,
rights, locale, budget and delivery contracts still apply; speed cannot excuse an
unsupported claim or an unreadable command. No new engine, provider or paid tool
is required. Author with the existing companion or another observed renderer.

## Write a beat sheet before scenes

Start with approved phrases and the chosen, rights-cleared music. Fit the passage
actually used with `music_tools.py analyze TRACK --bpm HINT --start SECONDS
--window SECONDS`; inspect `grid_strength`, downbeats, `drops` and any `warning`.
A requested BPM is a search hint, not proof of the recording's tempo. Read
`references/audio-production.md` before converting its times into a timeline.

Plan in beat units, then resolve to seconds through the measured tempo. Record
start/end beat, phrase, focal object, ground, movement and sound cue for each shot.
Use `REEL.bar`/`REEL.beat` with the compiled timeline, `barN` anchors and
`music.dropN` cues rather than scattering independently rounded seconds in scenes.
The visual turn belongs on a measured drop, not merely a loud-looking waveform.
For a zero-based planned drop beat and source-track drop time, the trim is:

`offset = drop_s - planned_drop_beat * 60 / bpm`

Here `offset` is the source audio to trim before film time zero, not a timeline
start delay. Apply that trim explicitly to the approved track and regenerate its
analysis before compiling cues; `timeline.py` shifts analysis cues by the music
start offset, it does not perform this source trim. A negative result needs an
authored lead-in or a different drop/beat choice, not silent clamping. Check the
first and last accents against decoded picture and audio before locking timing.

Give each beat one new thing to notice: new copy, a different scale, a reveal or
a change of viewpoint. A synchronized sound reinforces that event rather than
adding another competing message. Split long phrases instead of compressing type
or assuming Latin reading speed for every script. Build accelerating cut runs by
shortening successive beat spans toward the turn; vary the next run so cadence
has a shape, and do not insert rapid flashes as a substitute for that shape.

## Choose a device from the meaning

| Phrase job | An authored visual device |
| --- | --- |
| Denial | Remove or cross out the rejected object, then let the replacement occupy its space. Do not imply an actual product action unless captured. |
| Number | Make a verified quantity change the composition: a counter resolves, an area grows, or a scale compresses. Cite its exact source. |
| Input->output | Carry one visible token through a transformation into the result; captured input/output or a clearly labeled concept determines the claim. |
| Recap | Revisit earlier focal objects in a shorter sequence with a changed relationship, not a page of tiny thumbnails. |
| Picture push | Move into an approved picture's relevant detail, changing crop or parallax as the phrase develops; never leave a static image behind moving captions. |

These are a vocabulary for fresh scenes, not shipped block names or an effect
checklist. Preserve intact shaping runs for Arabic and other joining scripts;
measure text in the actual renderer and test moving samples at delivery size.

At phrase changes, use ground flips between approved brand-compatible light,
dark or accent treatments to mark the argument's turn. Recheck contrast on each
ground and keep the existing palette limits. Design transitions as camera moves:
carry direction through a pan, pass through a letter aperture, or change focal
scale around a shared object. Motion continues after an arrival for a reason;
noise, grain or unrelated particles must not be added just to beat a stillness
metric. Reserve rest for the end card and declare its actual duration separately.

## Sound and shutter belong in the edit

Make every cut audible with a deliberate music accent or a placed SFX; avoid a
stack of interchangeable impacts. Add one custom gag sound tied to this film's
own comic turn, using approved local synthesis/recording or rights-cleared audio.
Record each cue in the timing/mix source and inspect `buried_hits` from `mix.py`;
revise authored levels or bed automation deliberately and remeasure. That report
does not adjust gain and is not evidence of listening. If the brief requires a
muted delivery, do not invent an audio receipt: use the general workflow rather
than claim this sound-led lane's full acceptance.

Declare all hard-cut seconds in the project root's `project.json` as `cuts`, a
strictly increasing array inside `(0, duration)` with at most 4096 entries. Keep
those times equal to the scene boundaries. The companion's cut-aware shutter
keeps sub-frame captures inside the shot containing the output frame; do not
shift hard cuts by half a frame to hide cross-shot blur. See
`references/renderer-adapter.md` for sampling and receipt limits.

## Compare and gate the encoded film

Measure an approved reference first, recording its hash, active range and limits;
then run the same motion method on the candidate. Example operator invocation:

```sh
python toolkit/scripts/motion_check.py REFERENCE.mp4 --ffmpeg /approved/ffmpeg --profile kinetic --endcard REFERENCE_ENDCARD_SECONDS
python toolkit/scripts/motion_check.py FINAL.mp4 --ffmpeg /approved/ffmpeg --profile kinetic --endcard ENDCARD_SECONDS --reference REFERENCE.mp4
```

Replace the end-card placeholders with measured seconds. Reference numbers are
context, never permission to relax the gate; `--reference` cannot change the
candidate verdict. The kinetic profile requires `still_share <= 0.40` and no
unannotated still run longer than 0.6 s before the excluded end card. Declare
intentional holds with a nonempty reason through `--holds`; exemptions apply to
covered still-run time, not to the aggregate still-share ceiling. More than three
opposing brightness-jump pairs in a one-second window requires flash review.

Read `references/render-qa-delivery.md` for measurement definitions and separate
H.264 level, hardware decode, filesize/color/audio, and artistic/playback/listening
gates. A numerical PASS alone is not artistic approval, accessibility certification,
or a completed film. Review moving cut strips and the final encoded artifact;
revise the weakest scene without exceeding the agreed budget.

Method notes informed by Scenario's Kinetic Film exploration (https://www.scenario.com/explorations/kinetic-film/,
skill ZIP sha256 2217ab5dbd452185a5c3c1509994da46b1ac20d2ebeaa888536244372ce73ebf). OMH wording and code;
nothing was copied.
