/*!
 * omher.app top block: a soft pink aura behind the app window.
 * Pink light (#ff5fa2 into #e04ce0, violet only at the faint outer edge) falls from above and pools behind the window, so
 * it shows as a halo around the window's top and sides, brightest and centred behind its upper half. Wide feathered bands
 * slide down through it on slow seamless loops (6.4 s and 8 s) and it breathes on a 9.6 s loop: no lines, no streaks.
 * The page top, the nav and the title stay the site's own near-black. The window's crisp 1px top highlight is CSS.
 * The window and the download row sit in a sticky stage: they rise from the load position and settle with the window
 * centred on the screen, so the window's top never leaves the screen while the visitor is in the block.
 * Smoothness: the light is one WebGL2 fragment pass computed from the time and a few uniforms; the frame loop does no
 * layout reads and no allocations; pointer events only store a target that the loop eases toward on the clock. The
 * canvas renders at min(devicePixelRatio, 1.5) and idles while the tab is hidden or the block is off-screen. Without
 * WebGL2 a canvas 2D version is drawn at 30 fps; under prefers-reduced-motion one still frame is drawn and nothing moves.
 * Our own code (nothing taken from OpenBot or React Bits).
 */
(() => {
  const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const q = s => document.querySelector(s);
  let cv = q('canvas[data-beam]');
  const pill = q('[data-dlpill]'), sec = q('[data-omher]'), shot = q('[data-app-shot]'), win = q('[data-app-win]') || shot;
  const meta = q('[data-omher] .omher__meta') || q('[data-omher] .omher__t');
  if (!cv || !pill || !sec || !shot) return;

  // the 01-08 section rail belongs to the OMH sections, not to the omher block
  new IntersectionObserver(es => document.body.classList.toggle('rail-off', es[0].isIntersecting), {rootMargin: '0px 0px -60% 0px'}).observe(sec);

  const PROF = /[?&]beamprof\b/.test(location.search);
  const stats = window.__beam = {mode: '', frames: 0, cpu: [], gpu: [], lean: []};
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

    let W = 0, H = 0, DPR = 1;
  // pointer: events only store the target (tx, ty, in); the frame loop eases px, py, mz and lean toward it on the clock
  const S = {I: 0, pour: RM ? 1 : 0, hov: 0, hovT: 0, tx: 0, ty: 0, in: 0, px: 0, py: 0, mz: 0, lean: 0, rise: RM ? 1 : 0, riseW: -1,
    burst: -9, t0: performance.now(), ci: 0};
  // geometry, cached in document coordinates from the untransformed layout; the frame loop only subtracts the scroll
  // offset and applies the scroll-rise transform analytically, so it never reads layout
  const G = {wl: 0, wt: 0, ww: 0, wh: 0, ml: -9e3, mt: -9e3, mr: -9e3, mb: -9e3, fl: 1e9, sy: 0, gap: 999, so: 0, sk: -1, se: 1e9, sh: 0};
  const stage = q('[data-omher-stage]');
  const RISE = !RM;
  const PERSP = 1400;

  /* ---------- WebGL2 ---------- */
  const GLSL_COMMON = `
float h21(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float vn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3. - 2. * f);
  return mix(mix(h21(i), h21(i + vec2(1, 0)), f.x), mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), f.x), f.y); }
// the text sits in a soft pocket of dark: the light dims over ~250px around the text block (no visible box)
float pocket(vec2 p, vec4 b, float k){
  vec2 c = (b.xy + b.zw) * .5, h = (b.zw - b.xy) * .5;
  vec2 q = abs(p - c) - h + 30.; float d = length(max(q, 0.)) + min(max(q.x, q.y), 0.) - 30.;
  return mix(.6, 1., smoothstep(-40., 260. * k, d));
}
// the window as a trapezoid (its scroll-rise tilt makes the bottom a little wider): 1 inside its opaque UI
float inWin(vec2 p, vec4 w, float sp){
  float f = clamp((p.y - w.y) / max(w.w - w.y, 1.), 0., 1.);
  return step(w.x - sp * f, p.x) * step(p.x, w.z + sp * f) * step(w.y + .5, p.y) * step(p.y, w.w);
}`;
  const VS_BOX = `#version 300 es
uniform vec4 uBox; uniform vec2 uView;
void main(){
  vec2 c = vec2((gl_VertexID == 1 || gl_VertexID == 3) ? 1. : 0., gl_VertexID >= 2 ? 1. : 0.);
  vec2 px = mix(uBox.xy, uBox.zw, c);
  gl_Position = vec4(px.x / uView.x * 2. - 1., 1. - px.y / uView.y * 2., 0., 1.);
}`;
  // pass 1: the aura. A soft pink light falls from above and pools behind the window, showing as a halo around its top
  // and sides; wide feathered bands slide down through it and it breathes. The page top and the title stay the site's
  // own near-black. Nothing is drawn on the window itself (its 1px top highlight is CSS).
  const FS_GLOW = `#version 300 es
precision highp float;
uniform vec2 uView; uniform vec4 uWin, uMeta; uniform vec3 uM;
uniform float uScale, uTime, uK, uI, uFlare, uLean, uSpread, uFloor, uHov;
out vec4 o;
${GLSL_COMMON}
const vec3 PINK = vec3(1., .373, .635), MAGENTA = vec3(.878, .298, .878), VIOLET = vec3(.69, .42, 1.);   // #ff5fa2 #e04ce0 #b06bff
// signed distance to a rounded box (centre c, half size h, radius r)
float sdBox(vec2 p, vec2 c, vec2 h, float r){ vec2 q = abs(p - c) - h + r; return length(max(q, 0.)) + min(max(q.x, q.y), 0.) - r; }
// one soft band of light sliding down over period P seconds (seamless: the phase wraps with the clock)
float fallBand(float y, float lam, float P, float T, float ph){ return .5 + .5 * sin(6.2831853 * (y / lam - T / P) + ph); }
void main(){
  vec2 p = vec2(gl_FragCoord.x, uView.y * uScale - gl_FragCoord.y) / uScale;
  float T = uTime, K = uK;
  float wl = uWin.x, wt = uWin.y, wr = uWin.z, wb = uWin.w, ww = wr - wl, wh = wb - wt, cx = (wl + wr) * .5;
  if (inWin(p, uWin, uSpread) > .5) { o = vec4(0.); return; }
  float L = uLean * 60. * K;
  // the aura: pink light falling from above and pooling BEHIND the window, so it shows as a halo around the window's top
  // and sides; brightest behind the window's upper half, centred; the page top stays the site's own near-black
  float d = max(sdBox(p, vec2(cx, wt + wh * .5), vec2(ww * .5, wh * .5), 8.), 0.);
  float xr = (p.x - cx - L) / (ww * .5);
  float across = exp(-xr * xr * .22);                         // centred, but reaching both sides of the window
  float down = exp(-max(p.y - (wt + wh * .8), 0.) / (wh * 1.1));   // holds down the sides and reaches under the window
  float above = smoothstep(wt - 170. * K, wt + 60. * K, p.y);     // it falls from above, gone well before the title
  // a wider, softer halo on the sides than above: the light pools behind the window rather than cresting its edge
  // a pool of light behind the window's upper middle (an ellipse, not the window's outline) plus a soft rim of it
  // around the edges; only what spills past the window shows
  vec2 pe = vec2((p.x - cx - L) / (ww * .66), (p.y - (wt + wh * .42)) / (wh * .74));
  float pool = exp(-dot(pe, pe) * 1.45);
  // a halo all the way round: the pool behind the window plus a soft rim of light on every edge, a little more on the
  // sides and the top than under it
  // under the window the rim glow is a touch stronger, so the halo closes round it
  float under = 1. + .5 * smoothstep(wb - 20., wb + 40., p.y);
  float halo = pool * .8 + (exp(-d / (160. * K)) * .62 + exp(-d / (34. * K)) * .32) * under;
  halo *= mix(.9, .4, smoothstep(0., 1., (wt - p.y) / (110. * K)));   // lighter above the window than beside it
  float aura = halo * across * down * above;
  // the falling: wide feathered bands sliding down at two slow rates, plus a slow breath; every loop is seamless
  float fall = .72 + .17 * fallBand(p.y + .2 * p.x, 520. * K, 8., T, 0.) + .11 * fallBand(p.y - .15 * p.x, 330. * K, 6.4, T, 2.1);
  float breathe = .92 + .08 * sin(6.2831853 * T / 9.6);
  float e = aura * fall * breathe;
  // pink at the heart, magenta as it spreads, a faint violet only at the outer edge
  vec3 hue = mix(PINK, MAGENTA, .45 * smoothstep(.2, 1.1, abs(xr) * .6 + d / (320. * K)));
  hue = mix(hue, vec3(1., .78, .9), .18);   // a soft blush, never neon
  hue = mix(hue, VIOLET, .18 * smoothstep(180. * K, 420. * K, d));
  vec3 col = hue * e * .6;
  // the cursor: the light brightens gently near it
  col *= 1. + .18 * uM.z * exp(-dot(p - uM.xy, p - uM.xy) / (2. * 320. * 320. * K * K));
  col *= (1. + .3 * uFlare) * (1. + .25 * uHov) * uI;
  col *= pocket(p, uMeta, max(K, .5)) * smoothstep(uFloor, uFloor - 240. * K, p.y);
  col = 1. - exp(-col);
  col += (h21(gl_FragCoord.xy) - .5) / 255. * step(.004, col.r + col.b);   // dither: no banding in the dark falloff
  o = vec4(col, max(col.r, max(col.g, col.b)));
}`;
  let gl = null, progG = null;
  const UG = {};
  if (window.WebGL2RenderingContext) {
    try { gl = cv.getContext('webgl2', {alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false, powerPreference: 'low-power'}); } catch (e) { gl = null; }
  }
  if (gl) {
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    const link = (vs, fs) => { const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p)); return p; };
    try {
      progG = link(VS_BOX, FS_GLOW);
      for (const n of ['uBox', 'uView', 'uWin', 'uMeta', 'uM', 'uScale', 'uTime', 'uK', 'uI', 'uFlare', 'uLean', 'uSpread', 'uFloor', 'uHov']) UG[n] = gl.getUniformLocation(progG, n);
      gl.bindVertexArray(gl.createVertexArray());   // no attributes: every vertex is computed from gl_VertexID
      // screen blend inside the canvas: light adds up without clipping to a flat white
      gl.enable(gl.BLEND); gl.blendFuncSeparate(gl.ONE, gl.ONE_MINUS_SRC_COLOR, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    } catch (e) { console.warn('[beam] shader failed, using canvas 2D', e); gl = null; }
  }
  // a context that failed to build its program cannot hand the canvas to 2D; swap in a fresh canvas
  let cx = null;
  if (!gl) {
    if (progG !== null) { const n = cv.cloneNode(false); cv.replaceWith(n); cv = n; }
    cx = cv.getContext('2d');
  }
  stats.mode = gl ? 'webgl2' : '2d';
  document.documentElement.dataset.beam = stats.mode + (RM ? '-still' : '');
  console.info('[beam] ' + stats.mode + (RM ? ' (reduced motion: still frame)' : ''));
  cv.addEventListener('webglcontextlost', e => { e.preventDefault(); gl = null; stats.mode = 'lost'; });

  function measure() {
    // the untransformed layout box: offsets ignore the rise transform; the section itself is never transformed
    const sy = scrollY, sr = sec.getBoundingClientRect(), st = sr.top + sy;
    G.sy = sy;
    // the window inside the sticky stage: its offset in the stage, the stage's static top, its sticky top and the last
    // scroll position before the block pushes it up (the frame loop reproduces sticky positioning from these)
    const so = stage ? shot.offsetTop + win.offsetTop : 0;
    G.wl = sr.left + (stage ? stage.offsetLeft : 0) + shot.offsetLeft + win.offsetLeft; G.ww = win.offsetWidth; G.wh = win.offsetHeight; G.so = so;
    if (stage) {
      const cs = getComputedStyle(stage), pb = parseFloat(getComputedStyle(sec).paddingBottom) || 0;
      G.sk = cs.position === 'sticky' ? parseFloat(cs.top) || 0 : -1;
      G.wt = st + stage.offsetTop + so; G.sh = stage.offsetHeight;
      G.se = st + sec.offsetHeight - pb - G.sh;   // the stage's document top once the block's end pushes it
    } else G.wt = st + shot.offsetTop + win.offsetTop;
    if (meta) { const m = meta.getBoundingClientRect(); G.ml = m.left; G.mr = m.right; G.mt = m.top + sy; G.mb = m.bottom + sy; }
    G.fl = st + sec.offsetHeight - 120;   // the light is gone before the next section
    G.gap = G.wt - st;   // header-to-window room in the layout (a tight phone layout gets no light)
    G.st0 = st;
  }
  function size() {
    W = innerWidth; H = innerHeight; DPR = Math.min(devicePixelRatio || 1, 1.5);
    cv.width = Math.max(1, Math.round(W * DPR)); cv.height = Math.max(1, Math.round(H * DPR));
    measure();
  }
  // the scroll-rise: on load the window sits a little lower, at .9 and tilted back 2.5deg; it grows to full size and
  // straightens as the page scrolls into it (eased in the frame loop). Once settled it carries no transform at all, so
  // the window is flat (top and bottom the same width) and the picture and the live app stay sharp
  const riseOf = e => ({ty: (1 - e) * 14, a: (1 - e) * 2.5, sc: .9 + .1 * e, op: 1});
  function applyRise(e) {
    const r = riseOf(e);
    if (e >= .9995) { shot.style.transform = 'none'; shot.style.willChange = 'auto'; }
    else {
      shot.style.willChange = 'transform';
      shot.style.transform = `perspective(${PERSP}px) translateY(${r.ty.toFixed(2)}px) rotateX(${r.a.toFixed(3)}deg) scale(${r.sc.toFixed(4)})`;
    }
    if (stage) stage.style.setProperty('--rise', smooth(.35, 1, e).toFixed(3));   // the download row arrives as the window settles
  }

  /* ---------- per frame: uniforms and one draw, nothing else ---------- */
  function drawGL(t, wl, wt, wr, wb, k, flare, spread, floor) {
    gl.viewport(0, 0, cv.width, cv.height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    if (S.I <= .002) return;
    const sc = cv.width / W, ml = G.ml, mr = G.mr, mt = G.mt - G.sy, mb = G.mb - G.sy;
    const I = S.I * (1 - Math.pow(1 - S.pour, 3));
    const bt = clamp(floor, 0, H);   // the halo runs down the window's sides to the floor
    if (bt > 2) {
      gl.useProgram(progG);
      gl.uniform4f(UG.uBox, 0, 0, W, bt); gl.uniform2f(UG.uView, W, H); gl.uniform1f(UG.uScale, sc);
      gl.uniform4f(UG.uWin, wl, wt, wr, wb); gl.uniform4f(UG.uMeta, ml, mt, mr, mb);
      gl.uniform3f(UG.uM, S.px, S.py, S.mz); gl.uniform1f(UG.uTime, t); gl.uniform1f(UG.uK, k);
      gl.uniform1f(UG.uI, I); gl.uniform1f(UG.uFlare, flare); gl.uniform1f(UG.uLean, S.lean);
      gl.uniform1f(UG.uSpread, spread); gl.uniform1f(UG.uFloor, floor); gl.uniform1f(UG.uHov, S.hov);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
  }

  /* ---------- canvas 2D fallback: the same pink aura behind the window, breathing ---------- */
  function draw2d(t, wl, wt, wr, wb, k, flare, spread, floor) {
    cx.setTransform(1, 0, 0, 1, 0, 0); cx.clearRect(0, 0, cv.width, cv.height);
    if (S.I <= .002) return;
    const amp = Math.min(1, S.I * (1 - Math.pow(1 - S.pour, 3)) * (1 + .25 * S.hov) * (1 + .3 * flare)) * (.92 + .08 * Math.sin(t * 6.2832 / 9.6));
    const c = (wl + wr) / 2, ww = wr - wl, wh = wb - wt, fy = (t / 8 % 1) * 40 * k;   // a slow downward drift
    cx.save(); cx.setTransform(DPR, 0, 0, DPR, 0, 0);
    cx.beginPath(); cx.rect(0, 0, W, Math.min(H, floor)); cx.clip();
    cx.globalCompositeOperation = 'lighter';
    cx.translate(c, wt + wh * .25 + fy); cx.scale(1, (wh * .55 + 200 * k) / (ww * .5 + 200 * k));
    const r = ww * .5 + 200 * k, g = cx.createRadialGradient(0, 0, 0, 0, 0, r);
    g.addColorStop(0, `rgba(255,95,162,${.34 * amp})`); g.addColorStop(.6, `rgba(224,76,224,${.16 * amp})`); g.addColorStop(1, 'rgba(176,107,255,0)');
    cx.fillStyle = g; cx.fillRect(-r, -r, 2 * r, 2 * r);
    cx.restore();
  }

  function frame(now, dt) {
    const t = RM ? 6 : (now - S.t0) / 1000, sy = G.sy, k = clamp(W / 1440, .36, 1.15);
    const ez = rate => RM ? 1 : 1 - Math.exp(-dt / 1000 * rate);   // time-based exponential smoothing
    // the scroll-rise, eased toward the scroll position; written only while it moves
    if (RISE) {
      // complete by the time the stage sticks (the window centred on the screen)
      const target = W > 760 ? smooth(0, Math.max(60, G.sk >= 0 ? G.wt - G.so - G.sk : H * .4), sy) : 1;
      S.rise += (target - S.rise) * ez(9);
      if (Math.abs(S.rise - target) < .0005) S.rise = target;
      if (Math.abs(S.rise - S.riseW) > .0004 || (S.rise === target && S.riseW !== target)) { applyRise(S.rise); S.riseW = S.rise; }
    }
    // the window's real box on screen, from the layout box and the rise transform (origin: bottom centre)
    const r = RISE ? riseOf(S.rise) : {ty: 0, a: 0, sc: 1};
    // sticky: the stage's screen top is its static top, held at the sticky top, then pushed up by the block's end
    let stTop = G.wt - G.so - sy;
    if (G.sk >= 0) stTop = Math.min(Math.max(stTop, G.sk), G.se - sy);
    // origin: the window's centre; a rotateX about it tilts the top back (narrower) and the bottom forward (wider)
    const ox = G.wl + G.ww / 2, oy = stTop + G.so + G.wh / 2 + r.ty, ar = r.a * Math.PI / 180, hh = G.wh / 2 * r.sc;
    const zt = hh * Math.sin(ar), fT = PERSP / (PERSP + zt), fB = PERSP / (PERSP - zt), hw = G.ww / 2 * r.sc;
    const wt = oy - hh * Math.cos(ar) * fT, wb = oy + hh * Math.cos(ar) * fB, wl = ox - hw * fT, wr = ox + hw * fT, spread = hw * (fB - fT);
    const floor = G.fl - sy;
    // the light needs room above the window (none on a tight phone layout) and fades once the block is scrolled past
    const vis = smooth(90, 140, G.gap) * smooth(-80, 160, floor);
    if (RM) S.I = vis; else S.I = clamp(S.I + clamp(vis - S.I, -dt / 260, dt / 420), 0, 1);
    if (!RM && vis > 0) S.pour = Math.min(1, S.pour + dt / 1400);
    S.hov += (S.hovT - S.hov) * ez(6);
    // the pointer: position, presence and lean all ease on the clock; each step is capped
    const kp = ez(8);
    S.px += (S.tx - S.px) * kp; S.py += (S.ty - S.py) * kp;
    S.mz += (S.in * (S.ty < wb + 120 ? 1 : 0) - S.mz) * ez(4);
    const leanT = clamp((S.px - ox) / (W * .5), -1, 1) * S.mz;
    S.lean += clamp((leanT - S.lean) * ez(4), -.012 * dt / 16.7, .012 * dt / 16.7);
    stats.lean[S.ci % 3000] = S.lean;
    const flare = S.burst > 0 && t > S.burst ? Math.exp(-(t - S.burst) * 2.5) : 0;
    if (gl) drawGL(t, wl, wt, wr, wb, k, flare, spread, floor);
    else if (cx) draw2d(t, wl, wt, wr, wb, k, flare, spread, floor);
  }

  const PX = new Uint8Array(4);
  let raf = 0, last = 0, seen = true;
  const minDt = gl ? 0 : 31;   // every display frame for the shader; 30 fps for the 2D fallback
  function clearAll() { if (gl) { gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); } else if (cx) { cx.setTransform(1, 0, 0, 1, 0, 0); cx.clearRect(0, 0, cv.width, cv.height); } }
  function loop(now) {
    raf = 0;
    if (document.hidden || !seen) { clearAll(); last = 0; return; }
    if (last && now - last < minDt) { raf = requestAnimationFrame(loop); return; }
    const dt = last ? Math.min(50, now - last) : 16; last = now;
    const c0 = performance.now();
    frame(now, dt);
    const c1 = performance.now();
    if (PROF && gl) { gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, PX); stats.gpu[S.ci % 3000] = performance.now() - c1; }   // readPixels waits for the GPU
    stats.cpu[S.ci % 3000] = c1 - c0; S.ci++; stats.frames++;
    raf = requestAnimationFrame(loop);
  }
  function kick() {
    if (RM) { if (!raf) raf = requestAnimationFrame(now => { raf = 0; if (!document.hidden && seen) frame(now, 0); else clearAll(); }); return; }
    if (!raf) { last = 0; raf = requestAnimationFrame(loop); }
  }

  /* ---------- interaction: events only store the target; the frame loop does all easing ---------- */
  addEventListener('pointermove', e => { S.tx = e.clientX; S.ty = e.clientY; if (!S.in && S.mz < .01) { S.px = S.tx; S.py = S.ty; } S.in = RM || e.pointerType !== 'mouse' ? 0 : 1; }, {passive: true});
  document.documentElement.addEventListener('pointerleave', () => { S.in = 0; });   // ease back to rest; never reset
  // a click on the block brightens the light for a moment
  sec.addEventListener('click', e => {
    if (RM || e.target.closest('a,button,code,.omher__cmd')) return;
    S.burst = (performance.now() - S.t0) / 1000;
  });
  for (const [ev, v] of [['pointerenter', 1], ['pointerleave', 0], ['focus', 1], ['blur', 0]]) pill.addEventListener(ev, () => { S.hovT = v; });

  // the shot fades in under the light once (a CSS transition on the registered --reveal), then the glass sheen joins
  if (!RM) { shot.style.setProperty('--reveal', '0'); setTimeout(() => { shot.style.setProperty('--reveal', '1'); shot.style.setProperty('--lit', '.9'); }, 450); }
  else shot.style.setProperty('--lit', '.9');

  size();
  if (RISE) { S.rise = W > 760 ? smooth(0, Math.max(60, G.sk >= 0 ? G.wt - G.so - G.sk : H * .4), scrollY) : 1; applyRise(S.rise); S.riseW = S.rise; }   // before the first paint
  addEventListener('resize', () => { size(); kick(); });
  addEventListener('scroll', () => { G.sy = scrollY; kick(); }, {passive: true});
  addEventListener('load', measure);
  if (document.fonts) document.fonts.ready.then(measure);
  if (window.ResizeObserver) { const ro = new ResizeObserver(measure); ro.observe(win); if (meta) ro.observe(meta); if (stage) ro.observe(stage); }
  document.addEventListener('visibilitychange', kick);
  new IntersectionObserver(es => { seen = es[0].isIntersecting; kick(); }).observe(sec);
  kick();
})();
