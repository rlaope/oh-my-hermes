/* MIT; Copyright (c) 2026 Minho Hwang (revfactory).
 * From revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6 assets/engine/scenes.js.
 * Upstream API example scenes (new_project.py copies it to reel/_example_scenes.js; not loaded), unmodified below this notice.
 * Full permission/warranty: toolkit/LICENSE.upstream. Not imported or executed by OMH core. */
/* 엔진 API 사용 예시(12초). new_project.py 가 reel/_example_scenes.js 로 복사하며, 영상에는 불러오지 않는다.
 * 함수 쓰는 법을 보여 주려는 파일이다. 화면 구성·색·움직임을 새 영상의 출발점으로 삼지 않는다(references/design.md "뻔한 화면").
 *   A 오프닝: 선이 그어지고 글자가 마스크 안에서 솟은 뒤, 핵심어가 슬램(블러→선명)으로 떨어진다 + 섬광·흔들림
 *   B 숫자:   거대 외곽선 마키 위로 숫자 카운트업, 스크램블로 풀리는 챕터 라벨
 *   C 사진:   캔버스로 그린 '사진' 카드가 3D로 기울며 클립 와이프로 열리고 켄 번스, 단어 단위 헤드라인
 *   D 엔드카드: 입자가 모여 글자가 되고, 세리프 이름 + 빛 스윕
 * 쓰인 FX: 장면을 천천히 미는 push, 장면 뒤 격자 바닥·먼지, FX.impact + 흔들림, 장면 사이 휩 팬(B→C), 퇴장 inout(위로 밀리며 줄고 흐려짐).
 * 시각은 숫자로 적었지만 나레이션이 있으면 REEL.cue('이름', 기본값)로 timeline.js 의 큐를 쓰고,
 *   장면 경계는 음악 마디(REEL.bar(n) 또는 큐 'bar9')에 놓는다.
 */
const { ease, prog, win, kf, clamp, lerp, rand, split, stagger, inout, count, scramble, css, h, s, cue } = REEL;
REEL.config({ duration: 12, fps: 30, width: 1920, height: 1080, audio: null, push: 0.03 });   // push: 장면마다 3% 천천히 확대

const HIT_SLAM = cue('slam', 1.55);
const HIT_END = cue('end_hit', 9.6);
const CUT_PHOTO = 6.1;   // B → C 휩 팬 시각(두 장면의 경계)

/* ───────── A. 오프닝 ───────── */
REEL.scene({
  id: 'open', start: 0, end: 3.1,
  setup(el) {
    this.line = h('div', 'a', el);
    css(this.line, { left: '0', top: '540px', width: '1920px', height: '2px', background: 'var(--accent)', transformOrigin: '50% 50%' });
    this.l1 = h('div', 'center display', el, '1분 안에,');
    css(this.l1, { top: '330px', fontSize: '120px', fontWeight: 700, color: 'var(--dim)' });
    this.c1 = split(this.l1, 'char', { mask: true });
    this.l2 = h('div', 'center display', el, '모든 경력을.');
    css(this.l2, { top: '470px', fontSize: '220px' });
    this.ghost = h('div', 'center display', el, '모든 경력을.');   // 슬램 잔상
    css(this.ghost, { top: '470px', fontSize: '220px', color: 'var(--accent)', mixBlendMode: 'screen' });
  },
  render(lt) {
    const lp = kf(lt, [[0, 0], [0.55, 1, ease.swift], [1.2, 1], [1.45, 0, ease.exit]]);
    css(this.line, { transform: `scaleX(${lp})`, opacity: 1 - prog(lt, 1.2, 0.25) });
    this.c1.forEach((c, i) => {
      const p = stagger(lt, 0.35, 0.05, 0.6, i);
      const o = prog(lt, 2.5, 0.35, ease.exit);
      css(c, { transform: `translateY(${(1 - p) * 135 - o * 135}%)`, opacity: p > 0 ? 1 : 0, filter: `blur(${(1 - p) * 8}px)` });
    });
    const sp = prog(lt, HIT_SLAM - 0.25, 0.32, ease.snap);              // 슬램은 히트 직전에 시작해 히트에 착지
    const out = prog(lt, 2.6, 0.45, ease.exit);
    css(this.l2, { opacity: sp * (1 - out), transform: `scale(${lerp(1.9, 1, sp) * (1 - out * 0.08)})`, filter: `blur(${(1 - sp) * 24 + out * 12}px)` });
    const g = prog(lt, HIT_SLAM, 0.5, ease.snap);
    css(this.ghost, { opacity: (1 - g) * (sp > 0.99 ? 0.7 : 0), transform: `scale(${1 + g * 0.18})`, filter: `blur(${g * 10}px)` });
  },
});

/* ───────── B. 숫자 ───────── */
REEL.scene({
  id: 'number', start: 2.9, end: CUT_PHOTO,
  setup(el) {
    this.marq = h('div', 'a display', el, 'SINCE 1999 — SINCE 1999 — SINCE 1999 — ');
    css(this.marq, { top: '380px', left: '0', fontFamily: 'var(--num)', fontSize: '340px', whiteSpace: 'nowrap', color: 'transparent',
      WebkitTextStroke: '2px rgba(243,239,230,.12)', letterSpacing: '0' });
    this.tag = h('div', 'a label', el, '');
    css(this.tag, { left: '160px', top: '250px', color: 'var(--accent)' });
    this.num = h('div', 'a', el, '0');
    css(this.num, { left: '150px', top: '300px', fontFamily: 'var(--num)', fontSize: '360px', lineHeight: '1', fontVariantNumeric: 'tabular-nums' });
    this.unit = h('div', 'a display', el, '명의 관객');
    css(this.unit, { left: '160px', top: '730px', fontSize: '84px', fontWeight: 800 });
    this.uc = split(this.unit, 'char', { mask: true });
    this.wipe = h('div', 'full', el);
    css(this.wipe, { background: 'var(--accent)', transformOrigin: '0 50%' });
  },
  render(lt) {
    // 색면 와이프: 앞 장면 위로 덮으며 들어와(왼쪽 기준) 반대쪽으로 빠지며 새 장면을 드러낸다(오른쪽 기준)
    const wi = prog(lt, 0, 0.22, ease.swift), wo = prog(lt, 0.22, 0.3, ease.swift);
    css(this.wipe, { transform: `scaleX(${wo > 0 ? 1 - wo : wi})`, transformOrigin: wo > 0 ? '100% 50%' : '0% 50%' });
    css(this.marq, { transform: `translateX(${-200 - lt * 120}px)` });
    this.tag.textContent = scramble('CH.01 — PROOF', prog(lt, 0.3, 0.6, ease.linear), lt, 7);
    const cp = prog(lt, 0.35, 1.6, ease.outQuart);
    this.num.textContent = count(cp, 12840000);
    // 숫자: 아래에서 올라와 자리 잡고, 휩 직전에 위로 밀리며 줄고 흐려진다(페이드만 쓰지 않는다)
    inout(this.num, lt, 0.3, CUT_PHOTO - 2.9 - 0.05, { inDur: 0.6, rise: 60, from: 1 });
    this.uc.forEach((c, i) => { const q = stagger(lt, 1.2, 0.04, 0.5, i); css(c, { transform: `translateY(${(1 - q) * 135}%)`, opacity: q > 0 ? 1 : 0 }); });
    inout(this.unit, lt, 0, CUT_PHOTO - 2.9 - 0.02, { inDur: 0.01, rise: 0, from: 1 });
  },
});

/* ───────── C. 사진 카드 ───────── */
REEL.scene({
  id: 'photo', start: CUT_PHOTO, end: 9.4,
  setup(el) {
    // 실제 작업에서는 REEL.img('../assets/img/x.jpg') 를 쓴다. 여기선 캔버스로 '사진'을 그린다.
    const cv = h('canvas', 'a', el); cv.width = 1100; cv.height = 680;
    const g = cv.getContext('2d');
    const gr = g.createLinearGradient(0, 0, 1100, 680); gr.addColorStop(0, '#2b1d0e'); gr.addColorStop(0.55, '#7a4a1c'); gr.addColorStop(1, '#0d0b14');
    g.fillStyle = gr; g.fillRect(0, 0, 1100, 680);
    for (let i = 0; i < 90; i++) { g.fillStyle = `rgba(255,${180 + rand(i) * 60},120,${0.04 + rand(i, 2) * 0.1})`; g.beginPath(); g.arc(rand(i, 3) * 1100, rand(i, 4) * 680, 20 + rand(i, 5) * 120, 0, 7); g.fill(); }
    this.card = h('div', 'a', el);
    css(this.card, { left: '760px', top: '200px', width: '1000px', height: '620px', overflow: 'hidden', boxShadow: '0 40px 90px rgba(0,0,0,.6)', outline: '1px solid rgba(255,255,255,.12)' });
    this.card.appendChild(cv); css(cv, { left: '-50px', top: '-30px' }); this.cv = cv;
    this.kick = h('div', 'a label', el, '');
    css(this.kick, { left: '160px', top: '330px' });
    this.head = h('div', 'a display', el, '흩어진 기록을,<br>한 편으로.');
    css(this.head, { left: '150px', top: '380px', fontSize: '120px', lineHeight: '1.08' });
    this.words = [];
    for (const node of [...this.head.childNodes]) if (node.nodeType === 3) { const sp = h('span', null, null, node.textContent); this.head.replaceChild(sp, node); this.words.push(...split(sp, 'word', { mask: true })); }
    this.words[this.words.length - 1].style.color = 'var(--accent)';
  },
  render(lt) {
    const open = prog(lt, 0.15, 0.7, ease.swift);
    const o = prog(lt, 2.9, 0.35, ease.exit);
    css(this.card, { clipPath: `inset(0 ${(1 - open) * 100}% 0 0)`, transform: `perspective(1600px) rotateY(${lerp(-18, -6, open)}deg) translateX(${o * 200}px)`, opacity: 1 - o });
    css(this.cv, { transform: `scale(${1.08 + lt * 0.03}) translateX(${-lt * 10}px)` });  // 켄 번스: 멈추지 않는 미세 이동
    const full = 'ARCHIVE · 2026.10.07';
    this.kick.textContent = full.slice(0, Math.floor(prog(lt, 0.4, 0.6, ease.linear) * full.length)) + (Math.floor(lt * 4) % 2 ? '▍' : ' ');
    this.words.forEach((w, i) => { const q = stagger(lt, 0.6, 0.12, 0.55, i); css(w, { transform: `translateY(${(1 - q) * 135 - o * 135}%)`, opacity: q > 0 ? 1 : 0 }); });
  },
});

/* ───────── D. 엔드카드 ───────── */
REEL.scene({
  id: 'end', start: 9.2, end: 12,
  setup(el) {
    const W = 1920, H = 1080;
    this.cv = h('canvas', 'full', el); this.cv.width = W; this.cv.height = H;
    // 글자를 오프스크린에 그려 픽셀을 샘플링 → 입자 목표점 (폰트는 이미 로드된 상태)
    const off = document.createElement('canvas'); off.width = W; off.height = H;
    const g = off.getContext('2d');
    g.fillStyle = '#fff'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.font = '900 300px "Noto Serif KR", "Pretendard"'; g.fillText('홍길동', W / 2, 470);
    const data = g.getImageData(0, 0, W, H).data, pts = [];
    for (let y = 0; y < H; y += 5) for (let x = 0; x < W; x += 5) if (data[(y * W + x) * 4 + 3] > 128) pts.push([x, y]);
    this.P = Array.from({ length: Math.min(2600, pts.length) }, (_, i) => {
      const [tx, ty] = pts[Math.floor(rand(i, 11) * pts.length)];
      const a = rand(i, 12) * Math.PI * 2, r = 700 + rand(i, 13) * 700;
      return { tx, ty, sx: W / 2 + Math.cos(a) * r, sy: H / 2 + Math.sin(a) * r, d: rand(i, 14) * 0.5, s: 1.2 + rand(i, 15) * 2.2 };
    });
    this.name = h('div', 'center', el, '홍길동');
    css(this.name, { top: '305px', fontFamily: 'var(--serif)', fontWeight: 900, fontSize: '300px', lineHeight: '1.1',
      backgroundImage: 'linear-gradient(105deg, var(--ink) 40%, #fff6dc 50%, var(--ink) 60%)', backgroundSize: '300% 100%',
      WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent' });
    this.role = h('div', 'center label', el, 'MOTION DESIGNER — SHOWREEL 2026');
    css(this.role, { top: '700px', fontSize: '22px', letterSpacing: '.5em', color: 'var(--accent)' });
  },
  render(lt) {
    const g = this.cv.getContext('2d');
    g.clearRect(0, 0, 1920, 1080);
    const form = prog(lt, 0, 0.9, ease.linear);
    const fade = 1 - prog(lt, 0.35, 0.3, ease.linear);   // 입자가 모이면 실제 글자로 교체
    if (fade > 0) {
      g.globalCompositeOperation = 'lighter';
      for (const p of this.P) {
        const q = ease.snap(clamp((form - p.d * 0.5) / 0.6));
        const sw = (1 - q) * 120;
        const x = lerp(p.sx, p.tx, q) + Math.sin(p.d * 40 + lt * 3) * sw;
        const y = lerp(p.sy, p.ty, q) + Math.cos(p.d * 40 + lt * 3) * sw;
        g.fillStyle = `rgba(245,${185 + p.d * 70},${66 + p.d * 120},${0.85 * fade})`;
        g.fillRect(x, y, p.s, p.s);
      }
      g.globalCompositeOperation = 'source-over';
    }
    const np = prog(lt, HIT_END - 9.2 - 0.05, 0.25);
    const out = prog(lt, 2.35, 0.4, ease.linear);
    css(this.name, { opacity: np * (1 - out), transform: `scale(${lerp(1.06, 1, np) + lt * 0.006})`, backgroundPosition: `${lerp(100, -100, prog(lt, 1.2, 1.1, ease.inOutSine))}% 0` });
    css(this.role, { opacity: prog(lt, 0.9, 0.5) * (1 - out), letterSpacing: `${lerp(0.9, 0.5, prog(lt, 0.9, 1.2))}em` });
  },
});

/* ───────── 전역 레이어 ───────── */
/* 아래 전역 레이어 조합(격자 바닥·먼지·임팩트·레터박스·비네트·그레인·HUD)은 design.md 의 "뻔한 화면"과 같다. 호출 형식만 참고한다. */
FX.floor({ from: 2.9, to: 9.3 });                                     // 장면 뒤: 흘러오는 격자 바닥(검은 배경이 멈춰 보이지 않게)
FX.dust({ n: 70, opacity: 0.4 });                                     // 장면 뒤: 떠다니는 빛 먼지
FX.rays({ from: 9.2, y: 470 });                                       // 엔드카드 뒤: 천천히 도는 빛줄기
FX.camera({ shakes: [[HIT_SLAM, 14, 0.4], [HIT_END, 10, 0.4]], drift: 0.6, whips: [[CUT_PHOTO, 1]],
  beat: { hits: (REEL.TL.music && REEL.TL.music.hits) || [], amount: 0.01 } });   // 음악 히트마다 살짝 밀려 들어옴
FX.impact([[HIT_SLAM, { y: 560 }], [HIT_END, { y: 470, size: 0.8 }]]);   // 빛점 + 충격파 + 사방 빛줄기 + 플레어
FX.flash([[HIT_SLAM, 0.2, 0.08], [HIT_END, 0.25, 0.08, '#ffe7b0']]);   // 어두운 배경에서 0.15 를 넘으면 화면이 회색으로 씻긴다
FX.leak([[6.2, 1.6, 'rgba(255,170,70,.9)', 0.75]]);
FX.letterbox(t => 1 - prog(t, 2.9, 0.5, ease.swift) + prog(t, 9.1, 0.4, ease.swift));
FX.vignette({ strength: 0.6 });
FX.grain({ opacity: 0.09 });
FX.hud({ left: '● SHOWREEL — 2026', chapters: [[0, 'PROLOGUE'], [2.9, 'CH.01 / PROOF'], [6.1, 'CH.02 / ARCHIVE'], [9.2, 'FIN']], from: 3.0, to: 11.6, accent: 'var(--accent)' });
FX.subtitles();
