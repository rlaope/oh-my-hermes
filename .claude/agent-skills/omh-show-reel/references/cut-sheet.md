# Cut-sheet lane

## Select the lane, do not default to it

Use this opt-in page when a short, cut-driven film (title sequence, character or
product reveal, showreel intro, teaser of 30 s or less) is built from a written
shot contract: either handed to a coding model or companion that authors a
deterministic scene, or sent as a prompt to a text-to-video generator. It is
also the lane for remaking a supplied reference video in another subject. It
does not replace the brief, rights, locale or delivery contracts, and it never
applies to explainers or evidence films. A 15 s or shorter promo that the brief
wants as one scene keeps the one-scene rule; this lane is for briefs that ask
for cuts.

## Write the contract line first

Open with one sentence that fixes what every later row must obey: aspect ratio,
duration, exact cut count, frame rate, the share of screen time for graphic
design versus subject action (for example 80/20), a named style formed as
"A x B" from two concrete genres, and a palette of four to six named colours.
Numbers here are acceptance criteria, not mood: QA later counts the cuts and
checks the palette against them.

## Lock the subject once, in markers

List the three to eight features that make the subject recognizable, as
observable markers (shape, colour, material, accessory, proportion), not
adjectives. Follow them with an explicit preservation clause: keep these exact
features in every cut and never redesign. Pair the markers with the approved
reference art in `references/assets-and-rights.md`; a marker list without art
drifts, and art without markers loses small details. When the target tool caps
prompt length and the contract is split into numbered chunks, repeat the lock
paragraph in every chunk. A subject with only still art gets a pose sheet made
from that art in the same rendering (named poses, flat key colour, one figure
per cell) before any action cut is written; poses are moved, scaled, tinted and
masked, never redrawn.

## One row per cut

Write each cut as one row:

`CUT NN | start-end s - ground; focal event; graphic device; exit transition`

- One new event per cut. If a row needs "and then" twice it is two cuts.
- Every cut differs in composition from its neighbours: change at least two of
  ground (light, dark, accent), scale (detail, medium, wide), layout (centred,
  edge, split, full-bleed) and viewpoint.
- Name the exit transition, and prefer graphic matches that carry one shape
  across the cut (a letter counter becomes an aperture, a ring becomes a target
  lock, a slash becomes the next frame's edge). The kinetic-type device table in
  `references/kinetic-type.md` maps phrase jobs to devices.
- Give the arc an energy budget: name the single peak cut, place one held beat
  before it, and end on a cold, readable identity card rather than on the peak.
- Readability rule: any word on screen is fully readable for at least 6 frames
  before a subject or effect overlaps it.
- Write constraints as a swap, not only a ban: "no X; the energy comes from Y".

Declare the editing grammar once, as a closed vocabulary (hard cut, graphic
match, whip pan, snap zoom, strobe freeze, foreground wipe, RGB split, shutter
flash, impact shake, speed ramp), so rows reference it instead of inventing
effects. Restate the two or three hardest constraints, such as the exact cut
count and subject consistency, as the last line.

## Sound is written with the rows

State the bed (genre, or SFX-only), which cuts carry the heaviest hits, where the
peak lands and how the film ends (a stinger, a cut to silence). Name SFX roles
as rhythmic elements tied to rows: footfalls, whooshes, glass, type slams. When
building, place sounds from a rights-cleared professional SFX library: measure
each file's event onsets, align the onset (not the file start) to the cut,
stack two or three layers per hit (transient, body, tail), and keep 0.15-0.25 s
of silence before the biggest hit. Search-ranked amateur clips and synthesized
blips read as cheap. On SFX-only tracks a "linear" loudness pass can fall back
to dynamic mode and land hot; apply a measured fixed gain and an oversampled
limiter, then remeasure. `references/audio-production.md` owns the gates.

## Remaking a supplied reference

Measure before writing rows: hard-cut times with a scene-change detector
(`ffmpeg -i REF -vf "select='gt(scene,0.2)',showinfo" -an -f null -`), audio
onsets and silent holes from a short-window RMS curve, and a 10 fps contact
sheet for single-frame flashes a 4 fps sheet misses. Put the measured times into
the rows with a stated tolerance (for example plus or minus 0.05 s). Keep the
reference's grammar, rhythm and density; replace its subject, words and images
with the brief's own. Reusing the reference's literal phrases or objects is
overfitting, not a remake. Record the reference URL and that it was used for
timing and grammar only.

## Hand-off and review rounds for a delegated build

The cut sheet becomes the builder's spec: the contract line, the locked subject
with asset paths, the rows, the determinism contract from
`references/motion-techniques.md`, and a check command that renders one still
per cut midpoint plus each transition. Ask the builder to place reference and
candidate frames of the same second side by side and judge each pair.

Review with numbered, measurable fixes ordered by severity in a new round file
(`FIX1.md`, `FIX2.md`): sizes as a share of frame height, alphas, counts, times.
"Make her bigger" fails; "subject 55 % of frame height in front of the ring"
passes. When one component stays weak (a prop, a logo treatment), split it into
its own module with its own test page and review rounds, then integrate it in
the next film round. Two determinism traps seen in 2D canvas builds: a
GPU-backed canvas rasterizes edges differently depending on what was drawn
before (create contexts with `willReadFrequently: true`), and back-to-back seeks
batch into one raster (read back one pixel at the end of each seek). Verify by
comparing fresh-page frames against frames reached through a shuffled seek
order.

## Gate against the rows

Count cuts on the encoded film with the same detector and compare against the
contract. Check each row's focal event, device and readability on decoded
frames, not on authored stills. Report rows that miss with their time and cause;
a numerical pass is not artistic approval.
