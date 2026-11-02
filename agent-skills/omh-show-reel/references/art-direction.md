# Independent artistic acceptance and the weakest-scene rebuild

How to set art direction per segment, the predictable screens to avoid, motion
principles, rhythm, typography, safe areas and transitions are in
`references/craft-design.md`. Before an expensive render, compare three distinct
narrative/visual concepts, not palette swaps. For each useful reference record exact source/locator, revision
or inspection date, what composition/motion/sound decision it informs, rights and
limits. A supplied pinned reference can be enough; do not invent a trend claim or
seek unrelated references just to fill a quota. Never confuse imitation with
brand coherence: retain untouched official masters, establish a restrained visual
language, and select material/effect according to the message.

For every timed segment decide medium, palette, type, texture, composition,
focal point, movement/weight, sound intent, entry/exit and cut motivation. Render
style frames at delivery size AND a short moving proof before full production.
Authentic product captures, material/photographic composition, depth, kinetic
phrases, seeded geometry and quiet holds are options, not a required effect list.

## Hero-frame acceptance before the full render

A film that passes every lint, layout and contact-sheet check can still be
rejected on sight. Judge the hero frame (usually the first, which is also the
thumbnail) as a launch frame before rendering the whole film. Ask whether a top
product team could open its launch film on that frame. Then name each element
that reads as template or cheap, with the change that fixes it:

- A product shown in 3D is a lit model with real materials (a GLTF device, for
  example, with the product screen as a live texture), not stacked CSS layers
  or flat cards. A stacked-layer object reads as cardboard however it is
  animated.
- Materials are measured, not eyeballed: crop the product region from a
  rendered frame and read its mean luminance and clipped share. A light-coloured
  surface whose bulk sits near white with a radial hotspot reads as a glowing
  panel, so lower roughness-driven specular or key light until its tonal range
  opens.
- The title is set in the brand's own face and colour (see
  `references/storyboard-and-evidence.md`), the background carries the brand's
  own art or a deliberate material, and on-screen product UI reads as a
  shipped app rather than bare boxes.

## Frame checks before the first style frame

Run these on the storyboard, then again on the rendered style frame. Each is a
measurement with a stated number, not an impression.

- `frame_fill`: the area a product shot fills depends on the subtitle mode,
  using the zones `references/craft-design.md` (Layout and safe areas)
  defines. With no subtitles, a product-led shot is full-bleed: it uses the
  full frame minus the 46 px edge inset, so a 1080p product shot is at least
  about 988 px tall (1920x1080: at least 1828x988), and in 9:16 it still keeps
  the top 250 px and bottom 420 px clear. With subtitles, it fills at least 90%
  of the width and height of the body safe area (16:9: x 120-1800, y 120-900)
  and the subtitle band y 940-1040 stays clear. A shot that is not
  product-led, such as a title or a quote, follows the safe areas instead.
  Text rows are at least 2% of the frame's shorter side (22 px at 1080). Choose terminal columns and
  rows, or the viewport, from that area and row height; never keep a default
  size and letterbox it. Record the area used, the measured fractions and the
  row height.
- `clear_space`: a logo or identity mark (one the product renders, such as an
  ASCII logo) keeps clear space of at least one of its own text rows (one
  terminal row for an ASCII logo) from the frame edge and the window edge.
  Flush against either is REVISE. An intentional crop, as `craft-design.md`
  allows, is exempt; headings follow the type and safe-area rules instead.
- `decorative_text`: no text the product does not render and the brief does
  not need. Window title bars, `cols×rows` dimension labels, invented paths
  and prompts, and fake version strings are removed, not restyled.
- `palette_families`: for a composed frame (promo shot, poster, slide, end
  card), list every hue family on screen with its hex values and where it
  appears (background, window chrome, product palette, logo, captions,
  accents). The captured product or brand palette is given and never
  repainted. The surrounding composition adds at most one accent family beyond
  it. Neutrals, semantic-state colors and data-series palettes are listed but
  not counted. Check text contrast on its actual background: at least 4.5:1,
  or 3:1 for large type. A composed frame that adds more than one accent
  family beyond the product or brand palette, or misses contrast, is REVISE
  before render.

## Anti-slide evidence, not keyword approval

Record `anti_slide_review` from actual segment and transition evidence. Compare
adjacent shots' hierarchy, focal geometry, media, pose and rhythm. Reject repeated
headline/card/rail grammar when every shot is a centered title plus the same
boxes/rail with only text/color swapped. Do not repair it by sprinkling particles
or changing a palette. Recompose the narrative around the evidence/semantic object,
change medium/focal scale/camera purpose, or remove an unnecessary card. A coherent
recurring motif is valid when it develops meaning; justify that from the output,
not a checklist keyword or numeric quality score.

Name strongest and weakest scenes, why each succeeds/fails, and keep/fix/rebuild
for every segment. Reserve actual iteration/time budget to rebuild the weakest.
When the weakness is the subject itself (the feature shown is thin, not its
staging), record `product_gap` with the capability the film needs and report
it to the user as a product change; do not spend the budget on particles,
glow, palette or camera moves to hide it.
`before_after_and_boundaries` requires same-time before/after samples, consecutive
moving strips and both entry/exit cut boundaries from real renders. Re-render and
review the final encoded revision; approval of the earlier draft is not approval
of the new file. Budget exhaustion with unresolved defects means REVISE/HOLD.

## Four independent verdicts

`technical_verdict` binds final hash to decode/frame/color/audio/size observations.
`artistic_verdict` binds that SAME revision to actual delivery-size style, story,
material/motion/cut critique, source fidelity, anti-slide decision and rebuilt
weakest scene. `playback_verdict` needs observed full-speed viewing;
`listening_verdict` needs observed hearing of final audio, or reasoned not_applicable
for a muted brief. Missing required observations remain HOLD/not_observed.
Automated motion/loudness numbers, source inspection and tool names cannot fill
those fields. Native-language and accessibility review remain separately scoped.
A technique/locale fixture is never the complete commissioned film or evidence
that real product actions shown as concepts actually ran.
