# Engine contract and craft techniques

Read the local `toolkit/README.md`, then `references/craft-engine.md` (engine API,
scene authoring, WebGL and 3D, splitting work across agents) and
`references/craft-techniques.md` with `references/craft-techniques-2.md`
(verified technique code with the sync, first frame, flash and determinism
rules) before writing a scene. `new_project.py`
copies upstream's engine unmodified: `reel/engine.js` (`REEL`), `reel/fx.js`
(`FX` layers), `reel/_example_scenes.js` (an API example, not loaded) and an empty
`reel/scenes.js`. Helpers are source the scene calls, not scripts OMH executes.

## The contract the capture adapter checks

- The screen is a pure function of absolute time `t`. No `Math.random`,
  `Date.now`, CSS transition/animation, or state carried from the previous frame;
  use `REEL.rand(i, salt)` and `REEL.noise(t, seed)`. Precompute accumulating
  simulations in `setup` at fixed steps and read them by time in `render`.
- `REEL.config`, `REEL.scene({id,start,end,setup,render})`, `REEL.overlay`,
  `REEL.preload`/`REEL.img`, `REEL.cue`/`bar`/`beat`/`level`/`charTimes` read
  `reel/timeline.js`. Put times on cues, not literals, so re-timed audio carries
  the picture with it. Declare hard-cut seconds in `project.json` `cuts` at the
  actual scene boundaries; the cut-aware `--sub` shutter stays inside each shot,
  so the old `cue - 0.5 / fps` placement workaround is not needed.
- `window.__seek(t)`, `__ready` and `__meta` are the host capture contract, not a
  runtime RPC. The adapter refuses running animations, page errors, external
  requests, undeclared files and glyphs the declared fonts do not cover.

## Native scripts in motion

`REEL.split(el, 'char')` segments graphemes, which suits Hangul, CJK and Latin
kinetic type. Never split or reverse Arabic or another shaping script to imitate
a Latin stagger: animate intact runs or `split(el, 'word')`, with per-run
`lang`/`dir` and isolated literal LTR tokens. Anticipation and settling express
weight and arrival; they must not make essential text unreadable. Measure reading
time from delivery-size moving samples, not a character formula.

## Numbers, narrated items and camera moves

- `references/craft-design.md` (Motion principles) stamps a small value in at
  once because its intermediate values read as real values. The same reason
  decides which larger numbers may count: only one whose every intermediate
  value was true, such as a counted quantity, a clock, or a series moving
  through values it recorded. A measured or computed result, a price, a ratio
  or a multiplier appears at its final value on the cue where it is said or
  shown, because the values in between were never measured. When the earlier
  value is itself a fact, show it, strike it and set the new value in its
  place. A bar or gauge may grow; its numeric label appears when the growth
  ends.
- A value one scene ended on enters the next scene at that value. Counting it
  again from zero shows numbers below one the film already stated.
- In a narrated scene each listed item enters on the cue of the word that names
  it (`references/audio-production.md` gives where a narration cue comes from),
  not all at scene start: a list shown whole is read ahead of the voice. With
  no narration, items take beat or reading-time cues.
- A phrase (a narration line or a musical phrase) takes at most one camera move
  by default, so each move can be named by the phrase it serves. A second move
  inside it needs its own reason in the storyboard's movement field, where the
  first already has its intention.
- Compose a layout that will be pushed into at its end pose first, so that
  everything the viewer still needs is inside the safe area after the move,
  then pull back to the start pose.

## Concept first, techniques second

The technique catalog is verified code, not a menu: a film assembled only from it
looks like every other film made with this skill. Start from the segment's art
direction in `concept.md`; take a technique when the concept needs that exact
expression and adapt its palette, type and motion, otherwise build new. Adjacent
segments should differ in at least two of medium, palette, typeface, motion and
texture. Repeated shuffled seeks must yield identical decoded pixels at the same
times in the pinned environment; report the executed fixture rather than
extrapolating to every locale or platform.
