> Translated in full from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6 `showreel/references/techniques.md` (MIT, Copyright (c) 2026 Minho Hwang (revfactory); `toolkit/LICENSE.upstream`, provenance in `toolkit/upstream-manifest.json`). Read it for verified techniques T10 to T22 (beat grids, data, counters, 3D UI, camera, match cuts, montage, end cards). `$S` is `toolkit/scripts` under the loaded skill directory. Commands here are upstream's; check the upstream command map in `toolkit/README.md` before running one. Content language follows `references/brief-and-locales.md`: Korean-first defaults apply only to Korean content, the craft bar applies to every locale; host install paths are placeholders here, upstream's default narration voice is named by role and chosen only through voice_policy, inline OMH notes mark where OMH policy overrides an upstream default, and the provider scripts are opt-in with the user's own key.

# Expressive technique catalog (continued)

T10 to T22. The common rules and the common helper code these fragments use are at the start of `references/craft-techniques.md`.

## T10. Beat grid tiles

32x18 cells (60px) with seven Bauhaus shapes (square, circle, quarter circle, half circle, triangle, two arcs, dot). For each cell, build an event list (flip, rot, pop) from the beat times in setup, and evaluate it in render with closed-form expressions.

```js
function cellAt(c, t) {                                  // c.ev is sorted by start time, ascending
  let face = c.f0, ang = 0, sx = 1, k = 1;
  for (const e of c.ev) {
    if (t < e.s) break;
    const x = (t - e.s) / e.dur;
    if (e.type === 'flip') { const p = x >= 1 ? 1 : ease.inOutExpo(x); if (p >= 0.5) face = e.to; if (x < 1) sx *= Math.abs(Math.cos(Math.PI * p)); }
    if (e.type === 'rot') { ang += e.d * Math.PI / 2 * (x >= 1 ? 1 : ease.outBack(x, 1.4)); if (x < 1) k *= 1 - 0.13 * Math.sin(Math.PI * x); }
    if (e.type === 'pop' && x < 1) k *= 1 + 0.1 * (1 - ease.outExpo(x));
  }
  return { face, ang, sx, k };
}
// ripple: split the time by distance 'rank' so the number of cells flipping per frame stays constant (flash-safe)
const rank = cells.map((c, i) => [Math.hypot(c.c - 15.5, c.r - 8.5), i]).sort((a, b) => a[0] - b[0]);
rank.forEach(([, i], n) => cells[i].ev.push({ type: 'flip', s: E('ripple') - 3 * F + (12 * F * n) / (rank.length - 1), dur: 6 * F, to: pickFace(i) }));
```

**The most important caution**: when high-contrast tiles cover the screen and the whole grid rotates, inverts, or shifts at the same time, almost every such move crosses the flash threshold (in practice it produced 16 flashes in one second). Keep the area changing in each direction under 8% per frame, and express the beat with rotation, squash, and scale pulses instead of color inversion. Paint the accent color only on the cells that are moving right now.

## T11. Data pulse: continuous charts

Without cutting the scene, the elements become the next chart: ECG line -> x-axis -> ticks -> swatches -> bars -> dots -> line chart -> donut -> counter. Lines use `Path2D` + `shadowBlur 16`. Real values are computed in setup by reading JSON (for example `timeline.json` or research material).

```js
function ecg(u) {                                       // u = frames away from the R peak. The R peak sits on the beat frame
  let y = 0;
  if (u > -3.6 && u < -2.0) y += 0.075 * Math.sin((Math.PI * (u + 3.6)) / 1.6);
  if (u > -1.3 && u <= -0.8) y += (-0.07 * (u + 1.3)) / 0.5;
  else if (u > -0.8 && u <= 0) y += lerp(-0.07, 1, (u + 0.8) / 0.8);
  else if (u > 0 && u <= 2) y += lerp(1, -0.5, u / 2);
  else if (u > 2 && u <= 4) y += lerp(-0.5, 0, (u - 2) / 2);
  if (u > 5 && u < 8.5) y += 0.14 * Math.sin((Math.PI * (u - 5)) / 3.5);
  return y;
}
// at f0 the line head is already mid-screen (x 700) and the previous beat's R wave is already drawn (motion from the first frame)
const head = Math.min(1824, 700 + 24 * ctx.t * REEL.fps);
```

Caution: place 1px lines on +0.5 coordinates. An opaque canvas (`alpha: false`) causes color fringing on text. If the content is bunched on one side, fill the other side with a secondary chart.

## T12. Mechanical counter and slot roll

Give each digit a vertical 0-9-0 strip, and turn a higher digit only when the digit below it crosses 9->0. Erase the top and bottom 10% of the window with a gradient mask.

```js
const odoPos = (v, place) => { if (!place) return v; const d = 10 ** place, lo = ((v % d) + d) % d; return Math.floor(v / d) + clamp(lo - (d - 1), 0, 1); };
setup(el) {
  this.box = h('div', 'num', el); this.wheels = [];
  for (let k = 0; k < 3; k++) {
    const win = h('span', '', this.box), strip = h('span', '', win, [...'01234567890'].map((d) => `<span>${d}</span>`).join(''));
    css(win, { display: 'inline-block', overflow: 'hidden', height: '1em', verticalAlign: 'top', maskImage: 'linear-gradient(transparent, #000 10%, #000 90%, transparent)' });
    css(strip, { display: 'flex', flexDirection: 'column', lineHeight: 1 });
    this.wheels.push(strip);
  }
},
render(lt, ctx) {
  const v = lerp(0, 256, prog(ctx.t, cue('count') - 0.9, 0.9, ease.outQuart));     // lands on the cue
  this.wheels.forEach((w, k) => css(w, { transform: `translateY(${-(odoPos(v, 2 - k) % 10)}em)` }));
}
```

Use a monospaced typeface or `tabular-nums`. Fast-spinning digits can look doubled under `--sub`.

## T13. Pixel-to-particle dissolve

Draw the screen just before the transition offscreen, gather opaque pixel candidates at 3px spacing, shuffle them with `rand`, and pick 200. Destinations must be assigned **in the original x order** so the paths do not cross. The particles are sucked in along a quadratic Bezier (control point = between start and destination + random) with inQuart, and on arrival each one turns on the line segment it is responsible for. Use `getImageData` only once, in setup.

## T14. 3D device UI flow

Use: scenes of using a product, app, or tool (question -> choice -> generation -> done).

Stage `perspective: 2400px`, device `preserve-3d`. Interpolate the pose (x, y, ry, rx, s) with `kf` and add floating (±4px, ±0.8°). Inside the screen is a real DOM UI.

```js
const pose = (t) => ({
  x: kf(t, [[0, 1380], [cue('land'), 960, ease.outExpo], [cue('exit'), 960], [cue('exit') + 16 * F, 1340, ease.inOutExpo]]),
  ry: kf(t, [[0, -62], [cue('land'), -18, ease.outExpo], [cue('detail'), 14, ease.inOutCubic]]), rx: 8 + 0.5 * noise(t * 0.8, 3), s: 1,
});
const p = pose(ctx.t);
css(this.phone, { transform: `translate(${p.x - 220}px, ${88 + 4 * Math.sin(TAU * ctx.t / 4.6)}px) rotateY(${p.ry + 0.8 * Math.sin(TAU * ctx.t / 7.7)}deg) rotateX(${p.rx}deg) scale(${p.s})` });
// touch indicator: 1.2→1.0 just before the press, 0.85 while pressed, grows to 1.15 and fades out on release
const tp = ctx.t - cue('tap');
const sc = tp < -4 * F ? 0 : tp < 0 ? lerp(1.2, 1, ease.outQuart(clamp((tp + 4 * F) / (4 * F)))) : tp < 6 * F ? 0.85 : 0.85 + 0.3 * ease.outQuart(clamp((tp - 6 * F) / (7 * F)));
```

A shared-element expansion interpolates the card rectangle (x, y, w, h, r) to the header rectangle with inOutExpo over 16 frames, with the image inside set to `object-fit: cover`. Confetti uses the closed form for air drag + gravity: `x = x0 + vx(1−e^(−ku))/k`, `y = y0 + (g/k)u + (vy − g/k)(1−e^(−ku))/k`.

Caution: a translucent white touch circle on a bright UI is invisible (add a dark 1px outline). Bake static SVG icons into bitmaps in setup. If the device is smaller than 25% of the screen, use T15 at the key moment.

## T15. Punch-in camera

Use: when the subject of the key moment is smaller than 25% of the screen and hard to see.

Apply a 2D scale with the screen coordinates of an anchor (a button, a point in the data, a building) as the `transform-origin`. Both going in and coming out, arrive on the cue frame with `ease.inOutCubic`. During a riser, slowly raise the scale further from 1.30 to 1.38. Pulling the background back by 3% in the opposite direction creates depth.

```js
const z = 1 + 0.45 * (prog(t, cue('like') - 8 * F, 8 * F, ease.inOutCubic) - prog(t, cue('toast') + 2 * F, 10 * F, ease.inOutCubic));
css(this.camera, z === 1 ? { transform: 'none' } : { transformOrigin: `${ax}px ${ay}px`, transform: `scale(${z.toFixed(4)})` });
css(this.bg, { transformOrigin: `${ax}px ${ay}px`, transform: `scale(${1 - 0.03 * (z - 1) / 0.45})` });
```

Going in with outExpo arrives 4 frames before the cue and reads as early. Returning with inOutExpo moves the edges more than 100px per frame, which even blur cannot hide.

## T16. Circular match cut, iris, and 2.5D parallax

- 2.5D: for each photo, layer the cutout (`prep_images.py --cutout`) over the background; move the cutout with scale 1.00->1.06 and x +12px, and the background with 1.02 and x -6px (inOutSine). Put the pivot at the point where the subject touches the ground.
- Iris: animate the r of `clip-path: circle(r at x y)` from the original circle's radius to the distance to the screen corner with inOutExpo, and grow a 2px accent-color ring along with it.
- Match cut: set the starting scale so that the next scene's circle (a glass rim, a pupil, a clock) has the same position and size as the previous scene's circle (`z0 = r_prev / r_new`), and release it with outExpo over 1 beat.

```js
const cover = (x, y) => Math.max(Math.hypot(x, y), Math.hypot(REEL.W - x, y), Math.hypot(x, REEL.H - y), Math.hypot(REEL.W - x, REEL.H - y)) + 6;
const p = prog(ctx.t, E('wipe'), 0.75, ease.inOutExpo), [cx, cy, r0] = this.circle, r = lerp(r0, cover(cx, cy), p);
css(this.next, { clipPath: p <= 0 ? 'circle(0px at 0 0)' : `circle(${r}px at ${cx}px ${cy}px)` });
```

Measure the circle coordinates for each photo and keep them in a table. If the generation prompt specifies where the circle to match should sit, less zoom is needed. Put a cross-dissolve only in the 2 frames after the cut.

## T17. Procedural steam and smoke

On a quarter-resolution (480x270) canvas, compute a domain-warped fbm ribbon density, composite it in white at 15-30% with `screen`, and upscale it with CSS. The rise is `ny = q.y − t·rise`, and the sway is proportional to height. The pixel loop is heavy, so compute only a rectangle around the emitter. Original code: `production/reels/morning-brew/` in the isometric-web project.

## T18. Beat montage

- Extract only the needed section of the source as a JPG sequence with ffmpeg (do not use the `<video>` element; it is not frame-accurate): `ffmpeg -ss 7.0 -i in.mp4 -frames:v 45 -vf fps=30 -q:v 2 assets/seq/a/%04d.jpg`. Preload it in setup with `REEL.img`.
- Advance the cut on every beat. Transitions: a 1-2 frame white flash (once per bar), a zoom punch (1.08->1.00, 4 frames), a whip pan (incoming side 4 frames: 8% shift + 40px horizontal blur, outExpo).
- The drop is a 3x3 grid: the cells slam in one per beat with scale 0.6->1 and a clip that opens from a horizontal line, and the center cell is accent color + a number.
- If you put labels on the cuts, their shape, typeface, and position are set by that section's art direction.

```js
const frame = (seq, t0, t, rate = 1) => seq[clamp(Math.floor((t - t0) * REEL.fps * rate), 0, seq.length - 1)];
function whip(g, img, k) {                                  // k: 1 (start) → 0 (stopped). Draw the same image 9 times, shifted; the average = horizontal blur
  const shift = 0.08 * REEL.W * k, blur = 40 * k, sc = 1 + (2 * (shift + blur / 2)) / REEL.W, n = blur > 1 ? 9 : 1;
  for (let i = 0; i < n; i++) {
    g.globalAlpha = 1 / (i + 1);
    g.setTransform(sc, 0, 0, sc, REEL.W / 2 * (1 - sc) + shift + (n > 1 ? blur * (i / (n - 1) - 0.5) : 0), REEL.H / 2 * (1 - sc));
    g.drawImage(img, 0, 0, REEL.W, REEL.H);
  }
  g.globalAlpha = 1; g.setTransform(1, 0, 0, 1, 0, 0);
}
```

How to choose with flashes in mind: measure in advance the ratio of bright pixels (linear luminance >= 0.1) in the first and last frames of each candidate. Choose mostly dark scenes for consecutive cuts, and send bright scenes to grid cells (9% of the screen).

## T19. Afterimage and directional blur

1. For the final render use `render.mjs --sub 4` (180° shutter). In that case, put the event time of hard cuts and state changes at `E('cue')` (cue - 0.5 frame).
2. Stylized afterimage: call the same state function again at t - 2/3 frame and t - 1/3 frame and overlay them at 15% and 30%. Use it only on elements that move more than 40px per frame.
3. To smear just one element: the per-axis standard deviation of an SVG `feGaussianBlur` = min(26, 0.145 x speed in px/frame).

Using `--sub` and afterimages together smears too much. For large text over 150px, blur is cleaner than afterimages.

## T20. Flash-safe rhythm

Follow the flash item in "Common rules". The flash verdict of `motion_check.py` (draft) and `qa_check.py` (finished cut) is based on screen area (if pixels whose brightness changed by more than 0.1 between adjacent frames cover 10% or more of the screen, that is a transition; two transitions in opposite directions make one flash; more than 3 per second fails). When a failing section appears, split the area of simultaneous change in that section. Motion blur (`--sub 4`) blends a cut across two frames, which adds transitions. In a comparison experiment, a section that passed with `--sub 1` failed in the `--sub 4` master. It passed once the cut was replaced with a diagonal wipe (6-7 frames) and the slide distance was reduced.

## T21. Dither and grain

Wide gradients, glows, and blooms on a dark background develop banding (steps). In setup, build a screen-fixed dither (2x2 blocks, ±2 code values) once and lay it on top with `overlay`. Do not change it per frame. Dither and grain greatly increase file size, so raise the CRF by 1-2 for files meant for sharing.

```js
REEL.overlay(() => {}, { setup(el) {
  const c = h('canvas', '', el); c.width = REEL.W; c.height = REEL.H; const g = c.getContext('2d'), im = g.createImageData(REEL.W, REEL.H);
  for (let y = 0; y < REEL.H; y++) for (let x = 0; x < REEL.W; x++) {
    const v = 128 + (rand((y >> 1) * 4096 + (x >> 1), 17) < 0.5 ? -2 : 2), i = (y * REEL.W + x) * 4;
    im.data[i] = im.data[i + 1] = im.data[i + 2] = v; im.data[i + 3] = 255;
  }
  g.putImageData(im, 0, 0); css(c, { position: 'absolute', inset: 0, mixBlendMode: 'overlay', opacity: 0.6, pointerEvents: 'none' });
} });
```

## T22. Signature end card and hold

This is the code for building an end card from a plate reveal and three chunks of text. The concept decides what the final screen looks like. The plate is revealed from the left with `clip-path: inset(0 X% 0 0)` (X 100->0, outExpo 10 frames), and the accent square pops with outBack over 6 frames. The three text chunks come in staggered by 2 frames each, with opacity 0->1 and `top` +12px->0 (outQuart 6 frames). After that the card holds almost still until the end (drift of 2px or less). The final hit is sound only.

```js
const T0 = REEL.duration - 2.0;
render(lt, ctx) {
  const t = ctx.t;
  css(this.plate, { clipPath: `inset(0 ${100 * (1 - prog(t, T0, 10 * F, ease.outExpo))}% 0 0)` });
  css(this.sq, { transform: `scale(${prog(t, T0 + 2 * F, 6 * F, ease.outBack)})` });
  this.parts.forEach((el, i) => { const p = prog(t, T0 + (4 + 2 * i) * F, 6 * F, ease.outQuart); css(el, { opacity: p, top: `${12 * (1 - p)}px` }); });
}
```

If the text entrance uses `transform: translateY`, the compositing layer from the previous frame is reused, and the edges can differ depending on render order. Move text in the hold section with `top`.
