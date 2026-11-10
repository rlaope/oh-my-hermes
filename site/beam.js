/*!
 * omher.app top block: a soft, luminous glow that pours from the top of the hero down onto and behind the app window.
 * A few broad, feathered shafts of light (OMH pink, magenta, violet and a warm white) fall at slightly different angles
 * and depths, slowly drifting and breathing, brightest where they reach the window. A glow band with a pink rim rests
 * along the window's top edge, so the window stands in silhouette against the light behind it, and a faint wash
 * catches its title bar. A few tiny soft motes drift down through the light. The light fades out around the title
 * block and never fills the gutters beside the window. The window rises into place as the page scrolls.
 * Smoothness: the light is two WebGL2 draws (one fragment pass, one instanced draw for the motes) computed from the time
 * and a few uniforms; the frame loop does no layout reads and no allocations; pointer events only store a target that
 * the loop eases toward on the clock. The canvas renders at min(devicePixelRatio, 1.5) and idles while the tab is hidden
 * or the block is off-screen. Without WebGL2 a canvas 2D version is drawn at 30 fps; under prefers-reduced-motion one
 * still frame is drawn and the window does not move. Our own code (nothing taken from OpenBot or React Bits).
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

  const NM = 26;   // motes
  let W = 0, H = 0, DPR = 1;
  // pointer: events only store the target (tx, ty, in); the frame loop eases px, py, mz and lean toward it on the clock
  const S = {I: 0, pour: RM ? 1 : 0, hov: 0, hovT: 0, tx: 0, ty: 0, in: 0, px: 0, py: 0, mz: 0, lean: 0, rise: RM ? 1 : 0, riseW: -1,
    ft: RM ? 6 : 0, burst: -9, t0: performance.now(), ci: 0};
  // geometry, cached in document coordinates from the untransformed layout; the frame loop only subtracts the scroll
  // offset and applies the scroll-rise transform analytically, so it never reads layout
  const G = {wl: 0, wt: 0, ww: 0, wh: 0, ml: -9e3, mt: -9e3, mr: -9e3, mb: -9e3, fl: 1e9, sy: 0, gap: 999};
  const RISE = !RM;
  const PERSP = 1400;

  /* ---------- WebGL2 ---------- */
  const GLSL_COMMON = `
float h21(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float vn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3. - 2. * f);
  return mix(mix(h21(i), h21(i + vec2(1, 0)), f.x), mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), f.x), f.y); }
// the OMH brand light: 0 hot pink #ff5fa2, 1 magenta #e04ce0, 2 violet #b06bff (clamped, not cyclic)
vec3 brand(float h){
  h = clamp(h, 0., 2.); vec3 a = vec3(1., .373, .635), b = vec3(.878, .298, .878), c = vec3(.69, .42, 1.);
  return h < 1. ? mix(a, b, smoothstep(0., 1., h)) : mix(b, c, smoothstep(1., 2., h));
}
const vec3 WARM = vec3(1., .93, .9);
// the text block sits in a soft pocket of dark: the light fades out over ~130px around it (no visible box)
float pocket(vec2 p, vec4 b, float k){
  vec2 c = (b.xy + b.zw) * .5, h = (b.zw - b.xy) * .5;
  vec2 q = abs(p - c) - h + 30.; float d = length(max(q, 0.)) + min(max(q.x, q.y), 0.) - 30.;
  return mix(.22, 1., smoothstep(-40., 220. * k, d));
}
// the window as a trapezoid (its scroll-rise tilt makes the bottom a little wider): 1 inside its opaque UI
float inWin(vec2 p, vec4 w, float sp){
  float f = clamp((p.y - w.y) / max(w.w - w.y, 1.), 0., 1.);
  return step(w.x - sp * f, p.x) * step(p.x, w.z + sp * f) * step(w.y + .5, p.y) * step(p.y, w.w);
}
// light below the window's top edge only on the window itself: the gutters beside it stay dark
float gutter(vec2 p, vec4 w, float k){
  float out_ = 1. - smoothstep(w.x - 2., w.x + 2., p.x) * smoothstep(w.z + 2., w.z - 2., p.x);
  return mix(1., exp(-pow(max(p.y - w.y, 0.) / (40. * k), 2.)), out_);
}`;
  const VS_BOX = `#version 300 es
uniform vec4 uBox; uniform vec2 uView;
void main(){
  vec2 c = vec2((gl_VertexID == 1 || gl_VertexID == 3) ? 1. : 0., gl_VertexID >= 2 ? 1. : 0.);
  vec2 px = mix(uBox.xy, uBox.zw, c);
  gl_Position = vec4(px.x / uView.x * 2. - 1., 1. - px.y / uView.y * 2., 0., 1.);
}`;
  // pass 1: the shafts, the resting glow band and pink rim on the window's top edge, the title-bar wash
  const FS_GLOW = `#version 300 es
precision highp float;
uniform vec2 uView; uniform vec4 uWin, uMeta; uniform vec3 uM;
uniform float uScale, uTime, uK, uI, uFlare, uLean, uSpread, uFloor, uHov;
out vec4 o;
${GLSL_COMMON}
// one broad feathered shaft from (xa, ya) down to (xb, the window's top): returns its brightness at p
float shaft(vec2 p, float xa, float xb, float ya, float yb, float wa, float wb){
  float t = clamp((p.y - ya) / (yb - ya), 0., 1.);
  float d = p.x - mix(xa, xb, t), w = mix(wa, wb, t);
  return exp(-d * d / (w * w)) * mix(.42, 1., t) * smoothstep(-.05, .25, t) * mix(1., .6, smoothstep(.82, 1., t));
}
void main(){
  vec2 p = vec2(gl_FragCoord.x, uView.y * uScale - gl_FragCoord.y) / uScale;
  float T = uTime, K = uK;
  float wl = uWin.x, wt = uWin.y, wr = uWin.z, ww = wr - wl, cx = (wl + wr) * .5;
  float dy = wt - p.y, dyIn = max(-dy, 0.);
  float inside = inWin(p, uWin, uSpread);
  if (inside > .5 && dyIn > 90. * K) { o = vec4(0.); return; }
  float xn = (p.x - wl) / ww, xc = abs(xn - .5);   // unclamped: colours keep varying smoothly past the window's sides
  float ya = min(wt - 520. * K, 0.), L = uLean * 150. * K;
  // the shafts: broad, soft, at slightly different angles and depths; each drifts and breathes on its own slow clock
  vec3 col = vec3(0.);
  float s0 = shaft(p, cx - 420. * K + 40. * K * sin(T * .045) + L, cx - 300. * K + .3 * L, ya, wt, 90. * K, 170. * K) * (.78 + .22 * sin(T * .31));
  float s1 = shaft(p, cx - 190. * K + 34. * K * sin(T * .052 + 1.7) + L, cx - 90. * K + .3 * L, ya, wt, 80. * K, 150. * K) * (.8 + .2 * sin(T * .27 + 2.1));
  float s2 = shaft(p, cx + 210. * K + 38. * K * sin(T * .041 + 3.9) + L, cx + 140. * K + .3 * L, ya, wt, 86. * K, 160. * K) * (.8 + .2 * sin(T * .23 + 4.4));
  float s3 = shaft(p, cx + 440. * K + 42. * K * sin(T * .048 + 5.2) + L, cx + 320. * K + .3 * L, ya, wt, 96. * K, 180. * K) * (.78 + .22 * sin(T * .29 + .8));
  col += (brand(2.) * s0 * .42 + mix(brand(.1), WARM, .1) * s1 * 1.05 + brand(1.) * s2 * .95 + brand(1.6) * s3 * .4);
  // a soft texture inside the light: barely-there slow variation, no lines
  col *= .95 + .1 * vn(vec2(p.x / (260. * K) + T * .02, p.y / (520. * K) - T * .035));
  // a broad ambient wash across the whole width, brightest over the window, falling off toward the sides
  float amb = exp(-pow((p.x - cx) / (.62 * uView.x), 2.)) * smoothstep(ya, wt, p.y);
  col += brand(1.6) * amb * .03;
  // the resting look: a glow band behind the window's top edge, pink along most of it, violet toward the ends
  float hx = exp(-pow(max(abs(p.x - cx) - ww * .22, 0.) / (ww * .3), 2.));   // one broad elliptical bloom, feathered well past the window
  float live = .86 + .28 * vn(vec2(p.x / (300. * K) - T * .05, T * .07));
  float up = max(dy, 0.);
  // the hotspot sits a little above the edge (light coming from behind), with a soft spill around the window's sides
  float band = (exp(-pow((up - 48. * K) / (60. * K), 2.)) * .13 + exp(-up / (170. * K)) * .05) * hx * live * step(0., dy + .5);
  float spill = exp(-pow(min(abs(p.x - wl), abs(p.x - wr)) / (70. * K), 2.)) * (1. - smoothstep(wl - 6., wl + 6., p.x) * smoothstep(wr + 6., wr - 6., p.x))
    * exp(-max(p.y - wt, 0.) / (60. * K)) * smoothstep(wt - 120. * K, wt, p.y);
  col += mix(brand(1.75), WARM, .1) * spill * .08 * live;
  vec3 bandC = mix(brand(min(xc * 3.2, 2.)), WARM, .04 + .2 * exp(-up / (8. * K)));
  col += bandC * band;
  // the pink rim on the edge, with a whisper of iridescence; faint side rims that fade within ~120px
  float rimTop = exp(-pow((dy + .6) / 1.3, 2.)) * smoothstep(wl + 4., wl + 60. * K, p.x) * smoothstep(wr - 4., wr - 60. * K, p.x);
  vec3 rimC = mix(brand(.15 + 1.6 * min(xc, .5)), WARM, .3);
  float sideD = min(abs(p.x - wl), abs(p.x - wr));
  float rimSide = exp(-pow(sideD / 1.2, 2.)) * exp(-dyIn / (120. * K)) * step(0., -dy);
  col += rimC * (rimTop * .13 * live + rimSide * .1);
  // the light reaches the app: a soft wash over its title bar, a few percent, gone within ~50px
  col = col * (1. - inside) + brand(.8) * inside * exp(-dyIn / (22. * K)) * .05 * hx;
  // the cursor: the light brightens gently near it
  col *= 1. + .3 * uM.z * exp(-dot(p - uM.xy, p - uM.xy) / (2. * 300. * 300. * K * K));
  col *= (1. + .4 * uFlare) * (1. + .3 * uHov) * uI * .7;
  col *= pocket(p, uMeta, max(K, .5)) * gutter(p, uWin, K) * smoothstep(uFloor, uFloor - 240. * K, p.y);
  col = (1. - exp(-col * 1.1)) * .9;
  col = max(mix(vec3(dot(col, vec3(.3, .55, .15))), col, 1.6), 0.);   // keep the light a clean, saturated pink/violet over the dark page
  o = vec4(col, max(col.r, max(col.g, col.b)));
}`;
  // pass 2: a few tiny soft motes drifting down through the light (one instanced draw, stateless)
  const VS_MOTE = `#version 300 es
uniform vec2 uView; uniform vec4 uWin; uniform float uTime, uFlow, uK, uI, uLean;
out vec2 vQ; out float vA, vS; out vec3 vC;
${GLSL_COMMON}
float hs(float i, float k){ return fract(sin(i * 12.9898 + k * 78.233) * 43758.5453); }
void main(){
  float i = float(gl_InstanceID), K = uK, W = uView.x;
  float cx = (uWin.x + uWin.z) * .5, d = hs(i, 2.);
  float per = 11. + 7. * hs(i, 6.), t = mod(uFlow + hs(i, 7.) * per, per), u = t / per;
  float s = hs(i, 3.) * 2. - 1.;
  float x = cx + sign(s) * pow(abs(s), 1.25) * W * .46 + 16. * K * sin(uTime * (.25 + .2 * hs(i, 4.)) + hs(i, 9.) * 6.283) + uLean * 24. * K * u;
  float span = (440. + 160. * hs(i, 5.)) * K;
  float y = uWin.y - span * (1. - u) * .8 - 30. * K * hs(i, 8.);
  float fade = smoothstep(0., .12, u) * smoothstep(1., .8, u);   // in over ~1.5 s, out over ~2.5 s: nothing pops
  vS = (.8 + 1.8 * d * d) * sqrt(K) * (1. + .8 * hs(i, 13.));      // varied size and softness
  vA = (.04 + .14 * d * d) * fade * uI * step(hs(i, 12.), .7);
  vC = mix(WARM, brand(hs(i, 10.) * 2.), .45 + .25 * hs(i, 11.));
  vec2 c = vec2((gl_VertexID == 1 || gl_VertexID == 3) ? 1. : 0., gl_VertexID >= 2 ? 1. : 0.) * 2. - 1.;
  vQ = c * 3.;
  vec2 px = vec2(x, y) + c * vS * 3.;
  gl_Position = vA < .003 ? vec4(2., 2., 2., 1.) : vec4(px.x / uView.x * 2. - 1., 1. - px.y / uView.y * 2., 0., 1.);
}`;
  const FS_MOTE = `#version 300 es
precision highp float;
uniform vec2 uView; uniform vec4 uWin, uMeta; uniform float uScale, uK, uSpread, uFloor;
in vec2 vQ; in float vA, vS; in vec3 vC;
out vec4 o;
${GLSL_COMMON}
void main(){
  vec2 p = vec2(gl_FragCoord.x, uView.y * uScale - gl_FragCoord.y) / uScale;
  if (inWin(p, uWin, uSpread) > .5) discard;
  float g = exp(-dot(vQ, vQ) * .9);
  float a = g * vA * pocket(p, uMeta, max(uK, .5)) * gutter(p, uWin, uK) * smoothstep(uFloor, uFloor - 240. * uK, p.y)
    * smoothstep(uWin.y + 4., uWin.y - 30. * uK, p.y);   // gone by the window's top edge
  o = vec4(vC * a, a);
}`;

  let gl = null, progG = null, progM = null;
  const UG = {}, UM = {};
  if (window.WebGL2RenderingContext) {
    try { gl = cv.getContext('webgl2', {alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false, powerPreference: 'low-power'}); } catch (e) { gl = null; }
  }
  if (gl) {
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    const link = (vs, fs) => { const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p)); return p; };
    try {
      progG = link(VS_BOX, FS_GLOW); progM = link(VS_MOTE, FS_MOTE);
      for (const n of ['uBox', 'uView', 'uWin', 'uMeta', 'uM', 'uScale', 'uTime', 'uK', 'uI', 'uFlare', 'uLean', 'uSpread', 'uFloor', 'uHov']) UG[n] = gl.getUniformLocation(progG, n);
      for (const n of ['uView', 'uWin', 'uMeta', 'uScale', 'uTime', 'uFlow', 'uK', 'uI', 'uLean', 'uSpread', 'uFloor']) UM[n] = gl.getUniformLocation(progM, n);
      gl.bindVertexArray(gl.createVertexArray());   // no attributes: every vertex is computed from gl_VertexID and gl_InstanceID
      // screen blend inside the canvas: light adds up without clipping to a flat white
      gl.enable(gl.BLEND); gl.blendFuncSeparate(gl.ONE, gl.ONE_MINUS_SRC_COLOR, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    } catch (e) { console.warn('[beam] shader failed, using canvas 2D', e); gl = null; }
  }
  // a context that failed to build its program cannot hand the canvas to 2D; swap in a fresh canvas
  let cx = null;
  if (!gl) {
    if (progG !== null || progM !== null) { const n = cv.cloneNode(false); cv.replaceWith(n); cv = n; }
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
    G.wl = sr.left + shot.offsetLeft + win.offsetLeft; G.wt = st + shot.offsetTop + win.offsetTop; G.ww = win.offsetWidth; G.wh = win.offsetHeight;
    if (meta) { const m = meta.getBoundingClientRect(); G.ml = m.left; G.mr = m.right; G.mt = m.top + sy; G.mb = m.bottom + sy; }
    const act = q('[data-omher] .omher__act');
    G.fl = act ? st + act.offsetTop + act.offsetHeight + 60 : st + sec.offsetHeight - 120;   // the light is gone before the next section
    G.gap = G.wt - st;   // header-to-window room in the layout (a tight phone layout gets no light)
    shot.style.setProperty('--bx', Math.round(G.ww / 2) + 'px');
  }
  function size() {
    W = innerWidth; H = innerHeight; DPR = Math.min(devicePixelRatio || 1, 1.5);
    cv.width = Math.max(1, Math.round(W * DPR)); cv.height = Math.max(1, Math.round(H * DPR));
    measure();
  }
  // the scroll-rise: at rest the window sits a little lower, tilted back and at .94; it eases into place over ~55% of a screen
  const riseOf = e => ({ty: (1 - e) * 44 * Math.min(1, W / 1440), a: (1 - e) * 4, sc: .94 + .06 * e, op: .95 + .05 * e});
  function applyRise(e) {
    const r = riseOf(e);
    shot.style.transform = `perspective(${PERSP}px) translateY(${r.ty.toFixed(2)}px) rotateX(${r.a.toFixed(3)}deg) scale(${r.sc.toFixed(4)})`;
    shot.style.opacity = r.op.toFixed(3);
  }

  /* ---------- per frame: uniforms and two draws, nothing else ---------- */
  function drawGL(t, wl, wt, wr, wb, k, flare, spread, floor) {
    gl.viewport(0, 0, cv.width, cv.height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    if (S.I <= .002) return;
    const sc = cv.width / W, ml = G.ml, mr = G.mr, mt = G.mt - G.sy, mb = G.mb - G.sy;
    const I = S.I * (1 - Math.pow(1 - S.pour, 3));
    const bt = clamp(Math.min(floor, wt + 150 * k), 0, H);
    if (bt > 2) {
      gl.useProgram(progG);
      gl.uniform4f(UG.uBox, 0, 0, W, bt); gl.uniform2f(UG.uView, W, H); gl.uniform1f(UG.uScale, sc);
      gl.uniform4f(UG.uWin, wl, wt, wr, wb); gl.uniform4f(UG.uMeta, ml, mt, mr, mb);
      gl.uniform3f(UG.uM, S.px, S.py, S.mz); gl.uniform1f(UG.uTime, t); gl.uniform1f(UG.uK, k);
      gl.uniform1f(UG.uI, I); gl.uniform1f(UG.uFlare, flare); gl.uniform1f(UG.uLean, S.lean);
      gl.uniform1f(UG.uSpread, spread); gl.uniform1f(UG.uFloor, floor); gl.uniform1f(UG.uHov, S.hov);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      gl.useProgram(progM);
      gl.uniform2f(UM.uView, W, H); gl.uniform1f(UM.uScale, sc);
      gl.uniform4f(UM.uWin, wl, wt, wr, wb); gl.uniform4f(UM.uMeta, ml, mt, mr, mb);
      gl.uniform1f(UM.uTime, t); gl.uniform1f(UM.uFlow, S.ft); gl.uniform1f(UM.uK, k); gl.uniform1f(UM.uI, I * (1 + .3 * S.hov));
      gl.uniform1f(UM.uLean, S.lean); gl.uniform1f(UM.uSpread, spread); gl.uniform1f(UM.uFloor, floor);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, NM);
    }
  }

  /* ---------- canvas 2D fallback: soft shafts, the glow band and rim, a few motes ---------- */
  const hs = (i, k) => { const x = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453; return x - Math.floor(x); };
  const SHAFTS = [[-470, -330, 150, 300, '176,107,255', .3], [-150, -70, 118, 230, '255,95,162', .42], [190, 120, 136, 260, '224,76,224', .38], [500, 350, 160, 320, '200,96,240', .26]];
  function draw2d(t, wl, wt, wr, wb, k, flare, spread, floor) {
    cx.setTransform(1, 0, 0, 1, 0, 0); cx.clearRect(0, 0, cv.width, cv.height);
    if (S.I <= .002) return;
    const amp = Math.min(1, S.I * (1 - Math.pow(1 - S.pour, 3)) * (1 + .3 * S.hov) * (1 + .4 * flare)), c = (wl + wr) / 2, ya = wt - 720 * k, L = S.lean * 150 * k;
    cx.save(); cx.setTransform(DPR, 0, 0, DPR, 0, 0);
    // nothing below the window's top edge except on the window's rim; the window hides what is behind it
    cx.beginPath(); cx.rect(0, 0, W, Math.min(wt, floor)); cx.clip();
    for (const [a, b, wa, wb2, rgb, al] of SHAFTS) {
      const xa = c + a * k + 36 * k * Math.sin(t * .045 + a) + L, xb = c + b * k + .3 * L, w = (wa + wb2) / 2 * k;
      cx.save(); cx.translate(xb, wt); cx.rotate(Math.atan2(xa - xb, wt - ya));
      const g = cx.createLinearGradient(-w * 1.6, 0, w * 1.6, 0);
      g.addColorStop(0, `rgba(${rgb},0)`); g.addColorStop(.5, `rgba(${rgb},${al * amp})`); g.addColorStop(1, `rgba(${rgb},0)`);
      cx.fillStyle = g; cx.globalCompositeOperation = 'lighter'; cx.fillRect(-w * 1.6, -(wt - ya) * 1.1, w * 3.2, (wt - ya) * 1.1);
      cx.restore();
    }
    // fade the shafts toward the top
    cx.globalCompositeOperation = 'destination-out';
    const v = cx.createLinearGradient(0, ya, 0, wt); v.addColorStop(0, 'rgba(0,0,0,.85)'); v.addColorStop(1, 'rgba(0,0,0,0)');
    cx.fillStyle = v; cx.fillRect(0, 0, W, wt);
    cx.globalCompositeOperation = 'lighter';
    // the glow band above the window's top edge
    const band = cx.createLinearGradient(0, wt - 140 * k, 0, wt);
    band.addColorStop(0, 'rgba(224,76,224,0)'); band.addColorStop(.75, `rgba(255,95,162,${.22 * amp})`); band.addColorStop(1, `rgba(255,190,215,${.5 * amp})`);
    cx.fillStyle = band; cx.fillRect(wl - 80 * k, wt - 140 * k, wr - wl + 160 * k, 140 * k);
    // motes
    for (let i = 0; i < NM; i++) {
      const per = 11 + 7 * hs(i, 6), u = ((S.ft + hs(i, 7) * per) % per) / per, d = hs(i, 2), s = hs(i, 3) * 2 - 1;
      const x = c + Math.sign(s) * Math.pow(Math.abs(s), 1.25) * W * .46 + 16 * k * Math.sin(t * .3 + hs(i, 9) * 6.283);
      const y = wt - (440 + 160 * hs(i, 5)) * k * (1 - u), a = (.14 + .36 * d) * smooth(0, .12, u) * smooth(1, .8, u) * amp;
      cx.globalAlpha = a; cx.fillStyle = '#ffd6ea'; cx.beginPath(); cx.arc(x, y, (1 + 1.6 * d) * Math.sqrt(k), 0, 6.2832); cx.fill();
    }
    cx.globalAlpha = 1; cx.restore();
    // the pink rim on the edge, then the soft dark pocket around the text block
    cx.save(); cx.setTransform(DPR, 0, 0, DPR, 0, 0);
    const rim = cx.createLinearGradient(wl, 0, wr, 0);
    rim.addColorStop(0, `rgba(176,107,255,${.5 * amp})`); rim.addColorStop(.5, `rgba(255,140,190,${.9 * amp})`); rim.addColorStop(1, `rgba(176,107,255,${.5 * amp})`);
    cx.fillStyle = rim; cx.fillRect(wl, wt - 1, wr - wl, 2);
    if (G.ml > -9e3) {
      const mt = G.mt - G.sy, mb = G.mb - G.sy, rx = (G.mr - G.ml) / 2 + 130, ry = (mb - mt) / 2 + 100;
      cx.globalCompositeOperation = 'destination-out';
      cx.translate((G.ml + G.mr) / 2, (mt + mb) / 2); cx.scale(1, ry / rx);
      const rg = cx.createRadialGradient(0, 0, 0, 0, 0, rx); rg.addColorStop(0, '#000'); rg.addColorStop(.62, '#000'); rg.addColorStop(1, 'rgba(0,0,0,0)');
      cx.fillStyle = rg; cx.beginPath(); cx.arc(0, 0, rx, 0, 6.2832); cx.fill();
    }
    cx.restore();
  }

  function frame(now, dt) {
    const t = RM ? 6 : (now - S.t0) / 1000, sy = G.sy, k = clamp(W / 1440, .36, 1.15);
    const ez = rate => RM ? 1 : 1 - Math.exp(-dt / 1000 * rate);   // time-based exponential smoothing
    // the scroll-rise, eased toward the scroll position; written only while it moves
    if (RISE) {
      const target = W > 760 ? smooth(0, H * .55, sy) : 1;
      S.rise += (target - S.rise) * ez(9);
      if (Math.abs(S.rise - target) < .0005) S.rise = target;
      if (Math.abs(S.rise - S.riseW) > .0004 || (S.rise === target && S.riseW !== target)) { applyRise(S.rise); S.riseW = S.rise; }
    }
    // the window's real box on screen, from the layout box and the rise transform (origin: bottom centre)
    const r = RISE ? riseOf(S.rise) : {ty: 0, a: 0, sc: 1};
    const ox = G.wl + G.ww / 2, oy = G.wt + G.wh - sy, ar = r.a * Math.PI / 180, hgt = G.wh * r.sc;
    const f = PERSP / (PERSP + hgt * Math.sin(ar)), hwB = G.ww / 2 * r.sc, hwT = hwB * f;
    const wl = ox - hwT, wr = ox + hwT, wt = oy + (r.ty - hgt * Math.cos(ar)) * f, wb = oy + r.ty, spread = hwB - hwT;
    const floor = G.fl - sy;
    // the light needs room above the window (none on a tight phone layout) and fades once the block is scrolled past
    const vis = smooth(90, 140, G.gap) * smooth(-80, 160, floor);
    if (RM) S.I = vis; else S.I = clamp(S.I + clamp(vis - S.I, -dt / 260, dt / 420), 0, 1);
    if (!RM && vis > 0) S.pour = Math.min(1, S.pour + dt / 1400);
    S.hov += (S.hovT - S.hov) * ez(6);
    S.ft += RM ? 0 : dt / 1000;
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
  if (RISE) { S.rise = W > 760 ? smooth(0, H * .55, scrollY) : 1; applyRise(S.rise); S.riseW = S.rise; }   // before the first paint
  addEventListener('resize', () => { size(); kick(); });
  addEventListener('scroll', () => { G.sy = scrollY; kick(); }, {passive: true});
  addEventListener('load', measure);
  if (document.fonts) document.fonts.ready.then(measure);
  if (window.ResizeObserver) { const ro = new ResizeObserver(measure); ro.observe(win); if (meta) ro.observe(meta); }
  document.addEventListener('visibilitychange', kick);
  new IntersectionObserver(es => { seen = es[0].isIntersecting; kick(); }).observe(sec);
  kick();
})();
