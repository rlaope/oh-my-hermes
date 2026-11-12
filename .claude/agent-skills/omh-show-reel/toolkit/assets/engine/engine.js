/* MIT; Copyright (c) 2026 Minho Hwang (revfactory).
 * From revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6 assets/engine/engine.js.
 * Upstream engine, unmodified below this notice.
 * Full permission/warranty: toolkit/LICENSE.upstream. Not imported or executed by OMH core. */
/* showreel 엔진 — 화면 전체가 시간 t(초)의 순수 함수다.
 *
 * 렌더러(scripts/render.mjs)는 임의의 시각으로 바로 이동(seek)하고, 여러 워커가 구간을 나눠 그리며,
 * 모션 블러를 위해 프레임 사이의 소수 시각까지 찍는다. 그래서 다음은 쓰지 않는다:
 *   requestAnimationFrame 누적 상태, CSS transition/animation, Math.random(), Date.now(), 이전 프레임 값에 의존하는 계산.
 * 무작위가 필요하면 REEL.rand(i, salt), 흔들림·잡음은 REEL.noise(t, seed)를 쓴다.
 *
 * 규약
 *   REEL.config({ duration, fps, width, height, audio, push })   영상 길이·프레임률·해상도(9:16이면 1080×1920)·미리보기 오디오·장면 기본 푸시
 *   REEL.scene({ id, start, end, push, setup(el), render(lt, ctx) })   push: 장면 동안 천천히 확대할 비율(기본 config.push, 예 0.03)
 *       setup(el)        한 번 호출. el은 무대 크기의 <section>. DOM·SVG·canvas를 여기서 만든다.
 *       render(lt, ctx)  매 프레임 호출. lt = 장면 안 시간(초), ctx = { t, dur, p }.
 *       start/end는 숫자 또는 큐 이름 문자열(timeline.js의 TL.cues). 장면 구간은 겹쳐도 된다(전환).
 *       나중에 등록한 장면이 위에 그려진다. 구간 밖 장면은 display:none 이라 비용이 들지 않는다.
 *   REEL.overlay(fn, { layer: 'back' | 'cam' | 'top' })   모든 프레임에 호출되는 전역 레이어 fn(t). back 은 장면 뒤, cam 은 장면 위(카메라와 함께 움직임), top 은 맨 위
 *   REEL.preload(promise) / REEL.img(src)        준비 작업. 모두 끝나야 __ready = true
 *   REEL.cue(name, fallback)                     timeline.js 의 큐 시각(초). 없으면 fallback
 *   window.__seek(t), window.__ready, window.__meta   렌더러 진입점(직접 바꾸지 않는다)
 *
 * 미리보기: 브라우저로 index.html 을 연다(또는 node render.mjs --serve). 스페이스 재생, ←→ 1초, Shift+←→ 1프레임,
 *          숫자키 n×10%, ?t=12.5 로 시점 지정, M 으로 소리 켜기/끄기. 렌더 시에는 ?render=1 이 붙어 UI가 숨는다.
 */
(function () {
  'use strict';
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const lerp = (a, b, p) => a + (b - a) * p;
  const map = (x, a, b, c, d, e) => lerp(c, d, (e || (p => p))(clamp((x - a) / (b - a))));

  // 큐빅 베지어 이징 (CSS cubic-bezier 와 같은 정의)
  function bezier(x1, y1, x2, y2) {
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    const sx = t => ((ax * t + bx) * t + cx) * t;
    const sy = t => ((ay * t + by) * t + cy) * t;
    const dx = t => (3 * ax * t + 2 * bx) * t + cx;
    return p => {
      if (p <= 0) return 0;
      if (p >= 1) return 1;
      let t = p;
      for (let i = 0; i < 8; i++) {
        const e = sx(t) - p;
        if (Math.abs(e) < 1e-6) break;
        const d = dx(t);
        if (Math.abs(d) < 1e-6) break;
        t -= e / d;
      }
      return sy(clamp(t));
    };
  }

  const ease = {
    linear: p => p,
    inQuad: p => p * p,
    outQuad: p => 1 - (1 - p) * (1 - p),
    inOutQuad: p => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2),
    inCubic: p => p * p * p,
    outCubic: p => 1 - Math.pow(1 - p, 3),
    inOutCubic: p => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
    inQuart: p => p ** 4,
    outQuart: p => 1 - Math.pow(1 - p, 4),
    inOutQuart: p => (p < 0.5 ? 8 * p ** 4 : 1 - Math.pow(-2 * p + 2, 4) / 2),
    outQuint: p => 1 - Math.pow(1 - p, 5),
    inExpo: p => (p <= 0 ? 0 : Math.pow(2, 10 * p - 10)),
    outExpo: p => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p)),
    inOutExpo: p => (p <= 0 ? 0 : p >= 1 ? 1 : p < 0.5 ? Math.pow(2, 20 * p - 10) / 2 : (2 - Math.pow(2, -20 * p + 10)) / 2),
    outBack: (p, s = 1.70158) => 1 + (s + 1) * Math.pow(p - 1, 3) + s * Math.pow(p - 1, 2),
    inBack: (p, s = 1.70158) => (s + 1) * p * p * p - s * p * p,
    outElastic: p => (p <= 0 || p >= 1 ? clamp(p) : Math.pow(2, -10 * p) * Math.sin((p * 10 - 0.75) * ((2 * Math.PI) / 3)) + 1),
    inOutSine: p => -(Math.cos(Math.PI * p) - 1) / 2,
    // 모션 디자인에서 자주 쓰는 곡선(After Effects 감성)
    snap: bezier(0.16, 1, 0.3, 1),      // 강한 감속 등장 — 기본 등장 곡선
    swift: bezier(0.83, 0, 0.17, 1),    // 강한 in-out — 와이프·카메라 이동
    exit: bezier(0.7, 0, 0.84, 0),      // 가속 퇴장
    pop: bezier(0.34, 1.56, 0.64, 1),   // 살짝 넘쳤다 돌아옴 — 칩·아이콘
  };

  // start부터 dur 동안 0→1 (이징 적용)
  const prog = (t, start, dur, e = ease.snap) => e(clamp((t - start) / Math.max(1e-6, dur)));
  // 등장·퇴장 창: a에서 inDur 동안 0→1, b에서 outDur 동안 1→0
  const win = (t, a, b, inDur = 0.4, outDur = 0.3, ei = ease.snap, eo = ease.exit) =>
    Math.min(prog(t, a, inDur, ei), 1 - prog(t, b - outDur, outDur, eo));
  // 키프레임 보간: kf(t, [[0, 0], [0.5, 1, ease.outExpo], [2, 0]]) — 각 구간 이징은 도착 키프레임에 적는다
  function kf(t, frames) {
    if (t <= frames[0][0]) return frames[0][1];
    for (let i = 1; i < frames.length; i++) {
      const [t1, v1, e] = frames[i];
      const [t0, v0] = frames[i - 1];
      if (t <= t1) return lerp(v0, v1, (e || ease.inOutCubic)(clamp((t - t0) / Math.max(1e-6, t1 - t0))));
    }
    return frames[frames.length - 1][1];
  }
  // 감쇠 스프링(0→1). 정지 상태에서 t0에 출발. f=진동수(Hz), z=감쇠비
  function spring(t, t0 = 0, f = 2.2, z = 0.42) {
    const dt = t - t0;
    if (dt <= 0) return 0;
    const w = 2 * Math.PI * f, wd = w * Math.sqrt(1 - z * z);
    return 1 - Math.exp(-z * w * dt) * (Math.cos(wd * dt) + ((z * w) / wd) * Math.sin(wd * dt));
  }
  // 시드 고정 의사 난수 [0, 1)
  const rand = (i, salt = 0) => {
    const x = Math.sin(i * 12.9898 + salt * 78.233 + 0.1) * 43758.5453;
    return x - Math.floor(x);
  };
  // 부드러운 1차원 잡음 [-1, 1] — 손떨림·드리프트용
  const noise = (t, seed = 0) =>
    Math.sin(t * 1.31 + seed * 12.9) * 0.5 + Math.sin(t * 2.17 + seed * 7.3) * 0.3 + Math.sin(t * 3.73 + seed * 3.1) * 0.2;

  // 글자(또는 단어) 단위로 쪼개 span 배열을 돌려준다. 한글 음절·이모지는 한 글자.
  // mode: 'char' | 'word'. 마스크 리빌을 쓰려면 opts.mask = true (글자마다 overflow:hidden 래퍼)
  function split(el, mode = 'char', opts = {}) {
    const text = el.textContent;
    el.textContent = '';
    const units = [];
    const add = (str, isSpace) => {
      if (isSpace) { el.appendChild(document.createTextNode(str)); return; }
      let host = el;
      if (opts.mask) {
        host = document.createElement('span');
        host.className = 'mask';
        host.style.cssText = 'display:inline-block;overflow:hidden;vertical-align:top;padding:.12em .04em .18em;margin:-.12em -.04em -.18em';
        el.appendChild(host);
      }
      const s = document.createElement('span');
      s.className = mode === 'word' ? 'w' : 'ch';
      s.style.display = 'inline-block';
      s.style.whiteSpace = 'pre';
      s.textContent = str;
      host.appendChild(s);
      units.push(s);
    };
    if (mode === 'word') {
      for (const part of text.split(/(\s+)/)) if (part) add(part, /^\s+$/.test(part));
    } else {
      const seg = new Intl.Segmenter('ko', { granularity: 'grapheme' });
      for (const { segment } of seg.segment(text)) add(segment, segment === ' ');
    }
    return units;
  }
  // i번째 요소의 지연 진행률
  const stagger = (t, start, each, dur, i, e = ease.snap) => prog(t, start + i * each, dur, e);

  // 등장과 퇴장을 모두 움직임으로: a 에서 아래·흐림·확대 상태로 들어오고, b 에서 위로 밀리며 줄고 흐려지며 나간다.
  // 투명도만 바꾸는 페이드는 화면이 멈춘 것처럼 보인다. 반환값은 보이는 정도(0~1).
  //   o: { inDur 0.45, outDur 0.4, rise 60, lift 140, blur 12, from 1.06, to 0.9, x 0, dx 0 }
  function inout(el, t, a, b, o = {}) {
    const pi = prog(t, a, o.inDur ?? 0.45, ease.snap);
    const po = b == null ? 0 : prog(t, b - (o.outDur ?? 0.4), o.outDur ?? 0.4, ease.exit);
    const v = Math.min(pi, 1 - po);
    if (v <= 0.001) { if (el.style.opacity !== '0') el.style.opacity = '0'; return 0; }
    const y = (1 - pi) * (o.rise ?? 60) - po * (o.lift ?? 140);
    const x = (1 - pi) * (o.x ?? 0) + po * (o.dx ?? 0);
    const s = lerp(o.from ?? 1.06, 1, pi) * lerp(1, o.to ?? 0.9, po);
    const bl = (1 - pi) * (o.blur ?? 12) + po * (o.blur ?? 12) * 0.8;
    el.style.opacity = v.toFixed(3);
    el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) scale(${s.toFixed(4)})`;
    el.style.filter = bl > 0.3 ? `blur(${bl.toFixed(1)}px)` : 'none';
    return v;
  }

  // 나레이션 줄의 글자별 시작 시각(어절 시각을 글자 수로 나눔). split(el,'char') 결과와 함께 쓴다.
  //   charTimes('n03')            줄 전체 글자(공백 제외)
  //   charTimes('n03', '쇼릴')     줄 안의 부분 문자열만(화면 표기가 발음 표기와 같을 때)
  function charTimes(id, sub) {
    const v = (TL.vo || []).find(x => x.id === id);
    if (!v) { console.warn('[REEL] 줄 없음:', id); return []; }
    const out = [];
    for (const [w, s, e] of v.words || []) {
      const chs = [...w];
      chs.forEach((c, i) => out.push([c, s + (e - s) * (i / chs.length)]));
    }
    if (!sub) return out.map(x => x[1]);
    const joined = out.map(x => x[0]).join('');
    const k = joined.indexOf(sub.replace(/\s/g, ''));
    if (k < 0) { console.warn('[REEL] 부분 문자열 없음:', id, sub); return []; }
    return out.slice(k, k + sub.replace(/\s/g, '').length).map(x => x[1]);
  }
  // 글자 span 들을 말하는 시각에 맞춰 하나씩 올린다(아래에서 위로·흐림 → 선명). times 가 모자라면 마지막 값을 쓴다.
  function sayChars(spans, t, times, o = {}) {
    const dur = o.dur ?? 0.35, rise = o.rise ?? 18, bl = o.blur ?? 10, lead = o.lead ?? 0.03;
    spans.forEach((sp, i) => {
      const st = (times[Math.min(i, times.length - 1)] ?? 0) - lead;
      const p = prog(t, st, dur, ease.outCubic);
      sp.style.opacity = p.toFixed(3);
      sp.style.transform = `translateY(${((1 - p) * rise).toFixed(1)}px)`;
      sp.style.filter = p < 0.97 ? `blur(${((1 - p) * bl).toFixed(1)}px)` : 'none';
    });
  }
  // 숫자 카운터 문자열 (ko-KR 천 단위 구분)
  const count = (p, to, { decimals = 0, comma = true, from = 0 } = {}) => {
    const v = lerp(from, to, clamp(p));
    return comma
      ? v.toLocaleString('ko-KR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
      : v.toFixed(decimals);
  };
  // 스크램블 디코드: p=0이면 무작위 글리프, p=1이면 최종 문자열. 한글은 한글 음절로, 라틴은 라틴으로 섞는다.
  const GLY = 'ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#%&@/<>=+*';
  function scramble(final, p, t, seed = 1) {
    const a = [...final];
    const f = Math.floor(t * 30);
    return a.map((ch, i) => {
      if (ch === ' ' || p >= 1 || p >= (i / a.length) * 0.75 + 0.25) return ch;   // p=1 이면 반드시 원문
      const r = rand(i * 977 + f * 131, seed);
      if (/[가-힣]/.test(ch)) return String.fromCharCode(0xac00 + Math.floor(r * 11172));
      return GLY[Math.floor(r * GLY.length)];
    }).join('');
  }
  // 충격 흔들림: hits = [[t0, amp(px), decay(초)], ...] → {x, y, r}
  function shake(t, hits, freq = 75) {
    let x = 0, y = 0, r = 0;
    for (const [t0, amp = 12, d = 0.45] of hits) {
      const dt = t - t0;
      if (dt < 0 || dt > d * 2.5) continue;
      const k = amp * Math.exp(-(dt / d) * 5);
      x += k * Math.sin(dt * freq + t0 * 3);
      y += k * Math.cos(dt * (freq * 0.87) + t0 * 5);
      r += k * 0.03 * Math.sin(dt * freq * 0.7);
    }
    return { x, y, r };
  }
  // 펄스: 히트 시각마다 1에서 지수 감쇠 (빛·스케일 반응용)
  const pulse = (t, hits, decay = 0.25) => {
    let v = 0;
    for (const h of hits) { const dt = t - h; if (dt >= 0) v = Math.max(v, Math.exp(-dt / decay)); }
    return v;
  };

  const css = (el, o) => { for (const k in o) el.style[k] = o[k]; return el; };
  const h = (tag, cls, parent, html) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (html != null) el.innerHTML = html;
    if (parent) parent.appendChild(el);
    return el;
  };
  const svgNS = 'http://www.w3.org/2000/svg';
  const s = (tag, attrs, parent) => {
    const el = document.createElementNS(svgNS, tag);
    for (const k in attrs || {}) el.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(el);
    return el;
  };
  // 값이 바뀔 때만 쓰는 setter (DOM 쓰기 비용 절약)
  const set = (el, prop, v) => { if (el.style[prop] !== v) el.style[prop] = v; };

  const scenes = [];
  const overlays = [];
  const waits = [];
  const cfg = { duration: 60, fps: 30, width: 1920, height: 1080, audio: null, push: 0 };
  const TL = window.TL || { cues: {}, vo: [], scenes: [] };

  const cue = (name, fallback) => {
    const v = TL.cues && TL.cues[name];
    if (typeof v === 'number') return v;
    if (fallback === undefined) console.warn('[REEL] 큐 없음:', name);
    return fallback === undefined ? 0 : fallback;
  };
  const when = v => (typeof v === 'string' ? cue(v) : v);
  // 박 격자: bar(n) 은 n번째 마디 시작(1부터, 큐 'bar1' 과 같음), bar(n, 0.5) 는 그 마디의 절반 지점, beat(n) 은 n번째 박.
  // 음악 분석(timeline.py --music-analysis)이 없으면 120BPM 으로 가정한다
  const grid = (arr, n, per) => {
    if (!arr.length) return n * per;
    const i = Math.floor(n), f = n - i;
    if (i < arr.length - 1) return arr[i] + (arr[i + 1] - arr[i]) * f;
    const step = arr.length > 1 ? arr[arr.length - 1] - arr[arr.length - 2] : per;
    return arr[arr.length - 1] + (n - (arr.length - 1)) * step;
  };
  const bar = (n, frac = 0) => grid((TL.music && TL.music.downbeats) || [], n - 1 + frac, 2);
  const beat = n => grid((TL.music && TL.music.beats) || [], n - 1, 0.5);
  // 소리 크기 0~1: level(t) 는 그 시각의 나레이션, level(t, 'n03') 은 한 줄, level(t, 'music') 은 음악 에너지
  const level = (t, src) => {
    const read = e => {
      if (!e || !e.v) return 0;
      const x = (t - e.t0) / e.dt, i = Math.floor(x);
      if (i < 0 || i >= e.v.length - 1) return 0;
      return e.v[i] + (e.v[i + 1] - e.v[i]) * (x - i);
    };
    if (src === 'music') return read(TL.music && TL.music.energy);
    const lines = (TL.vo || []).filter(v => (src ? v.id === src : t >= v.start - 0.1 && t <= v.end + 0.1));
    return lines.reduce((m, v) => Math.max(m, read(v.env)), 0);
  };

  function img(src) {
    const im = new Image();
    im.decoding = 'sync';
    const p = new Promise((res) => {
      im.onload = () => im.decode().catch(() => null).then(() => res(im));
      im.onerror = () => { console.error('[REEL] 이미지 로드 실패:', src); res(im); };
    });
    im.src = src;
    waits.push(p);
    return im;
  }

  let stage, cam, back, top;
  function seek(t) {
    for (const sc of scenes) {
      const on = t >= sc._s && t < sc._e;
      if (on !== sc._on) { sc.el.style.display = on ? '' : 'none'; sc._on = on; }
      if (on && sc.render) {
        const dur = sc._e - sc._s;
        sc.render.call(sc, t - sc._s, { t, dur, p: (t - sc._s) / dur });
      }
      // 장면 전체를 천천히 민다(scale 속성은 장면 코드의 transform 과 겹치지 않는다). 장면별 push 가 config 값보다 우선
      const push = sc.push ?? cfg.push ?? 0;
      if (on && push) sc.el.style.scale = (1 + push * clamp((t - sc._s) / (sc._e - sc._s))).toFixed(5);
    }
    for (const o of overlays) o.fn(t);
    window.__t = t;
  }

  async function init() {
    stage = document.getElementById('stage');
    css(stage, { width: cfg.width + 'px', height: cfg.height + 'px' });
    const wrap = document.getElementById('wrap');
    if (wrap) css(wrap, { width: cfg.width + 'px', height: cfg.height + 'px' });
    cam = h('div', 'cam', stage);
    back = h('div', 'back', cam);   // 장면보다 뒤(카메라 안): 움직이는 배경 면·먼지·빛줄기
    back.style.cssText = 'position:absolute;inset:0;pointer-events:none';
    top = h('div', 'top', stage);
    // 폰트를 먼저 모두 받는다 — setup 안에서 글자 폭을 재거나 캔버스에 글자를 그려도 올바른 글꼴이 쓰이도록.
    // 선언된 모든 @font-face 를 실제로 내려받고, data-fonts 패밀리는 한글 샘플로 굵기별로 미리 그려 둔다.
    await document.fonts.ready;
    await Promise.all([...document.fonts].map(f => (f.status === 'loaded' ? null : f.load().catch(() => null))));
    const fams = (document.documentElement.dataset.fonts || '').split(',').map(x => x.trim()).filter(Boolean);
    const sample = '가나다라마바사 ABC 0123456789';
    await Promise.all(fams.flatMap(f => [400, 700, 900].map(w => document.fonts.load(`${w} 64px "${f}"`, sample).catch(() => null))));
    const pending = [];
    for (const sc of scenes) {
      sc._s = when(sc.start);
      sc._e = when(sc.end);
      sc.el = h('section', 'scene', cam);
      sc.el.id = sc.id;
      sc._on = false;
      // setup 중에는 보이게 둔다(글자 폭·위치 측정이 0으로 나오지 않도록). async setup 도 허용
      if (sc.setup) pending.push(sc.setup.call(sc, sc.el));
    }
    for (const o of overlays) if (o.setup) pending.push(o.setup(o.layer === 'cam' ? cam : o.layer === 'back' ? back : top));
    await Promise.all(pending);
    for (const sc of scenes) sc.el.style.display = 'none';
    await Promise.all(waits);
    await Promise.all([...document.images].map(im => (im.complete ? im.decode().catch(() => null) : new Promise(r => { im.onload = im.onerror = r; }))));
    window.__fonts = [...new Set([...document.fonts].filter(f => f.status === 'loaded').map(f => `${f.family.replace(/"/g, '')} ${f.weight}`))];
    window.__meta = { duration: cfg.duration, fps: cfg.fps, width: cfg.width, height: cfg.height, fonts: window.__fonts, scenes: scenes.map(s => [s.id, s._s, s._e]) };
    const params = new URLSearchParams(location.search);
    seek(Number(params.get('t') || 0));
    window.__ready = true;
    if (!params.has('render')) preview();
  }

  // 미리보기 플레이어(렌더 모드가 아닐 때만)
  function preview() {
    document.body.classList.add('preview');
    const wrap = document.getElementById('wrap');
    const fit = () => {
      const k = Math.min(innerWidth / cfg.width, (innerHeight - 48) / cfg.height);
      wrap.style.transform = `scale(${k})`;
    };
    fit();
    addEventListener('resize', fit);
    const ui = h('div', 'player', document.body);
    const bar = h('input', 'scrub', ui);
    const lab = h('span', 'tc', ui);
    Object.assign(bar, { type: 'range', min: 0, max: cfg.duration, step: 1 / cfg.fps, value: window.__t || 0 });
    let audio = null;
    if (cfg.audio) { audio = new Audio(cfg.audio); audio.preload = 'auto'; }
    let muted = !audio;
    let playing = false, t0 = 0, base = 0;
    const show = () => {
      const t = window.__t || 0;
      bar.value = t;
      const sc = scenes.filter(x => t >= x._s && t < x._e).map(x => x.id).join(' + ');
      lab.textContent = `${t.toFixed(2)}s / ${cfg.duration}s  f${Math.round(t * cfg.fps)}  ${sc}${audio ? (muted ? '  [M:소리 꺼짐]' : '  [M:소리 켜짐]') : ''}`;
    };
    const loop = now => {
      if (!playing) return;
      let t = base + (now - t0) / 1000;
      if (t >= cfg.duration) { t = 0; base = 0; t0 = now; if (audio) audio.currentTime = 0; }
      if (audio && !muted && Math.abs(audio.currentTime - t) > 0.12) audio.currentTime = t;
      seek(t);
      show();
      requestAnimationFrame(loop);
    };
    const play = on => {
      playing = on;
      if (on) { base = window.__t || 0; t0 = performance.now(); if (audio && !muted) { audio.currentTime = base; audio.play().catch(() => null); } requestAnimationFrame(loop); }
      else if (audio) audio.pause();
    };
    bar.oninput = () => { play(false); seek(Number(bar.value)); show(); };
    addEventListener('keydown', e => {
      const fr = 1 / cfg.fps;
      if (e.code === 'Space') { e.preventDefault(); play(!playing); }
      else if (e.code === 'ArrowRight') { play(false); seek(Math.min(cfg.duration, (window.__t || 0) + (e.shiftKey ? fr : 1))); }
      else if (e.code === 'ArrowLeft') { play(false); seek(Math.max(0, (window.__t || 0) - (e.shiftKey ? fr : 1))); }
      else if (/^Digit\d$/.test(e.code)) { play(false); seek((Number(e.code.slice(5)) / 10) * cfg.duration); }
      else if (e.code === 'KeyM' && audio) { muted = !muted; if (muted) audio.pause(); else if (playing) { audio.currentTime = window.__t; audio.play().catch(() => null); } }
      show();
    });
    show();
  }

  window.__ready = false;
  window.__seek = seek;
  window.REEL = {
    get duration() { return cfg.duration; },
    get fps() { return cfg.fps; },
    get W() { return cfg.width; },
    get H() { return cfg.height; },
    get stage() { return stage; },
    get cam() { return cam; },
    get top() { return top; },
    TL,
    config(o) { Object.assign(cfg, o); },
    scene(def) { scenes.push(def); return def; },
    overlay(fn, opts = {}) { overlays.push({ fn, layer: opts.layer || 'top', setup: opts.setup }); },
    preload(p) { waits.push(p); },
    img, cue, when, level, bar, beat,
    ease, bezier, prog, win, kf, spring, clamp, lerp, map, rand, noise, split, stagger, inout, charTimes, sayChars, count, scramble, shake, pulse,
    css, h, s, set,
  };
  addEventListener('load', init);
})();
