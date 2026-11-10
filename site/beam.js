/*!
 * omher.app top block: a pillar of rainbow light that pours from the top of the page, behind the header Download
 * pill, onto the app window's top edge; plus the shot's tilt and glare. Our own WebGL2 shader (nothing taken from
 * OpenBot or React Bits). A white-hot core disperses into a red-to-violet halo, bright ripples stream down it, and
 * it splashes into a shimmering pool along the window's top with rainbow rim light running along the edge and down
 * the sides. The window is opaque to it: only the rim and a faint top sheen enter. A halftone dot field lights up
 * under the glow. Without WebGL2 a canvas 2D pillar and pool are drawn instead; under prefers-reduced-motion one
 * still, already-poured frame is drawn, with no flow and no tilt. The shader renders at 1x CSS pixels inside the
 * light's bounding box only, is capped at 60 fps (2D at 30), and idles while the tab is hidden or the block is
 * off-screen. The canvas never takes pointer events: interaction is read from pointer listeners.
 */
(() => {
  const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const q = s => document.querySelector(s);
  let cv = q('[data-beam]'); const pill = q('[data-dlpill]'), sec = q('[data-omher]'), shot = q('[data-app-shot]'), win = q('[data-app-win]') || shot;
  if (!cv || !pill || !sec || !shot) return;
  let winDy = 0;   // the window's top-left corner sits this fraction of its height below the top-right one (perspective in the composition)

  // the 01-08 section rail belongs to the OMH sections, not to the omher block
  new IntersectionObserver(es => document.body.classList.toggle('rail-off', es[0].isIntersecting), {rootMargin: '0px 0px -60% 0px'}).observe(sec);

  const PROF = /[?&]beamprof\b/.test(location.search);
  const stats = window.__beam = {mode: '', frames: 0, cpu: [], gpu: []};
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const ease = x => 1 - Math.pow(1 - clamp(x, 0, 1), 3);
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  const segDist = (px, py, ax, ay, bx, by) => {
    const vx = bx - ax, vy = by - ay, l2 = vx * vx + vy * vy || 1, t = clamp(((px - ax) * vx + (py - ay) * vy) / l2, 0, 1);
    return Math.hypot(px - ax - vx * t, py - ay - vy * t);
  };
  // the full spectrum, red to violet, for the 2D fallback
  const PAL = [[255, 64, 72], [255, 140, 40], [255, 220, 60], [90, 240, 100], [40, 210, 255], [70, 110, 255], [150, 70, 255]];

  const RES = 1;             // render scale against CSS pixels
  const FLOW = 1300;         // click ripple speed down the pillar, px/s
  let W = 0, H = 0;
  const S = {I: 0, pour: RM ? 1 : 0, reveal: RM ? 1 : 0, lean: null, near: 0, hov: 0, hovT: 0, mx: -1, my: -1, mouse: false,
    rim: 0, rimX: 0, rimY: 0, ft: 0, rx: 0, ry: 0, gl: 0, pulses: [-1, -1, -1, -1], pi: 0, burst: -9, t0: performance.now(), geo: null, css: {}};
  if (!RM) shot.style.setProperty('--reveal', '0');

  /* ---------- WebGL2 ---------- */
  const VS = `#version 300 es
uniform vec4 uBox; uniform vec2 uView;
void main(){
  vec2 c = vec2((gl_VertexID == 1 || gl_VertexID == 3) ? 1. : 0., gl_VertexID >= 2 ? 1. : 0.);
  vec2 px = mix(uBox.xy, uBox.zw, c);
  gl_Position = vec4(px.x / uView.x * 2. - 1., 1. - px.y / uView.y * 2., 0., 1.);
}`;
  const FS = `#version 300 es
precision highp float;
uniform vec2 uView, uA, uB;    // pillar top (x, y) and landing point on the window's top edge (CSS px)
uniform vec4 uWin;             // window left, top (at its right corner), right, bottom
uniform vec3 uRim;             // cursor over the window: x, y, strength
uniform vec4 uPill;            // the Download pill (left, top, right, bottom): the light stays off its label
uniform float uSlope;          // window top edge dy/dx
uniform float uScale, uTime, uFlow, uI, uPour, uK, uBright, uLand, uHov, uBurst;
uniform float uPulse[4];
out vec4 o;
float h21(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float vn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3. - 2. * f);
  return mix(mix(h21(i), h21(i + vec2(1, 0)), f.x), mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), f.x), f.y); }
float fbm(vec2 p){ float s = 0., a = .5; for (int i = 0; i < 3; i++){ s += a * vn(p); p = p * 2.03 + vec2(1.7, 9.2); a *= .5; } return s / .875; }
// the full spectrum, cyclic: red, orange, yellow, green, cyan, blue, violet, magenta (back to red)
vec3 spec(float h){
  h = fract(h) * 8.; int i = int(h); float f = fract(h);
  vec3 c[8] = vec3[8](vec3(1.,.2,.26), vec3(1.,.5,.12), vec3(.98,.84,.18), vec3(.3,.98,.36), vec3(.16,.88,1.), vec3(.32,.5,1.), vec3(.66,.38,1.), vec3(.96,.3,.8));
  return mix(c[i], c[(i + 1) % 8], f);
}
// a prism fan, luminance-balanced: x in -1..1 maps red..violet, h shifts the whole fan along the spectrum
vec3 prism(float x, float h){ x = clamp(x, -1., 1.); vec3 c = spec(clamp((x * .5 + .5) * .74 + h, 0., .76)); return c * min(pow(.58 / max(dot(c, vec3(.3, .55, .15)), .2), .55), 1.1); }
void main(){
  vec2 p = vec2(gl_FragCoord.x, uView.y * uScale - gl_FragCoord.y) / uScale;
  float T = uTime, F = uFlow, K = uK;
  float yb = max(uB.y, 40.);
  float ty = clamp(p.y / yb, 0., 1.);
  // the pillar's axis runs from uA (above the viewport) to the landing point, with a slow sway
  float ax = mix(uA.x, uB.x, clamp((p.y - uA.y) / (yb - uA.y), 0., 1.3)) + 5. * K * sin(T * .6 + p.y / 170.) * (1. - ty * .7);
  float d = p.x - ax;
  float edgeY = uWin.y + uSlope * (p.x - uWin.z);
  float dy = edgeY - p.y;                                   // > 0 above the window's top edge
  float inX = smoothstep(uWin.x - 1., uWin.x + 1., p.x) * smoothstep(uWin.z + 1., uWin.z - 1., p.x);
  float inside = inX * smoothstep(-.5, -1.5, dy) * step(p.y, uWin.w);   // the window's opaque UI
  float dyIn = max(-dy, 0.);
  // cheap exits: deep inside the window (only the side rims run down it) and far below its top beside it
  float sideD = min(abs(p.x - uWin.x), abs(p.x - uWin.z));
  bool inWin = p.x > uWin.x && p.x < uWin.z;
  if (sideD > 16. && uBurst < T - 1.4 && ((inWin && dyIn > 150. * K) || dyIn > 520. * K)) { o = vec4(0.); return; }
  // beside the window the volume keeps falling past its edge and fades; over the window it stops at the edge
  float vol = (1. - inside) * mix(1., exp(-dyIn / (160. * K)), smoothstep(0., 2., -dy));
  float reach = uPour * (yb + 260.);
  float env = smoothstep(reach + 2., reach - 70., p.y);
  float wk = K * (1. + .2 * uHov);
  float wh = mix(140., 265., pow(ty, .8)) * wk, wc = mix(13., 16., ty) * wk * (1. + .15 * uHov);
  float u = d / wh;
  float bloom = exp(-max(dy, 0.) / (60. * K)) * smoothstep(-30., 0., dy);   // the core widens where it lands
  // pouring: fast streaks and bright packets stream down, faint vertical streaks hang in the haze
  float st = fbm(vec2(d / (40. * K), (p.y - F * 560.) / 110.));
  float pk = smoothstep(.56, .92, fbm(vec2(d / (34. * K) + 4., (p.y - F * 700.) / 64.)));
  float hz = fbm(vec2(p.x / (46. * K), p.y / 600. - F * 1.1));
  float pul = 0.;
  for (int k = 0; k < 4; k++){
    float s = uPulse[k]; if (s < 0.) continue;
    float pos = (T - s) * ${FLOW}. - 40.;
    pul += exp(-pow((p.y - pos) / 50., 2.)) * smoothstep(yb + 80., yb - 20., pos) * step(0., pos);
  }
  float drift = .05 * sin((p.y - F * 300.) / 260.) + .03 * sin(T * .27) + .06 * (fbm(vec2(d / (60. * K), (p.y - F * 420.) / 140.)) - .5);
  float flank = smoothstep(.05, .3, abs(u));
  float energy = (.84 + (.2 * st + .55 * pk) * mix(.35, 1., flank)) * (1. + 1.4 * pul);
  float halo = (exp(-u * u * 2.8) * .85 + exp(-u * u * 1.2) * .15) * (.8 + .32 * hz);
  float sheath = exp(-d * d / (wc * wc * 9.));
  float core = exp(-d * d / (wc * wc * (1.6 + 50. * bloom)));
  // brightest at the top, where it enters behind the header, and again where it lands
  float lumY = (.8 + .1 * ty + .45 * bloom) * (.8 + .2 * smoothstep(10., 130., p.y));   // softer where it passes the header pills   // a touch dimmer behind the header pills
  vec3 disp = prism(u * 1.05, drift) * (1. + .25 * smoothstep(0., -1., u));
  disp = max(mix(vec3(dot(disp, vec3(.3, .55, .15))), disp, 1.15), 0.);
  vec3 col = mix(vec3(1.), disp, smoothstep(.03, .38, abs(u))) * halo * .52 * energy
    + mix(vec3(1., .97, .98), disp, .3) * sheath * .5 * energy
    + vec3(1., .99, .98) * core * (1.6 + .4 * pk + 1.4 * pul) * (.4 + .6 * smoothstep(30., 150., p.y));
  col *= lumY;
  // the landing: a splash and a wide elliptical pool spreading along the window's top, shimmering outward
  float dx = p.x - uB.x, dyA = max(dy, 0.);
  float pw = (dx < 0. ? .5 : .24) * uView.x * (1. + .22 * uHov) * mix(1., .8, K < .6 ? 1. : 0.);
  float sh = fbm(vec2(dx / (46. * K) - sign(dx) * F * 2.2, dyA / 11.));
  float ring = pow(.5 + .5 * sin(abs(dx) / (18. * K) - F * 9.), 3.) * exp(-abs(dx) / (300. * K));
  float span = smoothstep(uWin.x - 90. * K, uWin.x + 20., p.x) * smoothstep(uWin.z + 90. * K, uWin.z - 20., p.x);
  float pool = (exp(-pow(dx / pw, 2.) - pow(dyA / (58. * K), 2.)) + 1.1 * exp(-pow(dx / (340. * K), 2.) - pow(dyA / (38. * K), 2.))) * (.75 + .2 * sh + .25 * ring) * span;
  float splash = exp(-pow(dx / (85. * K), 2.) - pow(dyA / (24. * K), 2.)) + .45 * exp(-pow(dx / (190. * K), 2.) - pow(dyA / (40. * K), 2.));
  vec3 poolC = mix(prism(clamp(-dx / (pw * .85), -1., 1.), .02 * sin(T * .4)), vec3(1.), .1 + .35 * exp(-pow(dx / (150. * K), 2.)));
  float floorM = mix(exp(-dyIn / 40.), smoothstep(-1.5, .5, dy), inX);   // over the window the pool sits on its edge; beside it, it fades
  col += (poolC * pool * .62 + vec3(1., .98, .97) * splash * .7) * uLand * floorM * (1. + .5 * pul);
  // splash droplets thrown sideways out of the impact
  vec2 g = vec2((abs(dx) - F * 140.) / 15., (dyA + F * 30.) / 9.); vec2 gi = floor(g), gf = fract(g);
  float r = h21(gi + 17. + step(0., dx) * 31.);
  float drop = step(.93, r) * smoothstep(.45, .05, length(gf - .5)) * (.5 + .5 * sin(T * (3. + r * 6.) + r * 50.));
  col += mix(prism(-dx / pw, 0.), vec3(1.), .45) * drop * exp(-pow(dx / (pw * .7), 2.) - dyA / (36. * K)) * .7 * uLand * step(0., dy);
  // halftone: a dot field that lights up under the glow (pillar haze and pool)
  float G = clamp(halo * .4 * vol * smoothstep(.35, .9, abs(u)) + pool * .7 * uLand * floorM, 0., 1.);   // dots on the flanks and under the pool, not in the core
  float fall = halo * vol * (1. - clamp(pool * 3., 0., 1.));
  vec2 cell = fract(vec2(p.x / 9., (p.y - F * 220. * fall) / 9.)) - .5;
  cell.y /= 1. + 1.6 * fall;
  float rad = .05 + .22 * sqrt(G);
  float dot_ = smoothstep(rad + .12, rad - .12, length(cell));
  col += mix(disp, poolC, clamp(pool * 2., 0., 1.)) * dot_ * G * .2;
  // the pillar does not wash over the UI
  col *= vol * env;
  // rainbow rim light: along the top edge (strongest under the pool, sparks running outward) and partway down the sides
  float hot = exp(-pow(dx / (110. * K), 2.));
  float onTop = exp(-pow((dy + .6) / (1.2 + 1.3 * hot), 2.)) * inX;
  float hue = p.x / 420. - T * .12;
  float runs = pow(.5 + .5 * sin(abs(dx) / 26. - F * 10.), 10.) * exp(-abs(dx) / 520.);
  float topI = .7 + 1.5 * exp(-pow(dx / (pw * 1.1), 2.)) + 1.2 * exp(-pow(dx / (70. * K), 2.)) + .9 * runs + 1.4 * uRim.z * exp(-pow((p.x - uRim.x) / 130., 2.));
  vec3 rimC = mix(prism(clamp(-dx / (pw * .7), -1., 1.), .02 * sin(T * .4)), vec3(1.), .15 + .55 * exp(-pow(dx / (90. * K), 2.)));
  float sideR = exp(-pow((p.x - uWin.z + .6) / 1.4, 2.)) + .45 * exp(-max(p.x - uWin.z, 0.) / 10.) * step(uWin.z, p.x);
  float sideL = .8 * exp(-pow((p.x - uWin.x - .6) / 1.3, 2.)) + .25 * exp(-max(uWin.x - p.x, 0.) / 7.) * step(p.x, uWin.x);
  float hgt = uWin.w - uWin.y;
  float down = smoothstep(-2., 2., -dy) * step(p.y, uWin.w);
  float rDrop = exp(-dyIn / (hgt * .45)) * (.7 + 1.4 * exp(-pow((uB.x - uWin.z) / (wh * 1.8), 2.)));
  float lDrop = exp(-dyIn / (hgt * .2)) * (.18 + .9 * exp(-pow((uB.x - uWin.x) / pw, 2.)));
  float flowR = .45 + 1.1 * smoothstep(.35, .85, fbm(vec2(3., (dyIn - F * 320.) / 46.)));
  float curY = uRim.z * exp(-pow((p.y - uRim.y) / 110., 2.));
  vec3 rim = rimC * onTop * topI * 1.1
    + mix(spec(p.y / 300. - T * .1 + .3), vec3(1.), .2) * sideR * down * (rDrop * flowR + 1.2 * curY * smoothstep(uWin.x + (uWin.z - uWin.x) * .5, uWin.z, uRim.x))
    + mix(spec(p.y / 300. - T * .1 + .7), vec3(1.), .2) * sideL * down * (lDrop * flowR + 1.2 * curY * smoothstep(uWin.x + (uWin.z - uWin.x) * .5, uWin.x, uRim.x));
  col += rim * uLand * (1. + .6 * pul);
  // the impact lip: a few px of white-hot light on the title bar right under the splash, then one faint top-edge sheen
  col += mix(vec3(1.), poolC, .35) * inside * exp(-dyIn / (5. * K)) * exp(-pow(dx / (90. * K), 2.)) * .55 * uLand * (1. + .6 * pul);
  // light on the glass: the title bar (window chrome, no content) catches it, the UI below gets only a thin streaked wash
  float tbar = exp(-dyIn / (16. * K)) * .75 + smoothstep(32. * K, 14. * K, dyIn) * .25;
  float rain = .75 + .5 * fbm(vec2(p.x / (26. * K), (dyIn - F * 180.) / 60.));
  col += mix(prism(clamp(-dx / (pw * .55), -1., 1.), 0.), vec3(1.), .18 + .3 * exp(-pow(dx / (80. * K), 2.))) * inside * (tbar * (.45 + .75 * exp(-pow(dx / (200. * K), 2.))) + exp(-dyIn / (90. * K)) * .06 * rain) * exp(-pow(dx / (pw * .9), 2.)) * uLand;
  // click burst: spectral sparks thrown up from the impact
  float age = T - uBurst;
  if (age > 0. && age < 1.3){
    float fade = 1. - age / 1.3;
    for (int k = 0; k < 18; k++){
      float fk = float(k), a = -3.1416 * (.08 + .84 * h21(vec2(fk, 3.7))), v = 140. + 240. * h21(vec2(fk, 9.1));
      vec2 pos = uB + vec2(cos(a), sin(a)) * v * age + vec2(0., 280. * age * age);
      col += mix(spec(fk / 18. * .86), vec3(1.), .25) * exp(-length(p - pos) / 1.6) * fade * 1.6 * (1. - inside);
    }
  }
  vec2 pc = (uPill.xy + uPill.zw) * .5, ph = (uPill.zw - uPill.xy) * .5;
  vec2 pq = abs(p - pc) - ph + ph.y; float pd = length(max(pq, 0.)) + min(max(pq.x, pq.y), 0.) - ph.y;
  col *= smoothstep(-2., 10., pd);
  col *= uI * uBright;
  // tone map, then cap: the light never reaches full opacity
  col = (1. - exp(-col * 1.25)) * .94;
  col += (h21(gl_FragCoord.xy + fract(T) * 61.) - .5) / 255. * step(.004, max(col.r, max(col.g, col.b)));
  o = vec4(col, max(col.r, max(col.g, col.b)));
}`;

  let gl = null, prog = null, U = {};
  if (window.WebGL2RenderingContext) {
    try { gl = cv.getContext('webgl2', {alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false, powerPreference: 'low-power'}); } catch (e) { gl = null; }
  }
  if (gl) {
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    try {
      prog = gl.createProgram();
      gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
      gl.useProgram(prog); gl.bindVertexArray(gl.createVertexArray());
      for (const n of ['uBox', 'uView', 'uA', 'uB', 'uWin', 'uRim', 'uPill', 'uSlope', 'uScale', 'uTime', 'uFlow', 'uI', 'uPour', 'uK', 'uBright', 'uLand', 'uHov', 'uBurst', 'uPulse']) U[n] = gl.getUniformLocation(prog, n);
    } catch (e) { console.warn('[beam] shader failed, using canvas 2D', e); gl = null; }
  }
  // a context that failed to build its program cannot hand the canvas to 2D; swap in a fresh canvas
  let cx = null;
  if (!gl) {
    if (prog !== null) { const n = cv.cloneNode(false); cv.replaceWith(n); cv = n; }
    cx = cv.getContext('2d');
  }
  stats.mode = gl ? 'webgl2' : '2d';
  document.documentElement.dataset.beam = stats.mode + (RM ? '-still' : '');
  console.info('[beam] ' + stats.mode + (RM ? ' (reduced motion: still frame)' : ''));
  cv.addEventListener('webglcontextlost', e => { e.preventDefault(); gl = null; stats.mode = 'lost'; });

  function size() {
    W = innerWidth; H = innerHeight;
    const k = gl ? RES : Math.min(devicePixelRatio || 1, 1.5);
    cv.width = Math.max(1, Math.round(W * k)); cv.height = Math.max(1, Math.round(H * k));
    winDy = parseFloat(getComputedStyle(shot).getPropertyValue('--win-dy')) || 0;
  }

  function drawGL(f) {
    gl.viewport(0, 0, cv.width, cv.height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    if (S.I <= .002) return;
    const sr = f.sr, pw = .36 * W * 1.25;
    // the light's box: the pillar and its halo, the pool, the rim along the top and down both sides
    const l = clamp(Math.min(f.x1 - pw * 1.6, sr.left - 24, f.x0 - 420 * f.k), 0, W), r = clamp(Math.max(f.x1 + .25 * W, sr.right + 60, f.x0 + 420 * f.k), 0, W);
    const b = clamp(Math.max(f.y1 + 30, sr.top + sr.height * .8), 0, H);
    if (r - l < 2 || b < 2) return;
    gl.uniform4f(U.uBox, l, 0, r, b); gl.uniform2f(U.uView, W, H); gl.uniform1f(U.uScale, cv.width / W);
    gl.uniform2f(U.uA, f.x0, f.y0); gl.uniform2f(U.uB, f.x1, f.y1);
    gl.uniform4f(U.uWin, sr.left, sr.top, sr.right, sr.bottom); gl.uniform1f(U.uSlope, f.slope);
    gl.uniform3f(U.uRim, S.rimX, S.rimY, S.rim); gl.uniform4f(U.uPill, f.p.left, f.p.top, f.p.right, f.p.bottom);
    gl.uniform1f(U.uTime, f.t); gl.uniform1f(U.uFlow, S.ft); gl.uniform1f(U.uI, S.I); gl.uniform1f(U.uPour, ease(S.pour)); gl.uniform1f(U.uK, f.k);
    gl.uniform1f(U.uBright, 1 + .35 * S.near + .45 * S.hov); gl.uniform1f(U.uLand, f.land);
    gl.uniform1f(U.uHov, S.hov); gl.uniform1f(U.uBurst, S.burst);
    gl.uniform1fv(U.uPulse, S.pulses);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  /* ---------- canvas 2D fallback: a spectral pillar, a pool on the window's top and a rim ---------- */
  const dust = Array.from({length: 46}, (_, i) => ({u: Math.random() * 2 - 1, f: Math.random(), v: .5 + Math.random() * .6, a: .3 + Math.random() * .5, s: Math.random() < .25 ? 2 : 1.3, ph: Math.random() * 6.3, c: i % 7}));
  const rgba = (i, a) => `rgba(${PAL[i % 7].join(',')},${a})`;
  function draw2d(f, dt) {
    const k0 = cv.width / W;
    cx.setTransform(1, 0, 0, 1, 0, 0); cx.clearRect(0, 0, cv.width, cv.height);
    if (S.I <= .002) return;
    const amp = Math.min(1, S.I * (1 + .3 * S.near + .4 * S.hov)), sr = f.sr, k = f.k, yb = f.y1;
    const reach = (yb + 60) * ease(S.pour), sk = (f.x1 - f.x0) / Math.max(yb - f.y0, 1), wh = 150 * k * (1 + .2 * S.hov);
    cx.save(); cx.setTransform(k0, 0, 0, k0, 0, 0);
    // the pillar stops at the window's top edge
    cx.beginPath(); cx.moveTo(0, 0); cx.lineTo(W, 0); cx.lineTo(W, sr.top + (W - sr.right) * f.slope); cx.lineTo(0, sr.top - sr.right * f.slope); cx.closePath(); cx.clip();
    cx.save(); cx.transform(1, 0, sk, 1, f.x0 - sk * f.y0, 0);   // skew: x' = x + sk * (y - y0)
    let g = cx.createLinearGradient(-wh, 0, wh, 0);
    g.addColorStop(0, rgba(0, 0)); g.addColorStop(.14, rgba(0, .2)); g.addColorStop(.26, rgba(1, .26)); g.addColorStop(.36, rgba(2, .3));
    g.addColorStop(.46, 'rgba(255,252,248,.55)'); g.addColorStop(.5, 'rgba(255,255,255,.95)'); g.addColorStop(.54, 'rgba(255,252,248,.55)');
    g.addColorStop(.64, rgba(3, .3)); g.addColorStop(.74, rgba(4, .28)); g.addColorStop(.86, rgba(5, .24)); g.addColorStop(1, rgba(6, 0));
    cx.globalAlpha = amp * (RM ? 1 : .94 + .06 * Math.sin(f.t * 2.1)); cx.fillStyle = g; cx.fillRect(-wh, 0, wh * 2, reach);
    cx.globalAlpha = 1; cx.globalCompositeOperation = 'destination-out';
    g = cx.createLinearGradient(0, reach - 60, 0, reach); g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, '#000');
    cx.fillStyle = g; cx.fillRect(-wh, reach - 60, wh * 2, 60);
    cx.globalCompositeOperation = 'source-over';
    for (const d of dust) {
      if (!RM) { d.f += d.v * dt / 1000; if (d.f > 1) { d.f = 0; d.u = Math.random() * 2 - 1; } }
      const py = d.f * reach, px = d.u * wh * .5 + Math.sin(f.t * 1.1 + d.ph) * 3;
      const a = d.a * amp * Math.min(1, d.f * 6) * (.6 + .4 * Math.sin(f.t * 3.3 + d.ph));
      if (a <= .02) continue;
      cx.globalAlpha = Math.min(1, a); cx.fillStyle = `rgb(${PAL[d.c].join(',')})`; cx.fillRect(px, py, d.s, d.s);
    }
    cx.restore();
    if (f.land > 0) {
      const pw = .32 * W * (1 + .2 * S.hov);
      cx.save(); cx.translate(f.x1, yb); cx.scale(1, 64 * k / pw);
      g = cx.createRadialGradient(0, 0, 0, 0, 0, pw); g.addColorStop(0, 'rgba(255,252,248,.75)'); g.addColorStop(.18, 'rgba(255,220,60,.32)'); g.addColorStop(.38, 'rgba(90,240,100,.2)'); g.addColorStop(.6, 'rgba(40,210,255,.15)'); g.addColorStop(.8, 'rgba(150,70,255,.08)'); g.addColorStop(1, 'rgba(150,70,255,0)');
      cx.globalAlpha = Math.min(1, f.land * amp); cx.fillStyle = g; cx.beginPath(); cx.arc(0, 0, pw, 0, 6.2832); cx.fill();
      cx.restore();
    }
    cx.restore();
    if (f.land > 0) {   // rim along the top edge
      cx.save(); cx.setTransform(k0, 0, 0, k0, 0, 0);
      const g2 = cx.createLinearGradient(sr.left, 0, sr.right, 0);
      for (let i = 0; i <= 6; i++) g2.addColorStop(i / 6, rgba(i, .25 + .65 * Math.exp(-Math.pow((sr.left + sr.width * i / 6 - f.x1) / (.3 * W), 2))));
      cx.globalAlpha = Math.min(1, f.land * amp); cx.fillStyle = g2; cx.fillRect(sr.left, sr.top - 1, sr.width, 2);
      cx.restore();
    }
    cx.globalAlpha = 1;
  }

  /* ---------- per frame ---------- */
  const setVar = (n, v) => { if (S.css[n] !== v) { S.css[n] = v; shot.style.setProperty(n, v); } };
  function frame(now, dt) {
    const t = RM ? 4 : (now - S.t0) / 1000;
    const p = pill.getBoundingClientRect(), sr = win.getBoundingClientRect();
    // the window's top edge runs from its top-right corner (sr.top) down to the top-left one
    const slope = -winDy * sr.height / Math.max(sr.width, 1), edgeAt = x => sr.top + (x - sr.right) * slope + 1;
    const k = clamp(W / 1440, .36, 1.15);
    const want = sr.bottom > H * .2 && p.width > 0;
    const vis = want ? smooth(90, 140, sr.top) : 0;   // the pillar needs room above the window: none on a tight layout or once scrolled past
    if (RM) S.I = vis; else S.I = clamp(S.I + clamp(vis - S.I, -dt / 260, dt / 420), 0, 1);
    if (want && !RM) S.pour = Math.min(1, S.pour + dt / 1100);
    if (S.pour >= 1 && S.reveal < 1) { S.reveal = Math.min(1, S.reveal + dt / 1300); setVar('--reveal', ease(S.reveal).toFixed(3)); }
    const kf = ms => RM ? 1 : 1 - Math.exp(-dt / ms);
    S.hov += (S.hovT - S.hov) * kf(160);
    S.ft += (RM ? 0 : dt / 1000) * (1 + .7 * S.hov);
    // landing near the window's top-right corner; the pillar enters from above the viewport behind the Download pill,
    // leaning at most ~20deg, and both ends lean toward the cursor
    const base = W < 600 ? sr.right - sr.width * .16 : sr.right - sr.width * .24;
    const live = !RM && S.mx >= 0 && S.my < sr.bottom + 120;
    const target = live ? clamp((S.mx - base) * .07, -46, 46) : 0;
    S.lean = S.lean == null || RM ? target : S.lean + (target - S.lean) * kf(300);
    const x1 = base + S.lean * .7, y1 = edgeAt(x1);
    const top = clamp(W < 600 ? p.left + p.width * .5 : p.left - 36, base - 10, base + Math.max(sr.top, 60) * .16);
    const x0 = top + S.lean * 1.6, y0 = -40;
    const nearT = live ? smooth(300, 40, segDist(S.mx, S.my, x0, Math.max(y0, 0), x1, y1)) : 0;
    S.near += (nearT - S.near) * kf(220);
    // shot tilt and glare follow a mouse over the shot
    const over = !RM && S.mouse && S.mx >= sr.left && S.mx <= sr.right && S.my >= sr.top && S.my <= sr.bottom;
    const nx = over ? (S.mx - sr.left) / sr.width : .5, ny = over ? (S.my - sr.top) / sr.height : .5;
    S.rim += ((over ? 1 : 0) - S.rim) * kf(200);
    if (over) { S.rimX = S.mx; S.rimY = S.my; }
    // tilt only while the pointer moves; at rest the shot eases back to a flat, crisply rastered layer
    const moving = over && now - (S.moved || 0) < 420;
    S.ry += ((moving ? (nx - .5) * 6 : 0) - S.ry) * kf(moving ? 160 : 170);   // max 3deg
    S.rx += ((moving ? (.5 - ny) * 5 : 0) - S.rx) * kf(moving ? 160 : 170);   // max 2.5deg
    if (!moving && Math.abs(S.rx) + Math.abs(S.ry) < .35) S.rx = S.ry = 0;    // snap flat: no resampled raster at rest
    S.gl += ((over ? 1 : 0) - S.gl) * kf(200);
    if (over) { setVar('--gx', (nx * win.offsetWidth).toFixed(0) + 'px'); setVar('--gy', (ny * win.offsetHeight).toFixed(0) + 'px'); }
    const tilted = Math.abs(S.rx) + Math.abs(S.ry) > 0;
    if (tilted !== S.tilted) { S.tilted = tilted; shot.classList.toggle('is-tilt', tilted); }
    setVar('--ry', S.ry.toFixed(2) + 'deg'); setVar('--rx', S.rx.toFixed(2) + 'deg'); setVar('--glare', S.gl.toFixed(3));
    const land = ease((S.pour - .6) / .4);
    const hit = S.burst > 0 && t > S.burst ? Math.exp(-(t - S.burst) * 3) : 0;
    setVar('--lit', (S.I * land * (1 + .25 * S.near + .3 * S.hov)).toFixed(2)); setVar('--bx', (x1 - sr.left).toFixed(0) + 'px'); setVar('--hit', hit.toFixed(2));
    S.geo = stats.geo = {x0, y0, x1, y1, len: y1 - y0};
    const f = {t, x0, y0, x1, y1, sr, land, slope, k, p};
    if (gl) drawGL(f); else if (cx) draw2d(f, dt);
  }

  let raf = 0, last = 0, seen = true;
  const minDt = gl ? 15 : 31;   // 60 fps for the shader, 30 for the 2D fallback
  function clearAll() { if (gl) { gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); } else if (cx) { cx.setTransform(1, 0, 0, 1, 0, 0); cx.clearRect(0, 0, cv.width, cv.height); } }
  function loop(now) {
    raf = 0;
    if (document.hidden || !seen) { clearAll(); last = 0; return; }
    if (last && now - last < minDt) { raf = requestAnimationFrame(loop); return; }
    const dt = last ? Math.min(100, now - last) : 16; last = now;
    if (PROF) performance.mark('beam:s');
    const c0 = performance.now();
    frame(now, dt);
    const c1 = performance.now();
    if (PROF) { performance.measure('beam:frame', 'beam:s'); if (gl) { gl.finish(); stats.gpu.push(performance.now() - c1); } }
    stats.cpu.push(c1 - c0); if (stats.cpu.length > 3000) stats.cpu.shift(); stats.frames++;
    raf = requestAnimationFrame(loop);
  }
  function kick() {
    if (RM) { if (!raf) raf = requestAnimationFrame(now => { raf = 0; if (!document.hidden && seen) frame(now, 0); else clearAll(); }); return; }
    if (!raf) { last = 0; raf = requestAnimationFrame(loop); }
  }

  /* ---------- interaction ---------- */
  function pulse() {
    if (RM || !S.geo) return;
    const t = (performance.now() - S.t0) / 1000;
    S.pulses[S.pi] = t; S.pi = (S.pi + 1) % 4;
    S.burst = t + (S.geo.y1 + 40) / FLOW;
  }
  addEventListener('pointermove', e => { S.mx = e.clientX; S.my = e.clientY; S.mouse = e.pointerType === 'mouse'; S.moved = performance.now(); }, {passive: true});
  document.documentElement.addEventListener('pointerleave', () => { S.mx = S.my = -1; });
  sec.addEventListener('click', e => {
    if (e.target.closest('a,button,code,.omher__cmd')) return;
    const r = shot.getBoundingClientRect(), g = S.geo;
    const onShot = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
    if (onShot || (g && segDist(e.clientX, e.clientY, g.x0, g.y0, g.x1, g.y1) < 120)) pulse();
  });
  for (const [ev, v] of [['pointerenter', 1], ['pointerleave', 0], ['focus', 1], ['blur', 0]]) pill.addEventListener(ev, () => { S.hovT = v; });

  size();
  addEventListener('resize', () => { size(); kick(); });
  document.addEventListener('visibilitychange', kick);
  if (RM) addEventListener('scroll', kick, {passive: true});
  new IntersectionObserver(es => { seen = es[0].isIntersecting; kick(); }).observe(sec);
  kick();
})();
