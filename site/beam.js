/*!
 * omher.app top block: the light that falls from the header Download pill onto the app shot, and the shot's
 * tilt and glare. Our own WebGL2 shader (nothing taken from OpenBot or React Bits). Without WebGL2 a canvas 2D
 * column is drawn instead; under prefers-reduced-motion one still frame is drawn, with no flow and no tilt.
 * The shader renders at 1x CSS pixels inside the beam's bounding box only, is capped at 60 fps, and idles
 * while the tab is hidden or the block is off-screen. The canvas never takes pointer events: interaction is
 * read from pointer listeners, so the buttons under it stay clickable.
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

  const RES = 1;             // render scale against CSS pixels (the box is small: full-res keeps the bands crisp)
  const FLOW = 1100;         // ripple speed down the beam, px/s
  let W = 0, H = 0;
  const S = {I: 0, pour: RM ? 1 : 0, reveal: RM ? 1 : 0, lean: null, near: 0, hov: 0, hovT: 0, mx: -1, my: -1, mouse: false,
    rx: 0, ry: 0, gl: 0, pulses: [-1, -1, -1, -1], pi: 0, burst: -9, t0: performance.now(), geo: null, css: {}};
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
uniform vec2 uView, uA, uB;
uniform vec3 uShot;            // window left, right, top edge at the impact (CSS px)
uniform float uSlope;          // window top edge dy/dx
uniform float uScale, uTime, uI, uPour, uWide, uBright, uLand, uHov, uBurst, uStill;
uniform float uPulse[4];
out vec4 o;
float h21(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float vn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3. - 2. * f);
  return mix(mix(h21(i), h21(i + vec2(1, 0)), f.x), mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), f.x), f.y); }
float fbm(vec2 p){ float s = 0., a = .5; for (int i = 0; i < 4; i++){ s += a * vn(p); p = p * 2.03 + vec2(1.7, 9.2); a *= .5; } return s; }
// the full spectrum, cyclic: red, orange, yellow, green, cyan, blue, violet, magenta (back to red)
vec3 spec(float h){
  h = fract(h) * 8.; int i = int(h); float f = fract(h);
  vec3 c[8] = vec3[8](vec3(1.,.2,.26), vec3(1.,.5,.12), vec3(.98,.84,.18), vec3(.3,.98,.36), vec3(.16,.88,1.), vec3(.32,.5,1.), vec3(.66,.38,1.), vec3(.96,.3,.8));
  return mix(c[i], c[(i + 1) % 8], f);
}
// a prism fan: x in -1..1 maps red..violet, h shifts the whole fan along the spectrum
vec3 prism(float x, float h){ x = clamp(x, -1., 1.); x = sign(x) * pow(abs(x), 1.15); vec3 c = spec(clamp((x * .5 + .5) * .7 + h, 0., .72)); float w = smoothstep(.45, .1, (x * .5 + .5) * .7 + h); return c * min(pow(.58 / max(dot(c, vec3(.3, .55, .15)), .2), .55), 1.05) * (1. + .15 * w); }
vec3 sat(vec3 c, float k){ return max(mix(vec3(dot(c, vec3(.3, .55, .15))), c, k), 0.); }
void main(){
  vec2 p = vec2(gl_FragCoord.x, uView.y * uScale - gl_FragCoord.y) / uScale;
  float T = uTime;
  vec2 ab = uB - uA; float L = max(length(ab), 1.); vec2 dir = ab / L, nrm = vec2(-dir.y, dir.x);
  vec2 ap = p - uA; float along = dot(ap, dir), d = dot(ap, nrm);
  float edgeY = uShot.z + uSlope * (p.x - uB.x);
  float t = clamp(along / L, 0., 2.);   // past the impact on the far side of a slanted beam the fan keeps widening (no shelf)
  float reach = uPour * (L + 160.);   // once poured, every band runs on until the window's edge clips it
  float env = smoothstep(reach + 2., reach - 36., along) * smoothstep(-4., 3., along);
  // the volume stops at the window's top edge: a hard clip with a 12px feather above it, so no haze reaches the UI
  float above = smoothstep(edgeY, edgeY - 12., p.y) * .55 + smoothstep(edgeY, edgeY - 2., p.y) * .45;
  // the column is born ~40px under the pill (its source is the pill's own glow), narrow, then fans out toward the window
  // uA sits 7px inside the pill, whose own glow is the source
  float born = smoothstep(52., 124., along * dir.y);   // the header is 68px: the column shows from ~40px below it
  float tt = t * t, wc = mix(1.6, 5.6, tt) * uWide, wb = mix(5., 74., tt) * uWide, wo = wb * 1.5;
  float u = d / wb * 1.15;
  float flow = fbm(vec2(u * .55, (along - T * 230.) / 72.));
  float streak = fbm(vec2(u * 1.2 + 3., (along - T * 410.) / 34.));
  float pul = 0.;
  for (int k = 0; k < 4; k++){
    float s = uPulse[k]; if (s < 0.) continue;
    float pos = (T - s) * ${FLOW}.;
    pul += exp(-pow((along - pos) / 46., 2.)) * smoothstep(L + 90., L - 30., pos) * step(0., pos);
  }
  // dispersion across the width, red on one side and violet on the other; the hue drifts slowly down the beam
  float drift = .045 * sin((along - T * 140.) / 200.) + .025 * sin(T * .31) + (flow - .5) * .03;
  vec3 sc = mix(vec3(.66, .64, .7), prism(u, drift), smoothstep(.22, .62, t));
  float band = smoothstep(1.1, .55, abs(u));
  float energy = (.86 + .2 * flow + .1 * streak * streak) * (1. + 1.6 * pul);
  float core = exp(-d * d / (wc * wc * 1.3)), sheath = exp(-d * d / (wc * wc * 6.)), halo = exp(-d * d / (wo * wo));
  // brightest a little under the source, easing off toward the window (the impact brightens it again)
  vec3 col = sat(sc, 1.) * band * energy * (.5 + .32 * smoothstep(.05, .35, t) - .3 * smoothstep(.55, 1., t))
    + vec3(.9, .9, .96) * halo * .015 * (.7 + .3 * flow)
    + vec3(1., .99, .98) * (core * .48 + sheath * .1) * (.9 + .1 * streak + 1.2 * pul) * mix(1.2, .22, smoothstep(.3, .95, t));
  // sparkles drifting down inside the column, each in one spectral hue
  vec2 g = vec2(d / 12., (along - T * 90.) / 24.); vec2 gi = floor(g), gf = fract(g);
  float r = h21(gi + 17.);
  vec2 sp = vec2(.2 + .6 * h21(gi + 7.1), .2 + .6 * h21(gi + 3.3));
  float spk = step(.95, r) * smoothstep(1.7, .2, length((gf - sp) * vec2(11., 24.)));
  spk *= (.45 + .55 * sin(T * (2.5 + r * 5.) + r * 40.)) * exp(-abs(d) / (wb * 1.2)) * smoothstep(.04, .2, t);
  col += mix(prism(u, drift), vec3(1.), .4) * spk * .06;
  col *= born * env * above * (1. + .45 * (uBright - 1.));
  // impact on the shot's top edge: a rainbow fan that pools on the edge, and a spectral rim running along it
  float dx = p.x - uB.x, dy = edgeY - p.y;
  float inX = smoothstep(uShot.x - 2., uShot.x + 70., p.x) * smoothstep(uShot.y + 2., uShot.y - 70., p.x);
  float lift = smoothstep(-1., .5, dy);   // nothing but the rim line and the sheen below crosses into the window
  float fw = 90. * uWide;
  float fan = exp(-pow(dx / fw, 2.) - pow(max(dy, 0.) / 5., 2.)) * lift * inX;
  float pool = exp(-pow(dx / (fw * 1.3), 2.) - pow(max(dy, 0.) / 9., 2.)) * lift * inX;
  float cz = fbm(vec2(dx / 70. - T * .3, dy / 22. + T * .6));
  float edge = exp(-pow((dy - .5) / 1.4, 2.)) * inX;
  float spread = (smoothstep(1.5, .7, abs(u)) * .75 + exp(-pow(dx / 44., 2.)) * .55) * (.86 + .14 * sin(abs(dx) * .02 - T * 2.4));
  float sw = .05 * sin(T * .45);
  vec3 imp = sat(prism(-dx / fw, sw), 1.25) * fan * (.4 + .16 * cz) + prism(-dx / (fw * 1.7), sw) * pool * (.12 + .05 * cz) + sat(prism(clamp(u, -1.2, 1.2) * .9, drift), 1.2) * edge * spread * 1.45
    + vec3(1., .98, .97) * exp(-pow(dx / 30., 2.) - pow((dy - .5) / 2.6, 2.)) * inX * .62 + sat(prism(-dx / fw, sw), 1.2) * exp(-pow(dx / (fw * .9), 2.) - pow(max(dy, 0.) / 14., 2.)) * lift * inX * .16;
  float arrive = 0.;
  for (int k = 0; k < 4; k++){ float s = uPulse[k]; if (s < 0.) continue; float a = T - s - L / ${FLOW}.; arrive += step(0., a) * exp(-a * 5.); }
  col += imp * uLand * (1. + 1.4 * arrive) * (1. + .45 * (uBright - 1.));
  // click burst: spectral sparks thrown up from the impact
  float age = T - uBurst;
  if (age > 0. && age < 1.3){
    float fade = 1. - age / 1.3;
    for (int k = 0; k < 18; k++){
      float fk = float(k), a = -3.1416 * (.08 + .84 * h21(vec2(fk, 3.7))), v = 120. + 220. * h21(vec2(fk, 9.1));
      vec2 pos = uB + vec2(cos(a), sin(a)) * v * age + vec2(0., 260. * age * age);
      float s = exp(-length(p - pos) / 1.5) * fade;
      col += mix(spec(fk / 18. * .86), vec3(1.), .25) * s * 1.6 * lift;
    }
  }
  // inside the window: one faint spectral sheen under the impact, capped at 6%
  col += mix(prism(-dx / 320., sw), vec3(1.), .5) * (1. - lift) * exp(dy / 40.) * exp(-pow(dx / 220., 2.)) * inX * .045 * uLand;
  col *= uI;
  // tone map, then cap: the light never reaches full opacity, so nothing under it is washed out
  col = (1. - exp(-col * 1.1)) * .9;
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
      for (const n of ['uBox', 'uView', 'uA', 'uB', 'uShot', 'uSlope', 'uScale', 'uTime', 'uI', 'uPour', 'uWide', 'uBright', 'uLand', 'uHov', 'uBurst', 'uStill', 'uPulse']) U[n] = gl.getUniformLocation(prog, n);
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
    const cs = getComputedStyle(shot);
    winDy = parseFloat(cs.getPropertyValue('--win-dy')) || 0;
  }

  function drawGL(f) {
    gl.viewport(0, 0, cv.width, cv.height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    if (S.I <= .002) return;
    const l = clamp(Math.min(f.x0 - 200, f.x1 - 620, f.sr.left), 0, W), r = clamp(Math.max(f.x0 + 200, f.x1 + 620, f.sr.right), 0, W);
    const t = clamp(Math.min(f.y0 - 60, f.y1 - 200), 0, H), b = clamp(f.y1 + 30, 0, H);
    if (r - l < 2 || b - t < 2) return;
    gl.uniform4f(U.uBox, l, t, r, b); gl.uniform2f(U.uView, W, H); gl.uniform1f(U.uScale, cv.width / W);
    gl.uniform2f(U.uA, f.x0, f.y0); gl.uniform2f(U.uB, f.x1, f.y1); gl.uniform3f(U.uShot, f.sr.left, f.sr.right, f.y1); gl.uniform1f(U.uSlope, f.slope);
    gl.uniform1f(U.uTime, f.t); gl.uniform1f(U.uI, S.I); gl.uniform1f(U.uPour, ease(S.pour));
    gl.uniform1f(U.uWide, 1 + .16 * S.near); gl.uniform1f(U.uBright, 1 + .3 * S.near + .4 * S.hov); gl.uniform1f(U.uLand, f.land);
    gl.uniform1f(U.uHov, S.hov); gl.uniform1f(U.uBurst, S.burst); gl.uniform1f(U.uStill, RM ? 1 : 0);
    gl.uniform1fv(U.uPulse, S.pulses);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  /* ---------- canvas 2D fallback: the earlier column, recoloured to the spectrum ---------- */
  const SW = 320, SH = 1024; let sprite = null;
  function build2d() {
    const c = document.createElement('canvas'); c.width = SW; c.height = SH; const g = c.getContext('2d'), m = SW / 2;
    const rgba = (i, a) => `rgba(${PAL[i % 7].join(',')},${a})`;
    const cone = (t, b, stops) => { const gr = g.createLinearGradient(m - b, 0, m + b, 0); for (const [o, col] of stops) gr.addColorStop(o, col); g.fillStyle = gr; g.beginPath(); g.moveTo(m - t, 0); g.lineTo(m + t, 0); g.lineTo(m + b, SH); g.lineTo(m - b, SH); g.closePath(); g.fill(); };
    cone(14, 190, [[0, rgba(0, 0)], [.1, rgba(0, .2)], [.24, rgba(1, .22)], [.36, rgba(2, .22)], [.5, 'rgba(255,250,245,.2)'], [.6, rgba(3, .22)], [.72, rgba(4, .22)], [.84, rgba(5, .2)], [.92, rgba(6, .16)], [1, rgba(6, 0)]]);
    cone(8, 70, [[0, rgba(0, 0)], [.2, rgba(1, .22)], [.38, rgba(2, .22)], [.5, 'rgba(255,255,255,.45)'], [.62, rgba(4, .22)], [.8, rgba(5, .22)], [1, rgba(6, 0)]]);
    cone(5, 22, [[0, 'rgba(255,255,255,0)'], [.5, 'rgba(255,255,255,.55)'], [1, 'rgba(255,255,255,0)']]);
    g.globalCompositeOperation = 'destination-in';
    const v = g.createLinearGradient(0, 0, 0, SH); v.addColorStop(0, 'rgba(0,0,0,.7)'); v.addColorStop(.85, 'rgba(0,0,0,.9)'); v.addColorStop(1, '#000');
    g.fillStyle = v; g.fillRect(0, 0, SW, SH);
    sprite = c;
  }
  const dust = Array.from({length: 40}, (_, i) => ({u: Math.random() * 2 - 1, f: Math.random(), v: .035 + Math.random() * .07, a: .25 + Math.random() * .5, s: Math.random() < .2 ? 2 : 1.2, ph: Math.random() * 6.3, c: i % 7}));
  function draw2d(f, dt) {
    const k0 = cv.width / W;
    cx.setTransform(1, 0, 0, 1, 0, 0); cx.clearRect(0, 0, cv.width, cv.height);
    if (S.I <= .002) return;
    if (!sprite) build2d();
    const k = W < 760 ? .5 : 1, len = Math.hypot(f.x1 - f.x0, f.y1 - f.y0) * ease(S.pour), ang = Math.atan2(f.x1 - f.x0, f.y1 - f.y0);
    if (len < 4) return;
    const amp = S.I * (1 + .3 * S.near + .4 * S.hov), flick = RM ? 1 : .94 + .05 * Math.sin(f.t * 2.3);
    cx.setTransform(k0, 0, 0, k0, 0, 0);
    let g;
    cx.globalAlpha = Math.min(1, amp * flick);
    // the column stops at the window's top edge: nothing but the rim enters the window
    cx.save(); cx.beginPath(); cx.moveTo(0, 0); cx.lineTo(W, 0); cx.lineTo(W, f.y1 + (W - f.x1) * f.slope); cx.lineTo(0, f.y1 - f.x1 * f.slope); cx.closePath(); cx.clip();
    cx.save(); cx.translate(f.x0, f.y0); cx.rotate(-ang);
    const wk = k * (1 + .16 * S.near);
    cx.drawImage(sprite, -SW / 2 * wk, 0, SW * wk, len);
    cx.globalCompositeOperation = 'destination-out';
    g = cx.createLinearGradient(0, 0, 0, 56); g.addColorStop(0, '#000'); g.addColorStop(.25, '#000'); g.addColorStop(1, 'rgba(0,0,0,0)');
    cx.globalAlpha = 1; cx.fillStyle = g; cx.fillRect(-SW, 0, SW * 2, 56);
    cx.globalCompositeOperation = 'source-over';
    for (const d of dust) {
      if (!RM) { d.f += d.v * dt / 1000; if (d.f > 1) { d.f = 0; d.u = Math.random() * 2 - 1; } }
      const py = d.f * len, half = k * (5 + 40 * d.f), px = d.u * half + Math.sin(f.t * 1.1 + d.ph) * 3 * k;
      const a = d.a * amp * Math.min(1, d.f * 8) * (1 - d.f * .5) * (.6 + .4 * Math.sin(f.t * 3.3 + d.ph));
      if (a <= .02) continue;
      cx.globalAlpha = Math.min(1, a); cx.fillStyle = `rgb(${PAL[d.c].join(',')})`; cx.fillRect(px, py, d.s, d.s);
    }
    cx.restore(); cx.restore();
    const land = f.land * amp;
    if (land > 0) {
      cx.save(); cx.beginPath(); cx.rect(f.sr.left, 0, f.sr.width, f.y1); cx.clip(); cx.translate(f.x1, f.y1); cx.scale(1, .3);
      g = cx.createRadialGradient(0, 0, 0, 0, 0, 230 * k); g.addColorStop(0, 'rgba(255,250,245,.3)'); g.addColorStop(.25, 'rgba(255,220,60,.12)'); g.addColorStop(.45, 'rgba(90,240,100,.08)'); g.addColorStop(.65, 'rgba(40,210,255,.07)'); g.addColorStop(.85, 'rgba(150,70,255,.05)'); g.addColorStop(1, 'rgba(150,70,255,0)');
      cx.globalAlpha = Math.min(1, land * flick); cx.fillStyle = g; cx.beginPath(); cx.arc(0, 0, 230 * k, 0, 6.2832); cx.fill();
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
    const x0 = p.left + p.width / 2, y0 = p.bottom - 7;
    const gap = sr.top - p.bottom, want = sr.bottom > H * .2 && p.bottom > 0 && p.width > 0 && gap > 10;
    const vis = want ? smooth(70, 110, gap) : 0;   // the column needs ~40px of lead under the header plus room to fan: no beam on a tight phone layout
    if (RM) S.I = vis; else S.I = clamp(S.I + clamp(vis - S.I, -dt / 260, dt / 420), 0, 1);
    if (want && !RM) S.pour = Math.min(1, S.pour + dt / 900);
    if (S.pour >= 1 && S.reveal < 1) { S.reveal = Math.min(1, S.reveal + dt / 1300); setVar('--reveal', ease(S.reveal).toFixed(3)); }
    const kf = ms => RM ? 1 : 1 - Math.exp(-dt / ms);
    // landing point: a little left of the pill, on the window's right part, leaning toward the cursor
    const base = W < 600 ? Math.min(x0, sr.right - 40) : clamp(x0 - 120, sr.left + sr.width * .42, sr.right - 110);
    const live = !RM && S.mx >= 0 && S.my < sr.bottom + 120;
    const target = live ? clamp(base + (S.mx - base) * .12, sr.left + sr.width * .5, sr.right - 90) : base;
    S.lean = S.lean == null || RM ? target : S.lean + (target - S.lean) * kf(280);
    const x1 = S.lean, y1 = edgeAt(x1);
    const nearT = live ? smooth(260, 40, segDist(S.mx, S.my, x0, y0, x1, y1)) : 0;
    S.near += (nearT - S.near) * kf(220);
    S.hov += (S.hovT - S.hov) * kf(160);
    // shot tilt and glare follow a mouse over the shot
    const over = !RM && S.mouse && S.mx >= sr.left && S.mx <= sr.right && S.my >= sr.top && S.my <= sr.bottom;
    const nx = over ? (S.mx - sr.left) / sr.width : .5, ny = over ? (S.my - sr.top) / sr.height : .5;
    // tilt only while the pointer moves; at rest the shot eases back to a flat, crisply rastered layer
    const moving = over && now - (S.moved || 0) < 420;
    S.ry += ((moving ? (nx - .5) * 6 : 0) - S.ry) * kf(moving ? 160 : 170);   // max 3deg
    S.rx += ((moving ? (.5 - ny) * 5 : 0) - S.rx) * kf(moving ? 160 : 170);   // max 2.5deg
    if (!moving && Math.abs(S.rx) + Math.abs(S.ry) < .35) S.rx = S.ry = 0;    // snap flat: no resampled raster at rest
    S.gl += ((over ? 1 : 0) - S.gl) * kf(200);
    if (over) { setVar('--gx', (nx * win.offsetWidth).toFixed(0) + 'px'); setVar('--gy', (ny * win.offsetHeight).toFixed(0) + 'px'); }
    // the 3D transform only while tilted: an untilted shot stays a plain, crisply rastered layer
    const tilted = Math.abs(S.rx) + Math.abs(S.ry) > 0;
    if (tilted !== S.tilted) { S.tilted = tilted; shot.classList.toggle('is-tilt', tilted); }
    setVar('--ry', S.ry.toFixed(2) + 'deg'); setVar('--rx', S.rx.toFixed(2) + 'deg'); setVar('--glare', S.gl.toFixed(3));
    const land = ease((S.pour - .7) / .3);
    const hit = S.burst > 0 && t > S.burst ? Math.exp(-(t - S.burst) * 3) : 0;
    setVar('--lit', (S.I * land * (1 + .25 * S.near + .3 * S.hov)).toFixed(2)); setVar('--bx', (x1 - sr.left).toFixed(0) + 'px'); setVar('--hit', hit.toFixed(2));
    S.geo = stats.geo = {x0, y0, x1, y1, len: Math.hypot(x1 - x0, y1 - y0)};
    const f = {t, x0, y0, x1, y1, sr, land, slope};
    if (gl) drawGL(f); else if (cx) draw2d(f, dt);
  }

  let raf = 0, last = 0, seen = true;
  function clearAll() { if (gl) { gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); } else if (cx) { cx.setTransform(1, 0, 0, 1, 0, 0); cx.clearRect(0, 0, cv.width, cv.height); } }
  function loop(now) {
    raf = 0;
    if (document.hidden || !seen) { clearAll(); last = 0; return; }
    if (last && now - last < 15) { raf = requestAnimationFrame(loop); return; }
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
    S.burst = t + S.geo.len / FLOW;
  }
  addEventListener('pointermove', e => { S.mx = e.clientX; S.my = e.clientY; S.mouse = e.pointerType === 'mouse'; S.moved = performance.now(); }, {passive: true});
  document.documentElement.addEventListener('pointerleave', () => { S.mx = S.my = -1; });
  sec.addEventListener('click', e => {
    if (e.target.closest('a,button,code,.omher__cmd')) return;
    const r = shot.getBoundingClientRect(), g = S.geo;
    const onShot = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
    if (onShot || (g && segDist(e.clientX, e.clientY, g.x0, g.y0, g.x1, g.y1) < 40)) pulse();
  });
  for (const [ev, v] of [['pointerenter', 1], ['pointerleave', 0], ['focus', 1], ['blur', 0]]) pill.addEventListener(ev, () => { S.hovT = v; });

  size();
  addEventListener('resize', () => { size(); kick(); });
  document.addEventListener('visibilitychange', kick);
  if (RM) addEventListener('scroll', kick, {passive: true});
  new IntersectionObserver(es => { seen = es[0].isIntersecting; kick(); }).observe(sec);
  kick();
})();
