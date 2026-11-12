> Translated in full from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6 `showreel/references/techniques.md` (MIT, Copyright (c) 2026 Minho Hwang (revfactory); `toolkit/LICENSE.upstream`, provenance in `toolkit/upstream-manifest.json`). Read it for the sync, first-frame, flash and determinism rules, common helper code and verified techniques T01 to T09. `$S` is `toolkit/scripts` under the loaded skill directory. Commands here are upstream's; check the upstream command map in `toolkit/README.md` before running one. Content language follows `references/brief-and-locales.md`: Korean-first defaults apply only to Korean content, the craft bar applies to every locale; host install paths are placeholders here, upstream's default narration voice is named by role and chosen only through voice_policy, inline OMH notes mark where OMH policy overrides an upstream default, and the provider scripts are opt-in with the user's own key.

# Expressive technique catalog

These are the techniques used in the isometric-web project (nine 15-second showreels: isometric city, Hangul kinetic type, beat grid, data pulse, UI flow, glass type, voxel light, live-action ad, and a composite showreel), ported into code for this skill's engine (`REEL`). If the original footage (`content/reels/<slug>/video.mp4` in the isometric-web project) is available, check against that file.

This document is not a list for planning scenes; it is a collection of code fragments that have already been verified. A scene starts from the art direction and technical challenges in `concept.md`. If the expression you need is here, take the code and adapt it to that section's palette, typeface, and motion. If it is not, build it new. A video that only combines techniques from this list will look like the other videos made with this skill.

WebGL shaders, three.js 3D, and precomputed simulations are in `craft-engine.md`. The "Common rules" at the front (sync, first frame, flashes, determinism) also apply to every scene you build new.

## Contents

- Common rules: sync, first frame, flashes, determinism
- Common helper code
- T01 Isometric voxel city / T02 Day-to-night grading / T03 Tilt-shift and number-to-title morph
- T04 Particle type / T05 Hangul jamo assembly / T06 Variable-weight pumping / T07 Slam title card
- T08 Glass and chrome dimensional type / T09 Prismatic light streak
- T10 Beat grid tiles / T11 Data pulse / T12 Mechanical counter / T13 Pixel-to-particle dissolve
- T14 3D device UI flow / T15 Punch-in / T16 Circular match cut and 2.5D parallax / T17 Procedural steam
- T18 Beat montage / T19 Afterimage and directional blur / T20 Flash-safe rhythm / T21 Dither and grain / T22 Signature end card

## Common rules

**Sync.** Align the frame where a new state first becomes visible with the cue frame. The picture must never lead the sound.

- If you use `ease.snap` (expo.out) or outBack so that it "ends on the cue", the result becomes visible 3-5 frames early. Start it *on* the cue, or align the frame where the scale first reaches 1.0 with the cue.
- Put the event time of a hard cut or state transition at `cue - 0.5 frame`. The shutter of `render.mjs --sub` spans 0.25 frame before and after the frame time, so this keeps the new state from blending into the frame just before the cue.
- Camera moves arrive exactly on the cue with `ease.inOutCubic`.

**First frame.** The concept decides how the video opens. To have the screen filled and moving from the 0-second frame, use the methods below. Do not open with an unintended blank frame or fade-in.

- Let time run from before 0 seconds. For example: at 0 seconds a line is already drawn halfway across the screen, and the waveform of the first beat is already visible.
- If you open with a drop (inExpo), the first 4-5 frames barely move. Start with the first piece already partly on screen.

**Flashes.** Keep changes in which 10% or more of the screen rises or falls in brightness by more than 0.1 to 3 or fewer per second.

- Express beats with position, rotation, scale, and weight instead of color inversion.
- Split motions in which the whole screen changes at once into subsets (half of a checkerboard, a quarter of 2x2 cells).
- Use a white flash at most once per bar.

**Determinism.** Rendering the same time in any order must produce the same picture.

- Do not use `will-change`.
- For the `visibility` of child elements, use only `inherit`.
- Bake static SVG illustrations into bitmaps in setup (there has been a case where Chrome's raster cache drew edges differently depending on render order).
- Do not use `border-radius` or a blurred `box-shadow` on small rotating elements.
- Apply 3D transforms only in the sections that need them.

## Common helper code

```js
const { ease, prog, kf, clamp, lerp, rand, noise, pulse, css, h, s, cue } = REEL;
const F = 1 / REEL.fps, TAU = Math.PI * 2;
const E = (name) => cue(name) - 0.5 * F;                 // event time: so the new state first appears on the cue frame
const BEATS = REEL.TL.music?.beats || [];                 // produced by timeline.py --music-analysis
const SPB = 60 / (REEL.TL.music?.bpm || 120);             // beat length (seconds)
const beat = (n) => BEATS[n] ?? n * SPB;                  // time of the nth beat
function cv(el, w = REEL.W, hh = REEL.H) {               // one canvas per scene (keep it an alpha canvas and paint the background yourself)
  const c = h('canvas', '', el); c.width = w; c.height = hh;
  css(c, { position: 'absolute', left: 0, top: 0, width: w + 'px', height: hh + 'px' });
  return c.getContext('2d');
}
const hex = (str) => [1, 3, 5].map((i) => parseInt(str.slice(i, i + 2), 16));
const toLin = (v) => ((v /= 255) <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
const toSrgb = (v) => 255 * (v <= 0.0031308 ? v * 12.92 : 1.055 * v ** (1 / 2.4) - 0.055);
const poly = (g, pts, rgb, k = 1) => {                    // polygon + 0.6px outline in the same color (fills the gaps between faces)
  g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath();
  g.fillStyle = `rgb(${rgb.map((v) => Math.min(255, v * k) | 0)})`; g.fill();
  g.strokeStyle = g.fillStyle; g.lineWidth = 0.6; g.stroke();
};
```

Setting the BPM to 120 (15 frames per beat) or 90 (20 frames per beat) makes beats fall on whole frames and reduces rounding problems. Set the bpm in the music spec (`audio/music/spec.json`) that way.

## T01. Isometric voxel city

Use: showing the overall structure with one building per scene, system and pipeline structure diagrams, openings, data clusters.

Rotate the ground coordinates (x, y, z) by the azimuth az, then project orthographically at the elevation el (true isometric 35.264°, 2:1 pixel isometric 26.565°). For each box draw only the two side faces that face the camera and the top face, and draw the buildings in depth order. Spread the rise delay evenly by distance *rank* (making it proportional to distance bunches it up in the outer ring).

```js
const ISO = { s: 30, cx: 960, cy: 600, el: 35.264 * Math.PI / 180 };
function iso(x, y, z, az) {                       // → [screen x, screen y, depth]
  const c = Math.cos(az), sn = Math.sin(az), u = x * c - y * sn, v = x * sn + y * c;
  return [ISO.cx + u * ISO.s, ISO.cy + v * ISO.s * Math.sin(ISO.el) - z * ISO.s * Math.cos(ISO.el), v];
}
function box(g, b, hgt, az, light, rgb) {          // b = {x, y, w, d}
  const P = (a, q, z) => iso(b.x + a, b.y + q, z, az), c = Math.cos(az), sn = Math.sin(az);
  const sides = [[[0, -1], [0, 0], [b.w, 0]], [[1, 0], [b.w, 0], [b.w, b.d]], [[0, 1], [b.w, b.d], [0, b.d]], [[-1, 0], [0, b.d], [0, 0]]];
  for (const [[nx, ny], [a0, q0], [a1, q1]] of sides) {
    if (nx * sn + ny * c <= 0) continue;           // back face
    poly(g, [P(a0, q0, 0), P(a1, q1, 0), P(a1, q1, hgt), P(a0, q0, hgt)], rgb, light([nx, ny, 0]));
  }
  poly(g, [P(0, 0, hgt), P(b.w, 0, hgt), P(b.w, b.d, hgt), P(0, b.d, hgt)], rgb, light([0, 0, 1]));
}
REEL.scene({ id: 'city', start: cue('scene.city'), end: cue('scene.city.end'),
  setup(el) {
    this.g = cv(el); this.B = [];
    for (let gx = -6; gx <= 6; gx++) for (let gy = -6; gy <= 6; gy++) {
      const i = (gx + 6) * 13 + gy + 6; if (rand(i, 1) < 0.25) continue;      // empty cell = road/plaza
      this.B.push({ i, x: gx * 1.25, y: gy * 1.25, w: 0.95, d: 0.95, H: 0.5 + 4.5 * rand(i, 2) ** 2, r: Math.hypot(gx, gy) });
    }
    this.B.sort((a, b) => a.r - b.r).forEach((b, k, A) => (b.delay = k / A.length));
  },
  render(lt, ctx) {
    const g = this.g;
    const az = Math.PI / 4 + 0.5 * Math.sin(Math.PI / 2 * Math.min(lt / 9, 1));   // orbit that decelerates to a stop
    g.fillStyle = '#0b0e1a'; g.fillRect(0, 0, REEL.W, REEL.H);                  // or T02 paintSky
    const order = this.B.map((b) => [iso(b.x + b.w / 2, b.y + b.d / 2, 0, az)[2], b]).sort((p, q) => p[0] - q[0]);
    for (const [, b] of order) {
      const hgt = b.H * prog(lt, 0.2 + 1.4 * b.delay, 0.5, ease.outBack);
      if (hgt > 0.01) box(g, b, hgt, az, (n) => 0.45 + 0.5 * Math.max(0, n[0] * 0.6 + n[1] * -0.3 + n[2] * 0.8), [46, 56, 96]);
    }
  } });
```

Window lights switch on and off with a different period for each window, and the lit ratio is a function of time (higher toward night). Neon outlines draw the edges of the top face with `shadowBlur`.

Caution: depth-order sorting is only correct when the footprints are cells of the same size that do not overlap (split long buildings into cells). `--sub 4` makes rendering 4 times slower. Bring the camera orbit to zero velocity before the end hold.

## T02. Day-to-night timelapse grading

Use: showing the passage of time, such as a day, a production process, or a chronology; going from a bright start to a dark climax.

Keep the sky's top and horizon colors and the sun's altitude, azimuth, and intensity in a key table, and interpolate **in linear light** (mixing directly in sRGB makes the middle muddy and the brightness change uneven). Face brightness is `ambient + diffuse·max(0, n·sun)`.

```js
const SKY = [[0, '#F4A6C0', '#FFD3B0'], [2.5, '#BFDDF2', '#EAF4FA'], [5, '#9FD3F2', '#DDF0FA'], [7.5, '#FF9A4D', '#FFC98A'],
  [8.75, '#C0607A', '#FF9A6A'], [9.7, '#4A3C78', '#C2567A'], [10, '#141A2E', '#1F2742'], [12.5, '#0B0E1A', '#07090F']];
function mixKeys(keys, x, col) {
  if (x <= keys[0][0]) return hex(keys[0][col]);
  for (let i = 1; i < keys.length; i++) if (x <= keys[i][0]) {
    const p = (x - keys[i - 1][0]) / (keys[i][0] - keys[i - 1][0]), A = hex(keys[i - 1][col]), B = hex(keys[i][col]);
    return A.map((v, j) => toSrgb(lerp(toLin(v), toLin(B[j]), p)));
  }
  return hex(keys[keys.length - 1][col]);
}
function paintSky(g, x) {                          // x: time in the key table (stretch it to fit the scene length)
  const gr = g.createLinearGradient(0, 0, 0, REEL.H);
  gr.addColorStop(0, `rgb(${mixKeys(SKY, x, 1).map(Math.round)})`); gr.addColorStop(1, `rgb(${mixKeys(SKY, x, 2).map(Math.round)})`);
  g.fillStyle = gr; g.fillRect(0, 0, REEL.W, REEL.H);
}
```

The clock HUD builds its digits from the same time function (`HH:MM`, a monospaced typeface, the colon `pulse`s on each beat). At dusk, switch the HUD text color from ink to white and lay a 10% darker circular backing behind the text. Covering the night screen with more than 70% darkness puts out the lights that are the subject.

## T03. Tilt-shift and number-to-title morph

Tilt-shift: layer 2, 4, and 6px blurs on only the top 22% and bottom 18% bands so it looks like a diorama. Applying `filter: blur` to the whole screen costs hundreds of ms per frame.

Morph: the `:00` of the HUD digits (`24:00`) folds around the baseline axis (rotateX 0->90°, inExpo 4 frames), and `시` (hour) unfolds in the same spot (-90->0°, outExpo 4 frames). The same digits cross over from the monospaced typeface to the body typeface. Apply the 3D transform only while folding.

```js
const T = cue('midnight'), fold = prog(ctx.t, T, 4 * F, ease.inExpo), unf = prog(ctx.t, T + 4 * F, 4 * F, ease.outExpo);
css(this.c00, { transformOrigin: '50% 82%', transform: fold > 0 && fold < 1 ? `perspective(600px) rotateX(${90 * fold}deg)` : 'none', opacity: fold >= 1 ? 0 : 1 });
css(this.si, { transformOrigin: '50% 82%', transform: unf > 0 && unf < 1 ? `perspective(600px) rotateX(${-90 + 90 * unf}deg)` : 'none', opacity: unf > 0 ? 1 : 0 });
```

## T04. Particle type: formation, explosion, galaxy, re-formation

Use: the biggest impact for a keyword's entrance, stories of breaking apart and being rebuilt (transformation, generation), drop sections.

In setup, draw the text offscreen and sample points from its pixels. Compute positions for each state with closed-form expressions: inflow outQuart, jitter `noise`, decelerating explosion `a + v·τ(1−e^(−Δt/τ))`, galaxy `θ = arm + r·k + (1.2/√r)·Δt` (the inside moves faster), implosion inQuart, re-formation outExpo (starting from the leftmost letter). **Blend between states in polar coordinates** (linear interpolation turns into square clumps).

```js
function glyphPoints(text, font, step = 6) {       // in setup (fonts are already loaded)
  const g = document.createElement('canvas'); g.width = REEL.W; g.height = REEL.H;
  const c = g.getContext('2d', { willReadFrequently: true });
  c.font = font; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillStyle = '#fff'; c.fillText(text, REEL.W / 2, REEL.H / 2);
  const d = c.getImageData(0, 0, REEL.W, REEL.H).data, on = (x, y) => d[(y * REEL.W + x) * 4 + 3] > 127, pts = [];
  for (let y = 4; y < REEL.H - 4; y += step) for (let x = 4; x < REEL.W - 4; x += step) if (on(x, y)) pts.push([x, y]);
  return pts;
}
// render: derive velocity from the position at the previous time (t − 1/60) to set the stretch length, draw with 'lighter', then add a quarter-resolution bloom
const [x, y] = pos(i, t), [px, py] = pos(i, t - 1 / 60), vx = (x - px) * 60, vy = (y - py) * 60, sp = Math.hypot(vx, vy);
const L = 1 + 6 * Math.min(1, sp / 1500);
g.lineWidth = 3.2 / Math.sqrt(L); g.beginPath(); g.moveTo(x, y); g.lineTo(x - (sp > 1 ? vx / sp * 3 * L : 1), y - (sp > 1 ? vy / sp * 3 * L : 0)); g.stroke();
```

The calculation for the simplest form (inflow -> letter swap) is in the setup and render code of the end card in `reel/_example_scenes.js`. Do not copy its color, typeface, or composition. Caution: random pairing tangles the paths (pair particles by radius rank). Large particles flying close to the screen look like confetti, so draw them thinner the more they stretch. Above 10,000 particles it takes tens of ms per frame.

## T05. Hangul jamo assembly

Use: the opening of a Korean-language video, a brand-name reveal, a message about parts coming together into one.

Method without preprocessing: stack as many copies of the same syllable DOM as there are pieces, clip each to its jamo region with `clip-path: inset()`, and animate them separately. All the pieces together equal the original glyph, so the resting state is perfect. Choose the regions by the type of medial vowel (jungseong).

```js
const VERT = new Set([0, 1, 2, 3, 4, 5, 6, 7, 20]);        // ㅏㅐㅑㅒㅓㅔㅕㅖㅣ: initial (choseong) left | medial (jungseong) right
const MIX = new Set([9, 10, 11, 14, 15, 16, 19]);          // ㅘㅙㅚㅝㅞㅟㅢ
function jamoRegions(ch) {                                  // [x0, y0, x1, y1] (fractions of the glyph box). Check with stills and adjust per typeface
  const c = ch.charCodeAt(0) - 0xac00; if (c < 0 || c > 11171) return [[0, 0, 1, 1]];
  const jung = Math.floor((c % 588) / 28), jong = c % 28, yb = jong ? 0.6 : 1;
  const top = VERT.has(jung) ? [[0, 0, 0.56, yb], [0.56, 0, 1, yb]]
    : MIX.has(jung) ? [[0, 0, 0.62, yb * 0.52], [0, yb * 0.52, 0.62, yb], [0.62, 0, 1, yb]]
    : [[0, 0, 1, yb * 0.52], [0, yb * 0.52, 1, yb]];        // ㅗㅛㅜㅠㅡ
  return jong ? [...top, [0, yb, 1, 1]] : top;
}
REEL.scene({ id: 'jamo', start: 0, end: cue('scene.jamo.end', 6),
  setup(el) {
    this.pieces = []; let k = 0;
    [...'쇼릴'].forEach((ch, ci) => jamoRegions(ch).forEach(([x0, y0, x1, y1]) => {
      const p = h('div', 'display', el, ch);
      css(p, { position: 'absolute', left: `${700 + ci * 280}px`, top: '400px', fontSize: '260px', lineHeight: 1,
        clipPath: `inset(${y0 * 100}% ${(1 - x1) * 100}% ${(1 - y1) * 100}% ${x0 * 100}%)` });
      const side = rand(k, 1) < 0.5;
      this.pieces.push({ el: p, k, dx: side ? (rand(k, 2) < 0.5 ? -1 : 1) * 700 : 0, dy: side ? 0 : -620 - 200 * rand(k, 3), slide: side });
      k++;
    }));
  },
  render(lt, ctx) {
    const t = ctx.t;
    this.pieces.forEach((p) => {
      const L = 0.4 + p.k * SPB / 2 - 0.5 * F;                                     // one piece lands on every eighth note
      const k = t >= L ? 0 : p.slide ? 1 - ease.outExpo(clamp((t - (L - 3 * F)) / (10 * F)))   // slide: the first 3 frames of a 10-frame curve
                                     : 1 - ease.inExpo(clamp((t - (L - 8 * F)) / (8 * F)));    // drop: inExpo 8 frames
      const q = t < L ? 1 : t < L + 3 * F ? 0.86 : lerp(0.86, 1, ease.outBack(clamp((t - L - 3 * F) / (4 * F))));   // landing squash
      css(p.el, { transform: `translate(${p.dx * k}px, ${p.dy * k}px) scale(${1 + (1 - q) * 0.5}, ${q})`, transformOrigin: '50% 100%',
        color: t < L ? 'var(--accent)' : 'var(--ink)' });
    });
  } });
```

Precise method: extract the syllable outlines with fontTools in three weights (100, 400, 900) and group the contour indices into jamo pieces (`production/reels/hangul-kinetic/` in the isometric-web project). Typing method: swap '한' (han) in as ㅎ -> 하 -> 한 (`String.fromCharCode(0xAC00 + cho*588 + jung*28 + jong)`).

Caution: let a changing color settle over 4 frames after landing. Flying hundreds of pieces all to one place tangles them. Fly only the hero pieces and let the rest shrink and disappear.

## T06. Variable-weight pumping and weight waves

Change the `'wght'` of Pretendard Variable (45-920) per character. On the kick every character hits 900 at the same time, and only the release is delayed by x position so that a wave flows through.

```js
const b = BEATS.filter((x) => x - F <= ctx.t).pop() ?? -99;           // most recent beat
this.chars.forEach((c, i) => {
  const atk = clamp((ctx.t - (b - F)) / (3 * F)), rel = clamp((ctx.t - (b + 2 * F) - i * 0.025) / (SPB - 3 * F));
  const w = atk < 1 ? lerp(200, 900, ease.outExpo(atk)) : lerp(900, 200, ease.inOutSine(rel));
  css(c, { fontVariationSettings: `'wght' ${w.toFixed(1)}` });
});
// syllable grid (u, v): w = 100 + 800·(0.5 + 0.5·cos(2π(beatPhase − off))), switching off from the diagonal (u+v)/8 to the radial hypot(u−cx, v−cy)/8
```

Caution: changing the weight changes the width of Latin letters. Put them in fixed-width cells (Pretendard Hangul syllables have the same width regardless of weight). A large area blinking 900<->100 on every beat becomes a flash.

## T07. Slam title card

A bold display typeface on a full-bleed accent-color background. Syllables slam in from 1.6x on every eighth note (outExpo 5 frames, event = cue - 0.4 frame), and each time one lands the whole line re-centers. The card shakes 4px on every beat, turning the direction each time. The exit sinks for 3 frames, then pulls up and out with inExpo over 4 frames while stretching vertically to 1.3x.

```js
const LEAD = 0.4 * F;
const slam = (t, c, from = 1.6, dur = 5 * F) => lerp(from, 1, ease.outExpo(clamp((t - (c - LEAD)) / dur)));
// in setup, measure the prefix width (prefixW) for each syllable; in render, re-center the line with the width for the n syllables that have landed
const cx = REEL.W / 2 - lerp(this.prefixW[Math.max(0, n - 1)], this.prefixW[n], ease.outExpo(clamp((t - (hits[n - 1] - LEAD)) / (5 * F)))) / 2;
```

Caution: if copy sits alone for more than 28 frames, the screen reads as frozen. Combine a letter-spacing tightening from -0.02 to -0.06em with a 1.00->1.03 push. Switching between a full accent-color card and a dark screen several times per second becomes a flash.

## T08. Glass and chrome dimensional type

Stack 24 layers of the same text with `translateZ(−1.6i px)` to build thickness (darker toward the back), give the front face a lighting-band gradient with `background-clip: text`, and rotate the band position over time. Chrome is a sharp dark-white band-dark reflection; glass is a translucent front face + `-webkit-text-stroke` edges.

```js
setup(el) {
  css(el, { perspective: '1800px' });
  this.wrap = h('div', '', el); css(this.wrap, { position: 'absolute', left: '960px', top: '470px', transformStyle: 'preserve-3d' });
  for (let i = 23; i >= 0; i--) {
    const d = h('div', 'display', this.wrap, '마감');
    css(d, { position: 'absolute', fontSize: '220px', transform: `translate(-50%,-50%) translateZ(${-i * 1.6}px)`, color: `rgb(${12 + i * 0.6},${16 + i * 0.8},${34 + i * 1.6})` });
  }
  this.face = h('div', 'display', this.wrap, '마감');
  css(this.face, { position: 'absolute', fontSize: '220px', transform: 'translate(-50%,-50%)', color: 'transparent', WebkitBackgroundClip: 'text', backgroundClip: 'text',
    backgroundSize: '400% 100%', WebkitTextStroke: '1.5px rgba(214,232,255,.9)',
    backgroundImage: 'linear-gradient(100deg,#07090F 0%,#1F2742 22%,#F2F4FF 25%,#9EC5FF 28%,#141A2E 38%,#7B5CFF 52%,#0B0E1A 62%,#F2F4FF 64%,#0B0E1A 69%,#07090F 100%)' });
},
render(lt, ctx) {
  css(this.face, { backgroundPosition: `${(lt * 13) % 400}% 0` });
  const settle = prog(lt, ctx.dur - 2, 2, ease.inOutCubic);            // settle to face-on at the end
  css(this.wrap, { transform: `rotateY(${lerp(-26, 0, settle) + 3 * noise(lt * 0.4, 2) * (1 - settle)}deg) rotateX(${lerp(14, 6, settle)}deg)` });
}
```

For a floor reflection, duplicate the same structure with `scaleY(-1)` and apply `mask-image: linear-gradient(to bottom, rgba(0,0,0,.35), transparent 60%)`. Caution: beyond ±30° the steps between the layers show.

## T09. Prismatic light streak

An additive light streak runs along an edge line at about 245px per frame. The head is short and white; the tail trails long in sky blue. The rainbow spreads 16 wavelengths perpendicular to the line from 0 to 18px and fades out 1.00 -> 0.47 -> 0.22 over 3 frames.

```js
function streak(g, x0, y0, ang, head, amp, spread) {
  g.save(); g.globalCompositeOperation = 'lighter'; g.translate(x0, y0); g.rotate(ang);
  const core = g.createLinearGradient(head - 600, 0, head + 150, 0);
  core.addColorStop(0, 'rgba(158,197,255,0)'); core.addColorStop(0.8, `rgba(242,244,255,${amp})`); core.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = core; g.fillRect(head - 600, -3, 750, 6);
  for (let i = 0; spread > 0 && i < 16; i++) {
    const w = (i + 0.5) / 16, off = (w - 0.5) * spread;
    g.fillStyle = `hsla(${w * 0.8 * 360},100%,62%,${(amp * 1.9) / 16})`; g.fillRect(head - 420 + (w - 0.5) * spread * 6, off - 1, 840, 2);
  }
  g.restore();
}
const n = Math.floor((ctx.t - cue('glint')) * REEL.fps + 1e-4);
if (n >= 0 && n < 3) streak(g, 0, 591, Math.atan(-0.0844), 900 + 50 * n, [1, 0.47, 0.22][n], [4, 11, 18][n]);
```

T10 to T22 continue in `references/craft-techniques-2.md`.
