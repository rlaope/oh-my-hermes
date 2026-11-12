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

## Concept first, techniques second

The technique catalog is verified code, not a menu: a film assembled only from it
looks like every other film made with this skill. Start from the segment's art
direction in `concept.md`; take a technique when the concept needs that exact
expression and adapt its palette, type and motion, otherwise build new. Adjacent
segments should differ in at least two of medium, palette, typeface, motion and
texture. Repeated shuffled seeks must yield identical decoded pixels at the same
times in the pinned environment; report the executed fixture rather than
extrapolating to every locale or platform.
