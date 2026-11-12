# Render, revision, export QA and delivery

## Observable review ladder

Tools: `render.mjs --stills`/`--every` for style frames, `contact_sheet.py` for
`--every`, `--times` and `--around` cut strips, `motion_check.py` for unintended
freezes and flashes, `finish.py` for master/share/poster/SRT. The critique method,
technical checklist, how to read a sheet and the delivery report form are in
`references/craft-qa.md`.

Render actual style frames at representative script/scene states, then a moving
draft, a contact sheet and consecutive transition strips. Inspect at intended
delivery-size (including actual mobile/chat thumbnail scale when applicable),
not only full-resolution screenshots. Read essential text and brand names there;
reduce copy or simplify hierarchy before shrinking type. No tiny crowded labels.
A contact sheet checks composition/order, never pacing, flicker or audio sync.
A model's critique of a downscaled sheet is a lead, not a finding: before
changing geometry or materials, crop the flagged region from the full-resolution
frame and ask one precise question about it, and before acting on "element
missing" compare the sampled time with that element's entrance.

For each segment record keep/fix/rebuild, evidence refs, reason, owner and cost;
identify the weakest scene and spend the declared revision budget there first.
After edits re-render the affected segment plus both cut boundaries, then review
the final encoded output. Stop at the time/iteration cap and report residual
defects; approval of an older draft does not certify the new export.

## Measure motion against the reference first

When matching an approved reference, measure it before authoring and retain its
hash, active range, intentional end-card duration and the decisions it informs.
Use `motion_check.py REFERENCE --ffmpeg PATH --profile general|kinetic --endcard
SECONDS`, then measure the candidate with `--reference REFERENCE`. Compare like
ranges and disclose differing crops/fps/end cards; reference measurements are
context and never change the candidate verdict. Only a selected kinetic-type
launch/teaser uses `--profile kinetic`; explainers and evidence films use general.

The checker decodes at native fps capped at 60, area-scales to 320x180 grayscale,
and measures `change_area`: the fraction of pixels with a luma change > 24 from
the previous frame. A still frame has `change_area < 0.015`; a cut has area > 0.45
and either an absolute mean-luma change > 18 or area > 0.6. These are frame-change
heuristics, not optical flow, camera speed or semantic edit detection. There is
no median-flow gate. Report `fps`, `seconds`, `still_share`, `still_runs` (runs
at least 0.3 s), `longest_unannotated_still_s`, `cuts_per_10s`,
`max_flashes_per_s`, `mean_change_area` and `high_motion_share` (area > 0.12).

- `general` revises an unannotated still run longer than 1.0 s; it has no
  aggregate still-share ceiling.
- `kinetic` revises when `still_share > 0.40` or an unannotated still run exceeds
  0.6 s. Do not impose those targets on a film whose concept needs quiet evidence.
- `--endcard SECONDS` excludes the tail from every metric. `--holds holds.json`
  accepts `[{"start":0,"end":1,"reason":"approved reading interval"}]` and
  exempts only the covered part of a still run. A reason is required; holds do
  not remove frames from `still_share` or waive flash review.
- A flash is an opposing pair of mean-luma jumps > 40 (up/down or down/up).
  `max_flashes_per_s` counts such pairs within any one-second window. A single
  ground flip with no return is not a flash. Both profiles return REVISE with
  `flash_review_required` above 3 pairs/s. Never use this heuristic as a medical,
  accessibility or photosensitivity safety certificate.

Receipts retain `artifact_sha256`, `profile`, `metrics`, `policy`, `issues`,
`limitations` and `artistic: "not_observed"`; an optional `reference` carries its
path, hash and metrics, not an artistic endorsement. Resolve
`unannotated_stillness` at its reported `at`/`duration`, `still_share_exceeded`
and `flash_review_required` with moving evidence and a documented revision.

## Measured export: show_reel_export_manifest/v1

List actual master/share/GIF/poster/subtitle variants requested, file hashes,
bytes/filesize cap, duration, dimensions, fps/timebase, codec/profile/container,
pixel format, color range/primaries/transfer/matrix, audio presence and provenance.
Probe final encoded files and fully decode them; do not infer success from a preset
or path existence. Color metadata is not color correctness: inspect gradients,
black levels and brand colors after decode, and record source/conversion intent.
With audio measure integrated loudness, true peak and A/V sync; STT only when
speech exists. No observed listening means listening not_observed even if metrics
pass. No audio means checks not_applicable with reason, not fabricated zeros.

Use `qa_check.py FINAL --audio-mode muted|music-only|narration|narration+bed/SFX --policy policy.json` with the chosen delivery limits (`--audio-mode` is required).
`max_h264_level` compares ffprobe's stream `level` (42 means Level 4.2, 52 means
Level 5.2; select for the intended 1080p/4K target). It fails on non-H.264 rather
than pretending that codec has a comparable H.264 level. Measurements include
`h264_level`; software decode success alone is not device playability evidence.
With `hardware_decode: true`, macOS runs a full FFmpeg decode using
`-hwaccel videotoolbox`; any error line is REVISE. On other operating systems
that check is HOLD, "not observable on this host", and overall cannot be PASS.
This is one host's decoder observation, not a guarantee for all phones, players
or channels. Record actual target playback separately when required.

Inspect the mix report's `buried_hits` before mastering: each row gives `at`,
`file`, `sfx_db` and `bed_db` when the placed effect's first 100 ms RMS is below
the music bed over the same window, after bed automation and ducking. No SFX or
muted mode yields `[]`. The report never changes gains; adjust the authored mix
only with a reason, rerun it, then remeasure final encoded audio. Neither an empty
list nor a numerical level comparison proves audibility or replaces listening.

## QA record: show_reel_qa_report/v1

Give each check PASS/REVISE/HOLD plus artifact hash, frame/time refs, method and
limits. Inspect:

- factual claims, source revision, brand/logo identity, rights and concept labels;
- actual delivery-size text readability, safe areas, contrast, clipping and hierarchy;
- native script line breaks, glyphs/fallback, weights, mixed-script baseline,
  Arabic shaping/bidi isolation of numbers/URLs/commands, subtitle reading time;
- every on-screen literal against `literal_fact_citations`: install commands,
  command names, URLs and counts match their cited source byte-for-byte, and
  every count agrees with its noun (`1 agents` is REVISE);
- the art-direction frame checks re-measured on the final export: frame fill,
  clear space, decorative meta text and the hue-family list;
- cut ordering, transition continuity, motion intent, unintentional freeze/flicker,
  flash suspicion and loops; distinguish an intentional hold from a stuck render;
- codec/color/filesize/channel cap and full decode; audio sync, pronunciation and
  listening only when observed. Automated flash metrics are not safety certification.

Any critical defect or unobserved required check prevents overall PASS. Missing
renderer/font/voice is HOLD; pageerror, timeout or partial export is failed/partial.
Keep incomplete frame counts, wrong dimensions, corrupt files and cancellation
cleanup visible; never relabel them successful. Re-encode oversized or unsupported
files and rerun final-file checks. Explicitly name which locale samples were
rendered and which remain contract-only; do not claim five-language fluency or
font/TTS/render support from fixtures.

Hand each tool report on as it was emitted. The JSON that `qa_check.py`,
`motion_check.py` and `mix.py` print and the table `finish.py` prints are saved
with the project and go to the next reader, another agent or the person, word
for word, with every check row and every `limitations` line. A summary may sit
beside a report, never in its place: a summary keeps the verdict and drops
rows, and a dropped row can be the one that failed.

## From a failed check to an edit

Each name below is printed by the kit's own checkers. Find its row, make the
edit, export again and run the same check on the new file. A policy value
changes only when the brief's delivery target changed; moving a limit to clear
a row leaves the same file. A printed name that is not below is a policy key
outside the set `toolkit/README.md` lists: correct the key.

| Printed name | What it found | The edit |
| --- | --- | --- |
| `muted mode contains undeclared audio` | The declared mode is muted and the file has an audio stream. | Export without the audio track, or declare the mode the brief asks for. |
| `required audio stream missing` | The declared mode needs sound and the file has none. | Mux the mix into the master with `finish.py --audio`; a muted brief declares `muted` instead. |
| `lufs outside +/-1` | Integrated loudness is more than 1 LU from the policy `lufs`, or was not measured. | Master the mix to the target again, encode and measure the encoded file. |
| `true_peak ceiling` | True peak is above the policy `true_peak`, or was not measured. | Lower the master, leaving room for the encoder to raise peaks, and measure the encoded file. |
| `max_bytes` | The file is larger than the size cap. | Encode the share copy at a lower rate and repeat every final-file check on it. |
| `max_h264_level` | Defined under Measured export above. | Encode as H.264 at a level the delivery target plays. |
| `hardware_decode` | Defined under Measured export above; a REVISE lists the decoder's lines in `hardware_decode_errors`. | Read those lines and encode with settings that decoder accepts. For HOLD, run the check on a macOS host or record playback on the target. |
| `duration`, `fps`, `frames`, `width`, `height` | The measured value differs from the policy value, `duration` by more than one frame. | Compare `project.json`, `REEL.config` and the policy with the brief, correct the one that is wrong and render again. |
| `probe_decode_measure` | HOLD: the file could not be probed, decoded or measured, and `reason` says why. | Fix the tool path or the export that `reason` names. Nothing counts as measured until it runs clean. |
| `unannotated_stillness` | Defined under Measure motion above; `at` and `duration` place it. | Add an event there or shorten the stretch (`references/craft-workflow.md`, Common problems, lists the kinds). A hold the brief's `motion_limits` planned goes in `--holds` with its reason. |
| `still_share_exceeded` | Defined under Measure motion above, for the kinetic profile; holds do not lower it. | Cut or shorten the rests before the end card, and pass the end card's measured length to `--endcard`. |
| `FAIL` on a `finish.py` row | That output is not yuv420p in tv range, or its loudness or peak is outside the target `finish.py` prints beside the flag. | Colour: encode through `render.mjs` and `finish.py` only. Loudness or peak: master again as in the `lufs` and `true_peak` rows. |
| `flash_review_required` | Defined under Measure motion above; the report gives the count, not the time. | Find the second on `contact_sheet.py --around` strips of the cuts, split the area that changes at once or soften the flip into a wipe (`references/craft-techniques-2.md`, T20), render that range with the final `--sub` setting and measure again. |

## Delivery: show_reel_delivery_manifest/v1

Separate generated, attached, received and published states with exact file
hashes and target receipts. A local path is generated, not delivered. Attachment
failure remains failed with a safe retry/alternative; external upload or
publication needs separate exact-target user approval and readback, and a spend
goes through `omh-spend-gate`'s card and typed yes first. Never infer
recipient receipt from an upload attempt. Include selected master/share/poster,
subtitles and source package as requested, rights/gaps and a regeneration recipe.
If a video was requested, a storyboard alone is not completion. Report the useful
prepared work and HOLD with the exact capability/evidence still missing.
