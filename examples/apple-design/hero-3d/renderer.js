/* OMH hero-3d renderer — a self-contained WebGL 1 signed-distance-field
 * ray-marcher. No dependencies, no network, file:// safe.
 *
 * It draws the SAME sculpture (two interlocked rounded-square links) twice:
 *   uVariant 0 — BEFORE: blue satin polymer, broad flat studio fill.
 *   uVariant 1 — AFTER:  machined satin aluminum + cool-blue optical glass,
 *                        sculpted key light, rim strip, floor reflection.
 * Rendering is static and deterministic: one draw per panel per size change
 * (initial + ResizeObserver), no animation loop, no stochastic accumulation.
 *
 * Readiness contract (deterministic, no polling needed by the harness):
 *   - html[data-omh-hero="ready"]  + window CustomEvent "omh-hero-ready"
 *     are set ONLY after shader compile + link + draw + gl.finish() succeed
 *     on BOTH panels.  The event re-fires after every resize re-render.
 *   - html[data-omh-hero="missing-webgl" | "error"] + "omh-hero-error"
 *     on failure; an explicit fallback message is shown, never a fake image.
 * Canvases use preserveDrawingBuffer:true so pixels survive for screenshots.
 */
(function () {
  'use strict';

  var VERT = [
    'attribute vec2 aPos;',
    'void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }'
  ].join('\n');

  var FRAG = [
    'precision highp float;',
    'uniform vec2  uRes;',
    'uniform float uVariant;   // 0.0 BEFORE, 1.0 AFTER',
    '#define AFTER (uVariant > 0.5)',
    '',
    '// ---- scene constants (see art-direction.md for the reasoning) ----',
    'const float GY   = -0.76;                      // studio floor height',
    'const float LIFT =  0.06;                      // sculpture lift above origin',
    'const vec3  LDIR = normalize(vec3(-0.5, 0.9, 0.45)); // key: above-left-front',
    'const float SEP  = 0.35;                       // half link-center separation',
    '',
    'mat3 gInv;                                     // world -> sculpture space',
    '',
    'float hash12(vec2 p){',
    '  vec3 p3 = fract(vec3(p.xyx) * 0.1031);',
    '  p3 += dot(p3, p3.yzx + 33.33);',
    '  return fract((p3.x + p3.y) * p3.z);',
    '}',
    'mat3 rotX(float a){ float c=cos(a),s=sin(a); return mat3(1.,0.,0., 0.,c,s, 0.,-s,c); }',
    'mat3 rotY(float a){ float c=cos(a),s=sin(a); return mat3(c,0.,-s, 0.,1.,0., s,0.,c); }',
    'mat3 rotZ(float a){ float c=cos(a),s=sin(a); return mat3(c,s,0., -s,c,0., 0.,0.,1.); }',
    '',
    '// 2D rounded box: half extents b + corner radius r',
    'float sdRBox2(vec2 p, vec2 b, float r){',
    '  vec2 q = abs(p) - b;',
    '  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;',
    '}',
    '// One link: rounded-square ring path (half extent 0.62, corner r 0.34) in the',
    '// local XY plane, extruded along Z with a beveled rectangular cross-section',
    '// (in-plane half width 0.17, half depth 0.14, edge bevel 0.055).',
    'float sdLink(vec3 p){',
    '  float path = sdRBox2(p.xy, vec2(0.28), 0.34);',
    '  return sdRBox2(vec2(path, p.z), vec2(0.115, 0.085), 0.055);',
    '}',
    '// Both links; .x distance, .y material id (1 ring-XY, 2 ring-XZ)',
    'vec2 map(vec3 p){',
    '  vec3 q = gInv * (p - vec3(0.0, LIFT, 0.0));',
    '  float d1 = sdLink(q + vec3(SEP, 0.0, 0.0));            // XY-plane link',
    '  float d2 = sdLink((q - vec3(SEP, 0.0, 0.0)).xzy);      // XZ-plane link',
    '  return (d1 < d2) ? vec2(d1, 1.0) : vec2(d2, 2.0);',
    '}',
    '',
    'vec2 trace(vec3 ro, vec3 rd, float tmax){',
    '  float t = 0.02;',
    '  for(int i = 0; i < 140; i++){',
    '    vec2 h = map(ro + rd * t);',
    '    if(h.x < 0.0008 + 0.0006 * t) return vec2(t, h.y);',
    '    t += h.x * 0.9;',
    '    if(t > tmax) break;',
    '  }',
    '  return vec2(tmax + 1.0, -1.0);',
    '}',
    'vec3 calcN(vec3 p){',
    '  vec2 e = vec2(0.0012, -0.0012);',
    '  return normalize(e.xyy * map(p + e.xyy).x + e.yyx * map(p + e.yyx).x +',
    '                   e.yxy * map(p + e.yxy).x + e.xxx * map(p + e.xxx).x);',
    '}',
    '// Per-link soft shadow so AFTER glass can pass part of the key light.',
    'vec2 shadow2(vec3 ro, vec3 rd, float k){',
    '  float r1 = 1.0, r2 = 1.0, t = 0.02;',
    '  for(int i = 0; i < 44; i++){',
    '    vec3 q = gInv * (ro + rd * t - vec3(0.0, LIFT, 0.0));',
    '    float d1 = sdLink(q + vec3(SEP, 0.0, 0.0));',
    '    float d2 = sdLink((q - vec3(SEP, 0.0, 0.0)).xzy);',
    '    r1 = min(r1, k * d1 / t);',
    '    r2 = min(r2, k * d2 / t);',
    '    t += clamp(min(d1, d2), 0.015, 0.22);',
    '    if((r1 < 0.004 && r2 < 0.004) || t > 5.0) break;',
    '  }',
    '  return clamp(vec2(r1, r2), 0.0, 1.0);',
    '}',
    'float shComb(vec2 s){',
    '  return AFTER ? s.x * mix(1.0, s.y, 0.55)   // glass passes ~45% of light',
    '               : s.x * s.y;',
    '}',
    'float calcAO(vec3 p, vec3 n){',
    '  float occ = 0.0, sca = 1.0;',
    '  for(int i = 0; i < 5; i++){',
    '    float h = 0.02 + 0.11 * float(i);',
    '    occ += (h - map(p + n * h).x) * sca;',
    '    sca *= 0.72;',
    '  }',
    '  return clamp(1.0 - 1.6 * occ, 0.0, 1.0);',
    '}',
    '',
    '// Continuous silver-white studio backdrop (linear-light values).',
    'vec3 backdrop(vec3 rd){',
    '  float h = clamp(rd.y * 0.5 + 0.5, 0.0, 1.0);',
    '  vec3 lo = mix(vec3(0.815, 0.824, 0.838), vec3(0.780, 0.792, 0.812), uVariant);',
    '  vec3 hi = vec3(0.955, 0.960, 0.972);',
    '  vec3 c  = mix(lo, hi, pow(h, 1.25));',
    '  c += vec3(0.05, 0.05, 0.048) * exp(-abs(rd.y - 0.18) * 5.0) * mix(0.55, 1.0, uVariant);',
    '  return c;',
    '}',
    '// Rectangular softbox seen along rd (gnomonic window) — studio reflections.',
    'float sbox(vec3 rd, vec3 n, vec2 hs, float soft){',
    '  float dp = dot(rd, n);',
    '  if(dp < 0.03) return 0.0;',
    '  vec3 q  = rd / dp - n;',
    '  vec3 xa = normalize(cross(vec3(0.0, 1.0, 0.0), n));',
    '  vec3 ya = cross(n, xa);',
    '  float wx = smoothstep(hs.x + soft, hs.x - soft, abs(dot(q, xa)));',
    '  float wy = smoothstep(hs.y + soft, hs.y - soft, abs(dot(q, ya)));',
    '  return wx * wy * dp;',
    '}',
    'vec3 envLight(vec3 rd, float rough){',
    '  vec3 c = backdrop(rd) * mix(1.0, 0.82, uVariant);',
    '  float s = mix(0.06, 0.85, rough);',
    '  if(AFTER){',
    '    c += vec3(1.05, 1.03, 0.99) * 3.4 * sbox(rd, normalize(vec3(-0.52, 0.78, 0.34)), vec2(0.70, 0.42), s + 0.10);',
    '    c += vec3(0.82, 0.88, 1.00) * 1.5 * sbox(rd, normalize(vec3(0.86, 0.18, -0.12)), vec2(0.10, 0.85), s + 0.06);',
    '    c += vec3(0.96, 0.97, 1.00) * 0.85 * sbox(rd, normalize(vec3(0.10, 0.25, 0.96)), vec2(0.90, 0.55), s + 0.30);',
    '    c -= vec3(0.10) * sbox(rd, normalize(vec3(0.0, -0.9, 0.3)), vec2(1.2, 1.2), s + 0.50);',
    '  } else {',
    '    c += vec3(1.0) * 0.90 * sbox(rd, normalize(vec3(-0.2, 0.9, 0.35)), vec2(1.1, 0.9), s + 0.45);',
    '    c += vec3(1.0) * 0.35 * sbox(rd, normalize(vec3(0.3, 0.2, 0.9)),  vec2(1.0, 0.8), s + 0.50);',
    '  }',
    '  return c;',
    '}',
    'float fres(float c){ return pow(clamp(1.0 - c, 0.0, 1.0), 5.0); }',
    '',
    '// Cheap shade for secondary rays (seen through glass / floor reflection).',
    'vec3 shadeCheap(vec3 p, vec3 n, float m, vec3 rd){',
    '  float dif = clamp(dot(n, LDIR), 0.0, 1.0);',
    '  if(AFTER && m < 1.5)',
    '    return vec3(0.91, 0.92, 0.94) * envLight(reflect(rd, n), 0.30) * 0.85;',
    '  if(AFTER)',
    '    return mix(backdrop(reflect(rd, n)), vec3(0.72, 0.82, 0.95), 0.30) * (0.72 + 0.28 * dif);',
    '  return vec3(0.155, 0.305, 0.615) * (0.45 + 0.75 * dif);',
    '}',
    '',
    'vec3 shadeGround(vec3 p, vec3 rd, float t){',
    '  vec3 n = vec3(0.0, 1.0, 0.0);',
    '  vec2 s2 = shadow2(p + n * 0.01, LDIR, AFTER ? 7.0 : 3.5);',
    '  float sh = shComb(s2);',
    '  float od = map(p + n * 0.05).x;                       // contact occlusion',
    '  float occ = 0.55 + 0.45 * smoothstep(0.0, 1.0, clamp(od / 0.45, 0.0, 1.0));',
    '  vec3 base = mix(vec3(0.835, 0.842, 0.855), vec3(0.800, 0.810, 0.830), uVariant);',
    '  float amb = mix(0.92, 0.78, uVariant);',
    '  float key = mix(0.28, 0.55, uVariant);',
    '  vec3 c = base * (amb * occ + key * sh * clamp(dot(n, LDIR), 0.0, 1.0));',
    '  if(AFTER){',
    '    c *= mix(vec3(1.0), vec3(0.88, 0.93, 1.02), (1.0 - s2.y) * 0.5); // cool glass shadow',
    '    vec3 rr = reflect(rd, n);                            // subtle floor reflection',
    '    vec2 hr = trace(p + n * 0.01, rr, 7.0);',
    '    if(hr.y > 0.0){',
    '      vec3 hp = p + rr * hr.x;',
    '      vec3 rc = shadeCheap(hp, calcN(hp), hr.y, rr);',
    '      c = mix(c, rc, exp(-hr.x * 0.55) * 0.30);',
    '    }',
    '  }',
    '  float fog = 1.0 - exp(-0.028 * t * t);                 // dissolve into backdrop',
    '  return mix(c, backdrop(vec3(rd.x, 0.03, rd.z)), clamp(fog, 0.0, 1.0));',
    '}',
    '',
    '// BEFORE — competent baseline: blue satin polymer, broad even light.',
    'vec3 shadePolymer(vec3 p, vec3 n, vec3 rd){',
    '  float occ = calcAO(p, n);',
    '  float sh  = shComb(shadow2(p + n * 0.012, LDIR, 4.0));',
    '  vec3 alb  = vec3(0.155, 0.305, 0.615);',
    '  float dif = clamp(dot(n, LDIR) * 0.7 + 0.3, 0.0, 1.0);         // wrap diffuse',
    '  vec3 hemi = mix(vec3(0.52), vec3(0.95), clamp(n.y * 0.5 + 0.5, 0.0, 1.0));',
    '  vec3 c = alb * (hemi * 0.85 * occ + vec3(1.0, 0.99, 0.97) * dif * 0.9 * mix(0.55, 1.0, sh));',
    '  vec3 hv = normalize(LDIR - rd);',
    '  c += vec3(1.0) * pow(clamp(dot(n, hv), 0.0, 1.0), 44.0) * 0.5 * sh;  // satin lobe',
    '  c += envLight(reflect(rd, n), 0.55) * 0.06 * occ;',
    '  c += vec3(0.05, 0.07, 0.11) * fres(clamp(dot(n, -rd), 0.0, 1.0)) * occ;',
    '  return c;',
    '}',
    '// AFTER link 1 — precision satin aluminum.',
    'vec3 shadeMetal(vec3 p, vec3 n, vec3 rd){',
    '  float occ = calcAO(p, n);',
    '  float sh  = shComb(shadow2(p + n * 0.012, LDIR, 9.0));',
    '  vec3 env  = envLight(reflect(rd, n), 0.19);',
    '  float ndv = clamp(dot(n, -rd), 0.0, 1.0);',
    '  float F   = 0.55 + 0.45 * fres(ndv);',
    '  vec3 tint = vec3(0.945, 0.950, 0.960);',
    '  vec3 c = tint * env * F * mix(0.55, 1.0, occ);',
    '  vec3 hv = normalize(LDIR - rd);',
    '  c += vec3(1.05, 1.03, 0.99) * pow(clamp(dot(n, hv), 0.0, 1.0), 120.0) * 1.4 * sh;',
    '  c += tint * 0.10 * clamp(-n.y, 0.0, 1.0) * occ;       // floor bounce',
    '  c += tint * 0.10 * occ;',
    '  return c;',
    '}',
    '// AFTER link 2 — cool-blue optical glass (single-scatter approximation:',
    '// entry refraction, thickness march, exit refraction, absorption tint).',
    'vec3 shadeGlass(vec3 p, vec3 n, vec3 rd){',
    '  float ndv = clamp(dot(n, -rd), 0.0, 1.0);',
    '  float F = 0.04 + 0.96 * fres(ndv);',
    '  vec3 refl = envLight(reflect(rd, n), 0.05);',
    '  vec3 rr = refract(rd, n, 1.0 / 1.45);',
    '  if(dot(rr, rr) < 0.5) rr = reflect(rd, n);',
    '  vec3 q = p + rr * 0.012;',
    '  float th = 0.0;',
    '  for(int i = 0; i < 32; i++){                          // march to exit face',
    '    float d = map(q).x;',
    '    if(d > 0.001) break;',
    '    float st = max(0.015, -d);',
    '    q += rr * st; th += st;',
    '  }',
    '  vec3 rt = refract(rr, -calcN(q), 1.45);',
    '  if(dot(rt, rt) < 0.5) rt = rr;                        // TIR fallback',
    '  vec3 bg;',
    '  vec2 hb = trace(q + rt * 0.03, rt, 8.0);              // metal seen through glass',
    '  if(hb.y > 0.0){',
    '    vec3 hp = q + rt * hb.x;',
    '    bg = shadeCheap(hp, calcN(hp), hb.y, rt);',
    '  } else if(rt.y < -0.02){',
    '    float tg = (GY - q.y) / rt.y;',
    '    vec3 gp = q + rt * tg;',
    '    bg = vec3(0.80, 0.81, 0.83) * (0.75 + 0.25 * shComb(shadow2(gp + vec3(0.0, 0.01, 0.0), LDIR, 6.0)));',
    '  } else bg = backdrop(rt);',
    '  vec3 T = exp(-vec3(0.55, 0.22, 0.06) * th * 2.0);     // cool-blue absorption',
    '  vec3 c = refl * F + bg * (1.0 - F) * T;',
    '  vec3 hv = normalize(LDIR - rd);',
    '  c += vec3(1.0) * pow(clamp(dot(n, hv), 0.0, 1.0), 420.0) * 2.0;',
    '  c += vec3(0.10, 0.16, 0.26) * fres(ndv) * 0.35;       // thickness edge cue',
    '  return c;',
    '}',
    '',
    'vec3 render(vec3 ro, vec3 rd){',
    '  vec2 h = trace(ro, rd, 14.0);',
    '  float tg = (rd.y < -0.0001) ? (GY - ro.y) / rd.y : 1e5;',
    '  if(h.y > 0.0 && h.x < tg){',
    '    vec3 p = ro + rd * h.x;',
    '    vec3 n = calcN(p);',
    '    if(!AFTER)          return shadePolymer(p, n, rd);',
    '    else if(h.y < 1.5)  return shadeMetal(p, n, rd);',
    '    else                return shadeGlass(p, n, rd);',
    '  }',
    '  if(tg < 1e4) return shadeGround(ro + rd * tg, rd, tg);',
    '  return backdrop(rd);',
    '}',
    '',
    'void main(){',
    '  // three-quarter pose: R = Ry(0.58) * Rx(0.24) * Rz(-0.08); gInv = R^T',
    '  gInv = rotZ(0.08) * rotX(-0.24) * rotY(-0.58);',
    '  vec2 uv = (2.0 * gl_FragCoord.xy - uRes) / uRes.y;',
    '  vec3 ro = vec3(0.0, 0.42, 4.35);',
    '  vec3 ta = vec3(0.0, -0.14, 0.0);',
    '  vec3 cw = normalize(ta - ro);',
    '  vec3 cu = normalize(cross(cw, vec3(0.0, 1.0, 0.0)));',
    '  vec3 cv = cross(cu, cw);',
    '  vec3 rd = normalize(uv.x * cu + uv.y * cv + 2.65 * cw);',
    '  vec3 c = render(ro, rd);',
    '  c = clamp(c, 0.0, 4.0);',
    '  vec3 k = vec3(0.85);                                   // soft highlight knee',
    '  c = mix(c, k + (1.0 - k) * (1.0 - exp(-(c - k) / (1.0 - k))), step(k, c));',
    '  c = pow(c, vec3(1.0 / 2.2));',
    '  c += (hash12(gl_FragCoord.xy) - 0.5) / 255.0;          // de-banding dither',
    '  gl_FragColor = vec4(c, 1.0);',
    '}'
  ].join('\n');

  var S = { state: 'pending', renders: 0, error: null };
  window.__OMH_HERO = S;

  function setState(state, evt, detail) {
    S.state = state;
    document.documentElement.setAttribute('data-omh-hero', state);
    try {
      window.dispatchEvent(new CustomEvent(evt, { detail: detail || null }));
    } catch (e) { /* CustomEvent unavailable: attribute state still set */ }
  }

  function fail(kind, message) {
    S.error = message;
    var notes = document.querySelectorAll('.nogl');
    for (var i = 0; i < notes.length; i++) {
      notes[i].hidden = false;
      var d = notes[i].querySelector('.nogl-detail');
      if (d) d.textContent = message;
    }
    setState(kind, 'omh-hero-error', { message: message });
  }

  function compile(gl, type, src) {
    var sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      throw new Error('shader compile failed: ' + gl.getShaderInfoLog(sh));
    }
    return sh;
  }

  function createPanel(canvas, variant) {
    var gl = canvas.getContext('webgl', {
      antialias: true,
      preserveDrawingBuffer: true,
      alpha: false,
      powerPreference: 'high-performance'
    });
    if (!gl) return null;
    var prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      throw new Error('program link failed: ' + gl.getProgramInfoLog(prog));
    }
    gl.useProgram(prog);
    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(prog, 'aPos');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    var uRes = gl.getUniformLocation(prog, 'uRes');
    var uVar = gl.getUniformLocation(prog, 'uVariant');
    return {
      canvas: canvas, w: 0, h: 0,
      draw: function (w, h) {
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);
        gl.uniform2f(uRes, w, h);
        gl.uniform1f(uVar, variant);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
        gl.finish();                       // block until pixels are real
        var err = gl.getError();
        if (err !== gl.NO_ERROR) throw new Error('GL error after draw: 0x' + err.toString(16));
      }
    };
  }

  function backingSize(el) {
    var w = el.clientWidth, h = el.clientHeight;
    var dpr = 2; // static 2x supersampling also smooths edges on 1x displays
    // deterministic pixel budget so a single static frame stays fast anywhere
    var cap = Math.sqrt(3200000 / Math.max(1, w * h));
    dpr = Math.min(dpr, cap);
    return [Math.max(2, Math.round(w * dpr)), Math.max(2, Math.round(h * dpr))];
  }

  var panels = [];

  function renderAll() {
    var drew = false;
    for (var i = 0; i < panels.length; i++) {
      var p = panels[i];
      var s = backingSize(p.canvas);
      if (s[0] === p.w && s[1] === p.h) continue;
      p.w = s[0]; p.h = s[1];
      p.draw(s[0], s[1]);
      drew = true;
    }
    if (drew) {
      S.renders++;
      setState('ready', 'omh-hero-ready', { renders: S.renders });
    }
  }

  function boot() {
    var before = document.getElementById('gl-before');
    var after = document.getElementById('gl-after');
    try {
      var p0 = createPanel(before, 0.0);
      var p1 = createPanel(after, 1.0);
      if (!p0 || !p1) {
        fail('missing-webgl', 'WebGL context could not be created in this browser.');
        return;
      }
      panels.push(p0, p1);
      renderAll();                         // first draw happens before 'ready'
      if (typeof ResizeObserver === 'function') {
        var ro = new ResizeObserver(function () { renderAll(); });
        ro.observe(document.querySelector('.panels'));
      } else {
        window.addEventListener('resize', renderAll);
      }
    } catch (e) {
      fail('error', String(e && e.message || e));
    }
  }

  boot();
})();
