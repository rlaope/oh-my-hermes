// The preview inside the omher.app hero: page scroll, inert actions, and the visitor's first click.
// - Wheel: until the visitor clicks into the window, every wheel scrolls the page (the window never traps it).
//   After a click it scrolls the pane under the cursor when that pane can move that way, else the page.
// - Things that would start real work (add a bot, attachments, changing an automation or a plugin) show one small
//   note instead: "Download omher to …". Nothing is started anywhere. The Automations and Plugins pages themselves
//   open on staged data (host.ts), so a visitor can look around them.
const W = window as unknown as { __omherPreviewToasts?: string[] };

let focused = false;
function scrollable(el: Element | null, dy: number, dx: number): boolean {
  for (let n = el; n && n !== document.body; n = n.parentElement) {
    const s = getComputedStyle(n);
    const y = /(auto|scroll)/.test(s.overflowY) && n.scrollHeight > n.clientHeight + 1;
    const x = /(auto|scroll)/.test(s.overflowX) && n.scrollWidth > n.clientWidth + 1;
    if (y && Math.abs(dy) >= Math.abs(dx)) {
      if ((dy < 0 && n.scrollTop > 0) || (dy > 0 && n.scrollTop + n.clientHeight < n.scrollHeight - 1)) return true;
    }
    if (x && Math.abs(dx) > Math.abs(dy)) {
      if ((dx < 0 && n.scrollLeft > 0) || (dx > 0 && n.scrollLeft + n.clientWidth < n.scrollWidth - 1)) return true;
    }
  }
  return false;
}

let toastEl: HTMLDivElement | null = null;
let toastTimer = 0;
export function toast(text: string): void {
  (W.__omherPreviewToasts ??= []).push(text);
  if (!toastEl) {
    toastEl = document.createElement("div");
    toastEl.className = "pv-toast";
    toastEl.setAttribute("role", "status");
    toastEl.dataset.testid = "preview-toast";
    document.body.appendChild(toastEl);
  }
  toastEl.textContent = text;
  toastEl.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toastEl?.classList.remove("on"), 2600);
}

// SESSIONS + opens a New session draft (from 0.2.3 nothing runs until its first message), so it stays live here;
// the mock agent answers that first message with the preview note (vite.config.ts hook). Automations and Plugins
// open (from 0.2.4 they work in the app); only what would change a bot's jobs or plugins is held back. Asking a bot
// from those pages, Run now and Edit are chat messages, which the story answers.
type Note = Record<"en" | "ko" | "ja" | "zh", string>;
const INERT: [string, Note][] = [
  [
    ".side-add .ui-ib",
    {
      en: "This is a preview. Download omher to connect your Hermes bots.",
      ko: "미리보기 화면이에요. omher를 내려받으면 내 Hermes 봇을 연결할 수 있어요.",
      ja: "これはプレビューです。omher をダウンロードすると Hermes のボットをつなげます。",
      zh: "这是预览。下载 omher 即可连接你的 Hermes 机器人。",
    },
  ],
  [
    '[data-testid="attach"]',
    {
      en: "This is a preview. Download omher to send files to your bots and sessions.",
      ko: "미리보기 화면이에요. omher를 내려받으면 봇과 세션에 파일을 보낼 수 있어요.",
      ja: "これはプレビューです。omher をダウンロードするとボットやセッションにファイルを送れます。",
      zh: "这是预览。下载 omher 即可向机器人和会话发送文件。",
    },
  ],
  [
    '[data-testid^="auto-toggle-"], [data-testid="auto-pause"], [data-testid="auto-delete"], [data-testid="auto-new"]',
    {
      en: "This is a preview. Download omher to manage your bots' automations.",
      ko: "미리보기 화면이에요. omher를 내려받으면 봇의 자동화를 관리할 수 있어요.",
      ja: "これはプレビューです。omher をダウンロードするとボットのオートメーションを管理できます。",
      zh: "这是预览。下载 omher 即可管理机器人的自动化任务。",
    },
  ],
  [
    '[data-testid^="plug-toggle-"], [data-testid="sheet-install"], [data-testid="plug-update"], [data-testid="plug-remove"]',
    {
      en: "This is a preview. Download omher to add and manage your bots' plugins.",
      ko: "미리보기 화면이에요. omher를 내려받으면 봇의 플러그인을 추가하고 관리할 수 있어요.",
      ja: "これはプレビューです。omher をダウンロードするとボットのプラグインを追加・管理できます。",
      zh: "这是预览。下载 omher 即可为机器人添加和管理插件。",
    },
  ],
];
const noteIn = (n: Note) => n[(document.documentElement.lang.slice(0, 2) as keyof Note) in n ? (document.documentElement.lang.slice(0, 2) as keyof Note) : "en"];

export function installGuards(): void {
  addEventListener(
    "wheel",
    (e) => {
      if (window.parent === window) return;
      if (focused && scrollable(e.target as Element, e.deltaY, e.deltaX)) return;
      e.preventDefault();
      const k = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? innerHeight : 1;
      parent.postMessage({ type: "omher-preview:wheel", dx: e.deltaX * k, dy: e.deltaY * k }, location.origin);
    },
    { passive: false, capture: true },
  );
  addEventListener("pointerdown", () => (focused = true), { capture: true });
  addEventListener("blur", () => (focused = false));
  addEventListener(
    "click",
    (e) => {
      const t = e.target as Element | null;
      if (!t) return;
      for (const [sel, text] of INERT) {
        const hit = t.closest(sel);
        if (hit && !hit.closest('[role="menu"]')) {
          e.preventDefault();
          e.stopPropagation();
          toast(noteIn(text));
          return;
        }
      }
    },
    { capture: true },
  );
}
