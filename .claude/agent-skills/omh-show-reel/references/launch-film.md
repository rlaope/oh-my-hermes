# Launch-film lane

## Select the lane, do not default to it

Use this opt-in page only after concept selection chooses a 60-120 s launch film
for a product the team can actually run and capture: a feature or mode release
shown working in its own UI. A promo or social clip of 15 s or less keeps the
one-scene rule in `references/craft-design.md` (Short promo clips); an explainer
keeps its own pacing; a hype teaser built from type alone takes
`references/kinetic-type.md`. Every source, rights, locale, capture and delivery
contract still applies: each UI shot comes from the product's own renderer or a
capture at a named revision, and every product fact on screen is cited.

## Act sheet before scenes

Write the acts with a time budget before any scene code, in `storyboard.md` or
the timing source. The shape below is a default to adapt, not a template to fill:

| Act | Share | Job |
| --- | --- | --- |
| Mark | 4-6% | The product mark alone on a quiet ground. |
| Title becomes the product | 6-8% | The feature name turns into the captured UI without a cut. |
| One honest loop | 25-30% | One complete real run: input, the work, the visible change, the result. |
| Escalating range | 15-20% | Three examples, each more ambitious or more visual than the last. |
| Turn | 15-18% | The product does something to itself or its own surface. |
| Reach | 6-10% | Where else it runs or plugs in; the only act that may use illustration. |
| Climax and close | 8-10% | Largest type of the film, then a small still tagline, then the mark again. |

Record per act: the captured source and revision, the one thing the viewer must
notice, the transition into the next act, and the act's music section.

## Devices that carry a launch film

- **Title becomes the product.** Stack copies of the feature name (seven to
  nine lines, staggered from the centre, a few pixels of deterministic offset
  per copy), drift the stack upward, bend the lowest lines back in perspective
  (`rotateX` about 35-55 degrees) while their colour shifts to the accent, and
  raise the captured window into the space they leave. The viewer sees one
  continuous move from name to product.
- **Anchored typing.** Measure the finished line in the actual renderer first,
  centre that measured width, fix the left edge, and reveal characters inside
  it, so the line never re-centres as it grows. Use a 2-3 px caret blinking on a
  stepped 0.5 s cycle. When the product takes a prompt, type the real prompt in
  the same field style: the prompt is the caption.
- **Two-tone escalation copy.** Connective words in a neutral weight and colour
  (`Like a`, `Or a`, `Even a`); only the noun arrives in the accent, unblurring
  from about 8 px over roughly 0.3 s. The escalation lives in the words and in
  the examples that follow them.
- **Bracket agent work with word cards.** A one-word card opens a long run
  (`Create`) and another closes it (`Ready`). Between them, show the log only as
  texture: cropped, scrolling and partly faded, never asked to be read. State
  the real duration or step count of the run you compressed in the delivery
  manifest.
- **One honest loop before any montage.** Show one full run end to end before
  fast cuts begin: the typed request, the reported change (for example a file
  count and a line diff taken from the captured screen), the new item where the
  product lists it, and the finished result. The montage borrows its credibility
  from this loop.
- **Close-ups only on decisions.** A tilted, slightly blurred-edge close-up and
  a visible cursor only where a person decides: a mode picker, a send button, a
  colour choice. Leave routine clicks at normal framing.
- **Window on a ground, not a device mock.** Present the captured window with a
  soft shadow over a blurred gradient ground. Enter from full frame by easing
  the scale from about 1.2 to 1 so the ground is revealed. Drop invented bezels.
- **Ration colour.** Keep the product chrome neutral and let colour arrive with
  results. Reserve full black for the opening mark and the close.
- **A planned breath.** One near-empty frame with only a blinking caret for two
  to three seconds before the last and heaviest montage resets attention.
  Declare it in the act sheet and as an intentional hold with a reason.
- **Climax by contrast.** The largest type of the film can overflow the frame
  and carry directional blur; cut straight from it to a small still tagline on a
  dark ground, then to the mark alone so the end rhymes with the first frame.
- **Choose results a viewer reads in two seconds.** A timer, a board of notes,
  a poster, a playable scene, a dashboard. Skip results that need reading.

## Gate before delivery

Render one still per act and the frames either side of each act boundary, and
check them as one sheet: is the title-to-UI move continuous, is the honest loop
complete, does each escalation step get bigger, is there exactly one breath, and
does the close rhyme with the open. Run `motion_check.py` with the general
profile, passing the breath and the end card through `--holds` and
`--endcard`. Keep the existing audio, loudness, export and artistic gates in
`references/render-qa-delivery.md`; a launch film is not exempt from any of them.

Method notes informed by a public frame-by-frame study of a 99 s product launch
film (DeepSeek Harness Creator Mode, https://x.com/DeepSeekHarness/status/2117256196227019194,
measured 2026-11-03: 27 detected cuts, 8 acts, about -16 LUFS integrated). OMH
wording; no footage, copy or assets were taken.
