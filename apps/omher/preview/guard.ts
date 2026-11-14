// The preview inside the omher.app hero: page scroll, inert actions, and the visitor's first click.
// - Wheel: until the visitor clicks into the window, every wheel scrolls the page (the window never traps it).
//   After a click it scrolls the pane under the cursor when that pane can move that way, else the page.
// - Things that would start real work (add a bot, attachments, changing an automation or a plugin, restarting a bot,
//   a session in the agent's own terminal, taking a message back, installing oh-my-hermes, opening a session's folder
//   in the file manager or the system terminal) show one small note instead: "Download omher to …". Nothing is
//   started anywhere. The Automations and Plugins pages themselves open on staged data (host.ts), so a visitor can
//   look around them.
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
// from those pages, Run now and Edit are chat messages, which the story answers. From 0.2.6: Restart / Start in a
// bot row's menu (and every other Restart press: an offline chat, after a plugin change, Restart anyway), a session
// run as the agent's own terminal (the draft's Terminal choice, Start, the header's terminal button), Edit on the
// last message of a session (the agent's own rewind) and the oh-my-hermes installer behind the sidebar's "!".
// From 0.2.7: Show in Finder / Explorer and Open in Terminal in a session row's right-click menu. The staged
// sessions' folders (/Users/you/code/…) are on nobody's computer, and the app's in-page session host only records
// those two calls, so each was a click that did nothing. The menu's other items stay live: Rename, Copy conversation
// id, New session here and Close session act on the staged session only, and Continue a conversation in the + menu
// lists the in-page host's staged conversations.
// The third field lets a note fire inside a menu (the bot row's menu, a session row's); other menus keep their own
// items.
type Note = Record<"en" | "ko" | "ja" | "zh", string>;
const INERT: [string, Note, boolean?][] = [
  [
    ".side-add > .ui-ib",
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
    '[data-testid^="plug-toggle-"], [data-testid="sheet-install"], [data-testid="plug-update"], [data-testid="plug-remove"], [data-testid$="load-now"]',
    {
      en: "This is a preview. Download omher to add and manage your bots' plugins.",
      ko: "미리보기 화면이에요. omher를 내려받으면 봇의 플러그인을 추가하고 관리할 수 있어요.",
      ja: "これはプレビューです。omher をダウンロードするとボットのプラグインを追加・管理できます。",
      zh: "这是预览。下载 omher 即可为机器人添加和管理插件。",
    },
  ],
  [
    '[data-testid="row-restart"], [data-testid="chat-start"], [data-testid$="load-restart"], [data-testid="restart-press"], [data-testid="restart-anyway"], [data-testid="restart-again"]',
    {
      en: "This is a preview. Download omher to restart your own bots.",
      ko: "미리보기 화면이에요. omher를 내려받으면 내 봇을 재시작할 수 있어요.",
      ja: "これはプレビューです。omher をダウンロードすると自分のボットを再起動できます。",
      zh: "这是预览。下载 omher 即可重启你自己的机器人。",
    },
    true,
  ],
  [
    '[data-testid="session-way-terminal"], [data-testid="session-go"], [data-testid="session-terminal-toggle"]',
    {
      en: "This is a preview. Download omher to run the agent in its own terminal in your folder.",
      ko: "미리보기 화면이에요. omher를 내려받으면 내 폴더에서 에이전트를 자기 터미널로 실행할 수 있어요.",
      ja: "これはプレビューです。omher をダウンロードすると、自分のフォルダでエージェントを専用のターミナルで動かせます。",
      zh: "这是预览。下载 omher 即可在你的文件夹里用智能体自己的终端运行它。",
    },
  ],
  [
    '[data-testid="bubble-edit"]',
    {
      en: "This is a preview. Download omher to take a message back and edit it in a real session.",
      ko: "미리보기 화면이에요. omher를 내려받으면 실제 세션에서 보낸 메시지를 되돌려 고칠 수 있어요.",
      ja: "これはプレビューです。omher をダウンロードすると、実際のセッションで送ったメッセージを取り消して直せます。",
      zh: "这是预览。下载 omher 即可在真实会话中撤回并修改已发送的消息。",
    },
  ],
  [
    '[data-testid="omh-pop-install"], [data-testid="session-add-omh"]',
    {
      en: "This is a preview. Download omher to add oh-my-hermes to your Hermes.",
      ko: "미리보기 화면이에요. omher를 내려받으면 내 Hermes에 oh-my-hermes를 설치할 수 있어요.",
      ja: "これはプレビューです。omher をダウンロードすると Hermes に oh-my-hermes を追加できます。",
      zh: "这是预览。下载 omher 即可为你的 Hermes 添加 oh-my-hermes。",
    },
    true,
  ],
  [
    '[data-testid="session-reveal"], [data-testid="session-system-terminal"]',
    {
      en: "This is a preview. Download omher to open a session's folder in your file manager or your own terminal.",
      ko: "미리보기 화면이에요. omher를 내려받으면 세션 폴더를 파일 관리자나 내 터미널에서 열 수 있어요.",
      ja: "これはプレビューです。omher をダウンロードすると、セッションのフォルダをファイルマネージャーや自分のターミナルで開けます。",
      zh: "这是预览。下载 omher 即可在文件管理器或你自己的终端中打开会话的文件夹。",
    },
    true,
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
      for (const [sel, text, inMenu] of INERT) {
        const hit = t.closest(sel);
        const menu = hit?.closest<HTMLElement>('[role="menu"]');
        if (hit && (!menu || inMenu)) {
          e.preventDefault();
          e.stopPropagation();
          toast(noteIn(text));
          // a menu item: the menu closes as after any pick (its own Escape)
          menu?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
          return;
        }
      }
    },
    { capture: true },
  );
}
