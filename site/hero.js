/*!
 * omher.app top block, the live parts around the app window (our own code; ideas only from other sites).
 *  1. The live app: on a desktop-sized screen, once the page has loaded and gone idle, the real omher UI (site/app-preview,
 *     staged data, nothing leaves the page) loads into the window and crossfades in over the film (240 ms) when it
 *     says it is ready. Phones keep the still. The window never traps the page's scroll: the preview hands wheel
 *     movement back unless the visitor has clicked into it and the pane under the cursor can scroll.
 *  2. A light orbiting the window's edge: a short comet (white core, pink tail, faint bloom) travelling the rounded
 *     frame at constant speed (stroke dash along the path, ~7 s a lap). Hovering the window or a Download button
 *     speeds it up and brightens it, eased; the same hover draws a soft pink rim on the window and the pill.
 *  3. A border spotlight that follows the cursor along the window's edge, smoothed.
 * One rAF loop; it writes a few CSS variables and SVG attributes and never reads layout (the window's box is read on
 * scroll, resize and pointer moves). It idles while the tab is hidden or the block is off-screen. Under reduced
 * motion: a static faint rim and the still picture (no live app).
 */
(() => {
  const q = (s, r = document) => r.querySelector(s);
  const sec = q('[data-omher]'), shot = q('[data-app-shot]'), win = q('[data-app-win]'), pill = q('[data-dlpill]');
  if (!sec || !shot || !win) return;
  const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const DESK = matchMedia('(min-width: 761px)');
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const ez = (dt, rate) => 1 - Math.exp(-dt / 1000 * rate);
  const stats = window.__hero = {frames: 0, cpu: [], ready: false};
  let frameEl = null, live = null;   // the live app, once mounted (below)
  const NS = 'http://www.w3.org/2000/svg';

  /* ---------- light source: the header pill and the hero's main download button ---------- */
  let hot = 0, hotT = 0;
  const setHot = v => { hotT = v; sec.classList.toggle('is-hot', !!v); pill && pill.classList.toggle('is-hot', !!v); };
  pill && pill.addEventListener('pointerenter', () => setHot(1));
  pill && pill.addEventListener('pointerleave', () => setHot(0));
  const dl = q('[data-dl]', sec);
  dl && dl.addEventListener('pointerover', e => { if (e.target.closest('.osbtn--main')) setHot(1); });
  dl && dl.addEventListener('pointerout', e => { if (e.target.closest('.osbtn--main') && !(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('.osbtn--main'))) setHot(0); });
  let overWin = 0;
  shot.addEventListener('pointerenter', () => { overWin = 1; });
  shot.addEventListener('pointerleave', () => { overWin = 0; });

  /* ---------- the rim: one SVG over the window's frame ---------- */
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'omher__rim'); svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = `<defs>
      <radialGradient id="rimSpot" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="150"><stop offset="0" stop-color="#fff" stop-opacity=".9"/><stop offset=".45" stop-color="#ffd3e7" stop-opacity=".35"/><stop offset="1" stop-color="#ff5fa2" stop-opacity="0"/></radialGradient>
    </defs>
    <rect class="r-base"/><rect class="r-hot"/><rect class="r-spot" stroke="url(#rimSpot)"/>
    <rect class="r-c r-b3"/><rect class="r-c r-b2"/><rect class="r-c r-b1"/><rect class="r-c r-t"/><rect class="r-c r-m"/><rect class="r-c r-h"/>`;
  shot.appendChild(svg);
  const rects = [...svg.querySelectorAll('rect')];
  const comet = {b3: q('.r-b3', svg), b2: q('.r-b2', svg), b1: q('.r-b1', svg), t: q('.r-t', svg), m: q('.r-m', svg), h: q('.r-h', svg)};
  const spot = q('#rimSpot', svg), spotRect = q('.r-spot', svg);
  // dash lengths in pathLength units (1000 = one lap): tail 200 (20% of the frame), mid 80, core 24; blooms ride the same head
  const DASH = {b3: 150, b2: 130, b1: 90, t: 200, m: 80, h: 24};
  // the frame loop writes one number (--off); each layer's dash offset is computed from it in CSS
  for (const [k, el] of Object.entries(comet)) { el.setAttribute('pathLength', '1000'); el.setAttribute('stroke-dasharray', `${DASH[k]} ${1000 - DASH[k]}`); el.style.setProperty('--d', DASH[k]); }
  let RW = 0, RH = 0;
  function sizeRim() {
    RW = win.offsetWidth; RH = win.offsetHeight;
    svg.setAttribute('viewBox', `-12 -12 ${RW + 24} ${RH + 24}`);
    svg.style.width = (RW + 24) + 'px'; svg.style.height = (RH + 24) + 'px';
    const r = parseFloat(getComputedStyle(win).borderTopLeftRadius) || 7;
    for (const el of rects) { el.setAttribute('x', '.5'); el.setAttribute('y', '.5'); el.setAttribute('width', RW - 1); el.setAttribute('height', RH - 1); el.setAttribute('rx', r); }
  }

  function measure() { sizeRim(); fit(); }

  /* ---------- the frame loop ---------- */
  let raf = 0, last = 0, seen = true, head = Math.random() * 1000, speed = 1, bright = 1, hotW = -1, brightW = -1, sOnW = 1;
  const WR = {l: 0, t: 0, r: 0, b: 0};
  const readWin = () => { const r = win.getBoundingClientRect(); WR.l = r.left; WR.t = r.top; WR.r = r.right; WR.b = r.bottom; };
  addEventListener('scroll', readWin, {passive: true});
  addEventListener('resize', readWin);
  let cx = -1e4, cy = -1e4, tcx = -1e4, tcy = -1e4, pin = 0, pinT = 0, sx = 0, sy = 0, sT = 0, sOn = 0;
  addEventListener('pointermove', e => {
    readWin();
    tcx = e.clientX; tcy = e.clientY; pinT = e.pointerType === 'mouse' ? 1 : 0;
    if (pin < .01) { cx = tcx; cy = tcy; }
  }, {passive: true});
  document.documentElement.addEventListener('pointerleave', () => { pinT = 0; });
  function frame(now, dt) {
    const c0 = performance.now();
    hot += (Math.max(hotT, overWin * .6) - hot) * ez(dt, 6);
    // the comet: ~7 s a lap at rest, faster and brighter while a light source or the window is hovered
    speed += ((1 + 1.1 * hot) - speed) * ez(dt, 3);
    bright += ((1 + .35 * hot) - bright) * ez(dt, 4);
    head = (head + dt / 7000 * 1000 * speed) % 1000;
    svg.style.setProperty('--off', head.toFixed(2));
    if (Math.abs(hot - hotW) > .002 || Math.abs(bright - brightW) > .002) { svg.style.setProperty('--hot', hot.toFixed(3)); svg.style.setProperty('--glow', bright.toFixed(3)); hotW = hot; brightW = bright; }
    // the cursor: eased toward the pointer; the border spotlight follows it while it is near the window
    cx += (tcx - cx) * ez(dt, 10); cy += (tcy - cy) * ez(dt, 10); pin += (pinT - pin) * ez(dt, 5);
    // the window's box is read on scroll / resize / pointer moves (WR), never here
    const near = pin * clamp(1 - (Math.max(WR.l - cx, cx - WR.r, WR.t - cy, cy - WR.b, 0)) / 90, 0, 1);
    sOn += (near - sOn) * ez(dt, 6);
    if (sOn > .003 || sOnW > .003) {
      spot.setAttribute('cx', (cx - WR.l).toFixed(1)); spot.setAttribute('cy', (cy - WR.t).toFixed(1));
      spotRect.style.opacity = (sOn * .9).toFixed(3); sOnW = sOn;
    }
    stats.cpu[stats.frames % 3000] = performance.now() - c0; stats.frames++;
  }
  function loop(now) {
    raf = 0;
    if (document.hidden || !seen || !DESK.matches) { last = 0; return; }   // phones: no rim (hidden in CSS), no loop
    const dt = last ? Math.min(50, now - last) : 16; last = now;
    frame(now, dt);
    raf = requestAnimationFrame(loop);
  }
  const kick = () => { if (!RM && !raf) { last = 0; raf = requestAnimationFrame(loop); } };

  measure(); readWin();
  if (RM) svg.classList.add('still');
  addEventListener('resize', () => { measure(); kick(); });
  addEventListener('load', measure);
  if (document.fonts) document.fonts.ready.then(measure);
  if (window.ResizeObserver) new ResizeObserver(measure).observe(win);
  document.addEventListener('visibilitychange', () => { kick(); tellPreview(); });
  new IntersectionObserver(es => { seen = es[0].isIntersecting; kick(); tellPreview(); }).observe(sec);
  kick();

  /* ---------- the live app in the window ---------- */
  function tellPreview() {
    if (!frameEl || !frameEl.contentWindow) return;
    try { frameEl.contentWindow.postMessage({type: 'omher-preview:visible', visible: seen && !document.hidden}, location.origin); } catch (e) { /* not loaded yet */ }
  }
  const LW = 1200, LH = 720;   // the preview lays out 1200 wide (Plans panel open, chat still roomy) and is scaled to the window
  function fit() {
    if (!live || !frameEl) return;
    const body = live.querySelector('.omher__lbody'), k = body.clientWidth / LW;
    if (!k) return;
    frameEl.style.height = Math.round(body.clientHeight / k) + 'px';
    frameEl.style.transform = `scale(${k.toFixed(5)})`;
  }
  function mountLive() {
    if (live || !DESK.matches || RM) return;   // phones and reduced motion keep the still picture
    live = document.createElement('div');
    live.className = 'omher__live'; live.dataset.live = 'loading';
    live.innerHTML = '<div class="omher__bar" aria-hidden="true"><i></i><i></i><i></i><span>omher</span><b class="omher__try">Live preview · click around</b></div><div class="omher__lbody"></div>';
    frameEl = document.createElement('iframe');
    frameEl.title = 'Interactive omher preview';
    frameEl.loading = 'lazy';
    frameEl.width = LW; frameEl.height = LH;
    frameEl.setAttribute('tabindex', '0');
    frameEl.src = 'app-preview/';
    live.querySelector('.omher__lbody').appendChild(frameEl);
    win.appendChild(live);
    fit();
    if (window.ResizeObserver) new ResizeObserver(fit).observe(live);
  }
  addEventListener('message', e => {
    if (e.origin !== location.origin || !frameEl || e.source !== frameEl.contentWindow) return;
    const d = e.data || {};
    if (d.type === 'omher-preview:ready' && live) {
      live.dataset.live = 'ready'; stats.ready = true; tellPreview();
      // the film under it stops once the live window covers it
      setTimeout(() => { const v = q('[data-app-film]'); if (v) v.pause(); }, 400);
    } else if (d.type === 'omher-preview:touched' && live) {
      live.dataset.touched = '1';   // the visitor found it: the cue in the title bar fades
    } else if (d.type === 'omher-preview:wheel') {
      scrollBy({left: 0, top: +d.dy || 0, behavior: 'instant'});
    }
  });
  // after the page's own load and an idle moment, so the first paint and the poster come first
  const later = () => (window.requestIdleCallback ? requestIdleCallback(mountLive, {timeout: 1500}) : setTimeout(mountLive, 300));
  if (document.readyState === 'complete') later(); else addEventListener('load', later);
  DESK.addEventListener('change', () => { if (DESK.matches) { mountLive(); kick(); } });
})();
