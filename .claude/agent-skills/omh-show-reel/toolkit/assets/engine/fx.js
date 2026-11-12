/* MIT; Copyright (c) 2026 Minho Hwang (revfactory).
 * From revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6 assets/engine/fx.js.
 * Upstream FX layers, unmodified below this notice.
 * Full permission/warranty: toolkit/LICENSE.upstream. Not imported or executed by OMH core. */
/* showreel FX — 전역 레이어 모음(모두 선택 사항). engine.js 다음에 불러온다.
 * 콘셉트에 필요한 것만 호출한다. 레터박스·그레인·비네트·HUD를 습관처럼 모두 붙이지 않는다(references/design.md "뻔한 화면").
 * 모두 시간 t의 순수 함수로 그려지므로 렌더 워커·모션 블러와 함께 써도 된다.
 *
 *   FX.camera({ shakes: [[t, amp, decay]], drift: 0.6, zoom: [[t, scale, ease], ...], whips: [[t, dir]], beat: { hits, amount } })
 *                                               장면 전체(#cam)를 흔들고·떠다니게·휩 팬으로 넘기고·박마다 살짝 밀어 넣는다
 *   FX.impact([[t, { x, y, color, size }]])     큰 타격: 빛점 + 충격파 두 겹 + 사방 빛줄기 + 가로 플레어(2.4초)
 *   FX.wipe([[t, { type: 'slats'|'bars', colors }]])   화면을 덮었다 걷는 전환. t 에서 완전히 덮인다
 *   FX.floor({ from, to })                       흘러오는 원근 격자 바닥(장면 뒤) — 검은 배경이 멈춰 보이지 않게
 *   FX.dust({ n, color, from, to })              떠다니는 빛 먼지(부차 움직임, 장면 뒤)
 *   FX.rays({ x, y, from, to })                  천천히 도는 빛줄기(장면 뒤)
 *   FX.flash([[t, dur, opacity, color]])        히트 순간의 섬광(screen). opacity는 0.15 이하(어두운 배경), dur는 0.12~0.25초
 *   FX.letterbox(t => 0..1, { ratio: 2.39 })    시네마 레터박스. 함수가 1이면 완전히 닫힘
 *   FX.vignette({ strength: 0.6 })
 *   FX.grain({ opacity: 0.09, fps: 24 })        시드 고정 필름 그레인
 *   FX.leak([[t, dur, color, x]])               라이트 리크(빛 번짐)
 *   FX.hud({ left, right: t => '', chapters: [[t, '01 / TITLE']], timecode, progress, corners, from, to, color, marginTop, marginBottom })
 *   FX.subtitles({ lines: REEL.TL.vo, size, bottom, font })   번인 자막(TL.vo 의 sub). "nosub": true 줄은 번인에서 빠진다(SRT 에는 남음)
 *   세로(9:16) 영상이면 HUD·자막이 앱 UI 영역(위 250px·아래 420px)을 자동으로 피한다
 *
 * floor·dust·rays 는 장면 뒤(back)에 깔린다. 장면이 불투명한 배경을 깔면 가려지므로 그 장면 안에서는 배경을 투명하게 두거나 직접 움직인다.
 * 나머지는 호출 순서가 곧 위아래다. 보통 camera → impact → wipe → flash → leak → letterbox → vignette → grain → hud → subtitles 순.
 */
(function () {
  'use strict';
  const R = window.REEL;
  const { clamp, ease, prog, rand, css, h, kf } = R;
  const full = 'position:absolute;inset:0;pointer-events:none;';

  function camera(opts = {}) {
    const shakes = (opts.shakes || []).map(([t0, ...r]) => [R.when(t0), ...r]);
    const drift = opts.drift ?? 0.6;
    const zoom = opts.zoom || null;
    // whips: [[t, 방향(1 이면 화면이 왼쪽으로 빠짐), 길이 0.32]] — 앞 장면 끝과 다음 장면 시작을 t 에 맞춘다
    const whips = (opts.whips || []).map(([t0, dir = 1, d = 0.32]) => [R.when(t0), dir, d]);
    // beat: { hits: [초…], amount: 0.012, decay: 0.18 } — 박·히트마다 화면이 살짝 밀려 들어왔다 돌아온다
    const beat = opts.beat || null;
    R.overlay(t => {
      const s = R.shake(t, shakes);
      const dx = R.noise(t * 0.35, 1) * 6 * drift, dy = R.noise(t * 0.35, 2) * 4 * drift;
      let z = zoom ? kf(t, zoom) : 1;
      if (beat) z *= 1 + (beat.amount ?? 0.012) * R.pulse(t, beat.hits || [], beat.decay ?? 0.18);
      let wx = 0, wb = 0;
      for (const [t0, dir, d] of whips) {
        const lt = t - t0;
        if (lt < -d || lt > d) continue;
        const k = lt < 0 ? ease.inCubic(1 + lt / d) : 1 - ease.outCubic(lt / d);   // 0 → 1(t0) → 0
        wx = (lt < 0 ? -dir : dir) * k * R.W * 0.22;
        wb = k * 26;
      }
      R.cam.style.transform = `translate(${(s.x + dx + wx).toFixed(2)}px, ${(s.y + dy).toFixed(2)}px) rotate(${s.r.toFixed(3)}deg) scale(${z.toFixed(4)})`;
      const f = wb > 0.4 ? `blur(${wb.toFixed(1)}px)` : 'none';
      if (R.cam.style.filter !== f) R.cam.style.filter = f;
    }, { layer: 'top', setup: () => css(R.cam, { position: 'absolute', inset: 0, transformOrigin: '50% 50%' }) });
  }

  const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${clamp(a).toFixed(3)})`; };
  const canvasLayer = (p, cls) => { const cv = h('canvas', cls, p); cv.width = R.W; cv.height = R.H; cv.style.cssText = full + 'width:100%;height:100%'; return cv.getContext('2d'); };

  // 큰 타격 한 번에 들어가는 것을 한꺼번에 그린다: 가운데 빛점, 충격파 두 겹, 사방으로 튀는 빛줄기, 가로 플레어(2.4초).
  //   FX.impact([[t, { x, y, color, size, streaks, rings, flare }]])  — x·y 는 픽셀(기본 화면 가운데), size 는 배율
  // 흔들림은 FX.camera 의 shakes 에, 글자 슬램은 장면 코드에 같은 t 로 넣는다. 몇 번 쓸지는 콘셉트가 정한다.
  function impact(list) {
    let ctx, dirty = false;
    const items = list.map(([t0, o = {}]) => ({ t0: R.when(t0), x: o.x ?? R.W / 2, y: o.y ?? R.H / 2, col: o.color || '#F3C27A',
      k: o.size ?? 1, n: o.streaks ?? 120, rings: o.rings ?? 2, flare: o.flare !== false }));
    R.overlay(t => {
      const live = items.filter(it => t >= it.t0 && t < it.t0 + 2.4);
      if (!live.length) { if (dirty) { ctx.clearRect(0, 0, R.W, R.H); dirty = false; } return; }
      ctx.clearRect(0, 0, R.W, R.H); dirty = true;
      ctx.save(); ctx.globalCompositeOperation = 'lighter';
      for (const it of live) {
        const lt = t - it.t0, { x, y, col, k } = it;
        const core = 1 - clamp(lt / 0.4);
        if (core > 0) {
          const r = (90 + 160 * (1 - core)) * k, g = ctx.createRadialGradient(x, y, 0, x, y, r);
          g.addColorStop(0, rgba('#FFFFFF', 0.9 * core)); g.addColorStop(0.35, rgba(col, 0.55 * core)); g.addColorStop(1, rgba(col, 0));
          ctx.fillStyle = g; ctx.fillRect(x - r, y - r, r * 2, r * 2);
        }
        for (let j = 0; j < it.rings; j++) {
          const p = clamp((lt - j * 0.12) / (1.4 + j * 0.4));
          if (p <= 0 || p >= 1) continue;
          const r = ease.outCubic(p) * (j ? 1200 : 1500) * k;
          ctx.strokeStyle = j ? rgba('#FFFFFF', (1 - p) * 0.4) : rgba(col, (1 - p) * 0.8);
          ctx.lineWidth = (j ? 1 : 2) + (1 - p) * (j ? 3 : 10);
          ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke();
        }
        const pp = 1 - Math.pow(2, -10 * clamp(lt / 2.2)), fa = (1 - clamp((lt - 0.2) / 2.2)) * 0.8;
        if (fa > 0) {
          ctx.lineWidth = 1.3;
          for (let i = 0; i < it.n; i++) {
            const ang = rand(i, 11) * Math.PI * 2, r = (300 + rand(i, 12) * 1300) * k * pp, tl = 18 + 40 * (1 - pp);
            const cx = Math.cos(ang), cy = Math.sin(ang) * 0.6;
            ctx.strokeStyle = i % 3 ? rgba(col, fa) : rgba('#FFFFFF', fa);
            ctx.beginPath(); ctx.moveTo(x + cx * r, y + cy * r); ctx.lineTo(x + cx * (r - tl), y + cy * (r - tl)); ctx.stroke();
          }
        }
        const fl = it.flare ? 1 - clamp(lt / 1.4) : 0;
        if (fl > 0) {
          const L = 1000 * k, g = ctx.createLinearGradient(x - L, 0, x + L, 0);
          g.addColorStop(0, rgba(col, 0)); g.addColorStop(0.5, rgba('#FFE9C8', 0.55 * fl)); g.addColorStop(1, rgba(col, 0));
          ctx.fillStyle = g; ctx.fillRect(x - L, y - 3, L * 2, 6);
          ctx.globalAlpha = 0.5 * fl; ctx.fillRect(x - L * 0.6, y - 14, L * 1.2, 28); ctx.globalAlpha = 1;
        }
      }
      ctx.restore();
    }, { setup: p => { ctx = canvasLayer(p, 'fx-impact'); } });
  }

  // 원근 격자 바닥이 앞으로 흘러온다(무대 느낌 + 끊이지 않는 배경 움직임). 기본은 장면 뒤(back).
  //   FX.floor({ from, to, color: '#F3EFE6', glow: '#F3C27A', horizon: 0.62, speed: 0.35, opacity: 0.08 })
  function floor(o = {}) {
    let ctx;
    const col = o.color || '#F3EFE6', glow = o.glow || '#F3C27A';
    R.overlay(t => {
      ctx.clearRect(0, 0, R.W, R.H);
      const a0 = Math.min(prog(t, R.when(o.from ?? 0), 0.8, ease.linear), 1 - prog(t, R.when(o.to ?? R.duration) - 0.6, 0.6, ease.linear));
      if (a0 <= 0) return;
      const k = R.W / 1920, hy = R.H * (o.horizon ?? 0.62), vx = R.W / 2, op = (o.opacity ?? 0.08) * a0;
      const g = ctx.createRadialGradient(vx, -100, 50, vx, -100, 1100 * k);
      g.addColorStop(0, rgba(glow, 0.16 * a0)); g.addColorStop(1, rgba(glow, 0));
      ctx.fillStyle = g; ctx.fillRect(0, 0, R.W, R.H);
      ctx.strokeStyle = col; ctx.lineWidth = 1;
      ctx.globalAlpha = op;
      for (let i = -24; i <= 24; i++) { ctx.beginPath(); ctx.moveTo(vx + i * 14 * k, hy); ctx.lineTo(vx + i * 260 * k, R.H + 40); ctx.stroke(); }
      const off = (t * (o.speed ?? 0.35)) % 1;
      for (let j = 0; j < 14; j++) {
        const z = (j + off) / 14, y = hy + (R.H - hy) * z * z;
        ctx.globalAlpha = op * z; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(R.W, y); ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }, { layer: o.layer || 'back', setup: p => { ctx = canvasLayer(p, 'fx-floor'); } });
  }

  // 화면을 떠다니는 빛 먼지(정지 화면 방지용 부차 움직임). 기본은 장면 뒤(back), layer:'top' 이면 글자 위.
  //   FX.dust({ n: 80, color, size: 1.6, speed: 10, opacity: 0.5, from, to, box: [x, y, w, h], layer })
  function dust(o = {}) {
    let ctx;
    const n = o.n ?? 80, box = o.box || [0, 0, R.W, R.H], col = o.color || '#FFE2B0';
    R.overlay(t => {
      ctx.clearRect(0, 0, R.W, R.H);
      const a0 = Math.min(prog(t, R.when(o.from ?? 0), 0.8, ease.linear), 1 - prog(t, R.when(o.to ?? R.duration) - 0.8, 0.8, ease.linear));
      if (a0 <= 0) return;
      ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.fillStyle = col;
      for (let i = 0; i < n; i++) {
        const sp = (o.speed ?? 10) * (0.4 + rand(i, 3));
        const x = box[0] + (((rand(i, 1) * box[2] + R.noise(t * 0.2 + i, 7) * 30) % box[2]) + box[2]) % box[2];
        const y = box[1] + (((rand(i, 2) * box[3] - sp * t) % box[3]) + box[3]) % box[3];
        const r = (o.size ?? 1.6) * (0.4 + rand(i, 4) * 1.2);
        ctx.globalAlpha = a0 * (o.opacity ?? 0.5) * (0.5 + 0.5 * Math.sin(t * (1 + rand(i, 5) * 3) + i));
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
      }
      ctx.restore();
    }, { layer: o.layer || 'back', setup: p => { ctx = canvasLayer(p, 'fx-dust'); } });
  }

  // 천천히 도는 빛줄기(갓 레이). 타이틀·엔드카드 뒤에(기본 back).  FX.rays({ x, y, from, to, color, opacity: 0.12, n: 28, length: 1500 })
  function rays(o = {}) {
    let ctx;
    const col = o.color || '#F3C27A';
    R.overlay(t => {
      ctx.clearRect(0, 0, R.W, R.H);
      const a0 = Math.min(prog(t, R.when(o.from ?? 0), 1.0, ease.outCubic), 1 - prog(t, R.when(o.to ?? R.duration) - 0.6, 0.6, ease.linear));
      if (a0 <= 0) return;
      const x = o.x ?? R.W / 2, y = o.y ?? R.H * 0.38, n = o.n ?? 28, L = o.length ?? 1500;
      ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.translate(x, y);
      for (let i = 0; i < n; i++) {
        const ang = (i / n) * Math.PI * 2 + t * 0.05 + rand(i, 21) * 0.2, wv = 0.012 + rand(i, 22) * 0.03;
        const g = ctx.createLinearGradient(0, 0, Math.cos(ang) * L, Math.sin(ang) * L);
        g.addColorStop(0, col); g.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.globalAlpha = a0 * (o.opacity ?? 0.12) * (0.3 + 0.7 * (0.5 + 0.5 * Math.sin(t * 0.8 + i * 1.7)));
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.cos(ang - wv) * L, Math.sin(ang - wv) * L); ctx.lineTo(Math.cos(ang + wv) * L, Math.sin(ang + wv) * L); ctx.closePath(); ctx.fill();
      }
      ctx.restore();
    }, { layer: o.layer || 'back', setup: p => { ctx = canvasLayer(p, 'fx-rays'); } });
  }

  // 화면 전체를 덮었다가 걷히는 전환. t 에서 완전히 덮이므로 장면 경계를 t 에 둔다.
  //   FX.wipe([[t, { type: 'slats'|'bars', colors: ['#E8FF3A', '#6B4CFF'], n: 7, dir: 1, dur: 0.22 }]])
  //   slats: 가로 띠가 좌우로 엇갈려 들어왔다 빠진다. bars: 세로 막대가 아래에서 차례로 덮었다 위로 걷힌다.
  function wipe(list) {
    const sets = [];
    const items = list.map(([t0, o = {}]) => ({ t0: R.when(t0), type: o.type || 'slats', cols: o.colors || ['#F3C27A', '#0B0D14'], n: o.n ?? 7, dir: o.dir ?? 1, d: o.dur ?? 0.22 }));
    R.overlay(t => {
      items.forEach((it, k) => {
        const els = sets[k], lt = t - it.t0;
        if (lt < -it.d - 0.05 || lt > it.d * 1.6 + 0.05) { if (els[0].style.display !== 'none') els.forEach(e => (e.style.display = 'none')); return; }
        els.forEach((e, i) => {
          const off = (i / it.n) * it.d * 0.6;
          const pin = prog(t, it.t0 - it.d + off * 0.5, it.d * 0.7, ease.inCubic);   // 덮기(t 에 모두 덮임)
          const pout = prog(t, it.t0 + off, it.d * 0.9, ease.outCubic);             // 걷기
          const sgn = (it.type === 'slats' ? (i % 2 ? -1 : 1) : 1) * it.dir;
          const pos = pout > 0 ? sgn * pout * 101 : sgn * (pin - 1) * 101;          // %, 0 이면 덮음
          e.style.display = Math.abs(pos) >= 100.5 ? 'none' : '';
          e.style.transform = it.type === 'slats' ? `translateX(${pos.toFixed(2)}%)` : `translateY(${(-pos).toFixed(2)}%)`;
        });
      });
    }, { setup: p => {
      const root = h('div', 'fx-wipe', p); root.style.cssText = full + 'overflow:hidden';
      items.forEach(it => {
        const els = [];
        for (let i = 0; i < it.n; i++) {
          const e = h('div', null, root), c = it.cols[i % it.cols.length];
          e.style.cssText = it.type === 'slats'
            ? `position:absolute;left:-1px;right:-1px;top:${(i * 100 / it.n).toFixed(3)}%;height:${(100 / it.n + 0.2).toFixed(3)}%;background:${c};display:none`
            : `position:absolute;top:-1px;bottom:-1px;left:${(i * 100 / it.n).toFixed(3)}%;width:${(100 / it.n + 0.2).toFixed(3)}%;background:${c};display:none`;
          els.push(e);
        }
        sets.push(els);
      });
    } });
  }

  function flash(list) {
    let el;
    R.overlay(t => {
      let a = 0, color = '#fff';
      for (const [t0, dur = 0.18, op = 0.22, c = '#fff'] of list) {
        const dt = t - t0;
        if (dt < 0 || dt > dur) continue;
        const v = op * (dt < 0.02 ? dt / 0.02 : Math.pow(1 - (dt - 0.02) / (dur - 0.02), 2));
        if (v > a) { a = v; color = c; }
      }
      el.style.opacity = a.toFixed(3);
      if (a > 0) el.style.background = color;
    }, { setup: p => { el = h('div', 'fx-flash', p); el.style.cssText = full + 'mix-blend-mode:screen;opacity:0'; } });
  }

  function leak(list) {
    const els = [];
    R.overlay(t => {
      list.forEach(([t0, dur = 1.2, color = '#ffb347', x = 0.7], i) => {
        const p = (t - t0) / dur;
        const el = els[i];
        if (p < 0 || p > 1) { el.style.opacity = 0; return; }
        const a = Math.sin(Math.PI * p);
        css(el, { opacity: (a * 0.55).toFixed(3), transform: `translateX(${((p - 0.5) * 900).toFixed(1)}px)`,
          background: `radial-gradient(ellipse 38% 70% at ${x * 100}% 45%, ${color} 0%, transparent 70%)` });
      });
    }, { setup: p => list.forEach(() => { const e = h('div', 'fx-leak', p); e.style.cssText = full + 'mix-blend-mode:screen;filter:blur(30px);opacity:0'; els.push(e); }) });
  }

  function letterbox(fn, opts = {}) {
    let a, b;
    R.overlay(t => {
      const full_h = (R.H - R.W / (opts.ratio || 2.39)) / 2;
      const hgt = (clamp(fn(t)) * full_h).toFixed(1) + 'px';
      a.style.height = hgt; b.style.height = hgt;
    }, { setup: p => {
      a = h('div', 'fx-lb', p); b = h('div', 'fx-lb', p);
      a.style.cssText = 'position:absolute;left:0;right:0;top:0;height:0;background:#000;pointer-events:none';
      b.style.cssText = 'position:absolute;left:0;right:0;bottom:0;height:0;background:#000;pointer-events:none';
    } });
  }

  function vignette(opts = {}) {
    const k = opts.strength ?? 0.6;
    R.overlay(() => {}, { setup: p => { const e = h('div', 'fx-vig', p);
      e.style.cssText = full + `background:radial-gradient(ellipse 80% 75% at 50% 50%, rgba(0,0,0,0) 52%, rgba(0,0,0,${k}) 100%)`; } });
  }

  function grain(opts = {}) {
    const fps = opts.fps || 24, N = 8;
    let cv, frames = [];
    R.overlay(t => {
      const i = Math.floor(t * fps) % N;
      const ctx = cv.getContext('2d');
      ctx.putImageData(frames[i], 0, 0);
    }, { setup: p => {
      cv = h('canvas', 'fx-grain', p);
      cv.width = 640; cv.height = Math.round(640 * R.H / R.W);
      cv.style.cssText = full + `width:100%;height:100%;mix-blend-mode:overlay;opacity:${opts.opacity ?? 0.09};image-rendering:auto`;
      const ctx = cv.getContext('2d');
      for (let f = 0; f < N; f++) {
        const img = ctx.createImageData(cv.width, cv.height);
        for (let j = 0; j < img.data.length; j += 4) {
          const v = 128 + (rand(j * 0.25 + f * 7919, 3) - 0.5) * 255;
          img.data[j] = img.data[j + 1] = img.data[j + 2] = v; img.data[j + 3] = 255;
        }
        frames.push(img);
      }
    } });
  }

  function hud(opts = {}) {
    const color = opts.color || 'rgba(243,239,230,0.72)';
    const font = opts.font || '"JetBrains Mono", "Pretendard", monospace';
    const chapters = opts.chapters || [];
    const from = opts.from ?? 0.4, to = opts.to ?? R.duration;
    let root, tl, tr, bl, br, bar, corners = [];
    R.overlay(t => {
      const a = Math.min(prog(t, from, 0.6), 1 - prog(t, to - 0.5, 0.5));
      root.style.opacity = a.toFixed(3);
      if (a <= 0) return;
      if (opts.timecode !== false) {
        const fr = Math.floor(t * R.fps), ss = Math.floor(t);
        bl.textContent = `TC 00:${String(Math.floor(ss / 60)).padStart(2, '0')}:${String(ss % 60).padStart(2, '0')}:${String(fr % R.fps).padStart(2, '0')}`;
      }
      let ch = '';
      for (const [t0, label] of chapters) if (t >= R.when(t0)) ch = label;
      if (opts.right) ch = opts.right(t) || ch;
      if (tr.textContent !== ch) tr.textContent = ch;
      if (bar) bar.style.transform = `scaleX(${(t / R.duration).toFixed(4)})`;
    }, { setup: p => {
      root = h('div', 'fx-hud', p);
      root.style.cssText = full + `font:500 15px/1 ${font};letter-spacing:.18em;color:${color};text-transform:uppercase`;
      // 세로(9:16) 영상은 앱 UI(위 약 250px, 아래 약 420px)를 피한다
      const vertical = R.H > R.W;
      const mx = opts.marginX ?? (vertical ? 60 : 46), mt = opts.marginTop ?? (vertical ? 250 : 46), mb = opts.marginBottom ?? (vertical ? 420 : 46);
      const pos = (x, y) => `position:absolute;${x};${y};`;
      tl = h('div', null, root, opts.left || ''); tl.style.cssText = pos(`left:${mx + 18}px`, `top:${mt}px`);
      tr = h('div', null, root, ''); tr.style.cssText = pos(`right:${mx + 18}px`, `top:${mt}px`) + 'text-align:right';
      bl = h('div', null, root, ''); bl.style.cssText = pos(`left:${mx + 18}px`, `bottom:${mb}px`);
      br = h('div', null, root, opts.br || ''); br.style.cssText = pos(`right:${mx + 18}px`, `bottom:${mb}px`) + 'text-align:right';
      if (opts.corners !== false) {
        for (const [x, y] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
          const c = h('div', null, root);
          c.style.cssText = `position:absolute;width:22px;height:22px;${x ? 'right' : 'left'}:${mx - 18}px;${y ? 'bottom' : 'top'}:${(y ? mb : mt) - 18}px;` +
            `border-${x ? 'right' : 'left'}:2px solid ${color};border-${y ? 'bottom' : 'top'}:2px solid ${color}`;
          corners.push(c);
        }
      }
      if (opts.progress !== false) {
        bar = h('div', null, root);
        bar.style.cssText = `position:absolute;left:0;bottom:0;width:100%;height:3px;background:${opts.accent || color};transform-origin:0 50%;transform:scaleX(0)`;
      }
    } });
  }

  function subtitles(opts = {}) {
    const lines = (opts.lines || R.TL.vo || []).filter(l => (l.sub || l.text) && !l.nosub);
    let el, cur = null;
    const size = opts.size || 40;
    R.overlay(t => {
      let hit = null;
      for (const l of lines) if (t >= l.start - 0.05 && t < l.end + 0.25) hit = l;
      if (!hit) { el.style.opacity = 0; cur = null; return; }
      if (cur !== hit) { el.textContent = hit.sub || hit.text; cur = hit; }
      const a = Math.min(prog(t, hit.start - 0.05, 0.15, ease.linear), 1 - prog(t, hit.end + 0.1, 0.15, ease.linear));
      el.style.opacity = a.toFixed(3);
    }, { setup: p => {
      el = h('div', 'fx-sub', p);
      el.style.cssText = `position:absolute;left:6%;right:6%;bottom:${opts.bottom ?? (R.H > R.W ? 440 : 64)}px;text-align:center;` +
        `font:${opts.weight || 600} ${size}px/1.35 ${opts.font || '"Pretendard", sans-serif'};letter-spacing:-0.01em;color:#fff;word-break:keep-all;` +
        `text-shadow:0 2px 12px rgba(0,0,0,.85),0 0 30px rgba(0,0,0,.6);pointer-events:none;opacity:0`;
    } });
  }

  window.FX = { camera, impact, floor, dust, rays, wipe, flash, leak, letterbox, vignette, grain, hud, subtitles };
})();
