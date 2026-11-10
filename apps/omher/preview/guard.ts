// The preview inside the omher.app hero: page scroll, inert actions, and the visitor's first click.
// - Wheel: until the visitor clicks into the window, every wheel scrolls the page (the window never traps it).
//   After a click it scrolls the pane under the cursor when that pane can move that way, else the page.
// - Things that would start real work (add a bot, a new session, attachments, Automations, Plugins) show one small
//   note instead: "Download omher to …". Nothing is started anywhere.
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

const INERT: [string, string][] = [
  ['[data-testid="session-new"], [data-testid="session-start"]', "This is a preview. Download omher to start a real session."],
  ['[aria-label="Add a bot"]', "This is a preview. Download omher to connect your Hermes bots."],
  ['[data-testid="attach"]', "This is a preview. Download omher to send files to your bots."],
  ['[data-testid="nav-automations"], [data-testid="nav-plugins"]', "Coming in a later version of omher."],
];

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
          toast(text);
          return;
        }
      }
    },
    { capture: true },
  );
  // a disabled nav row swallows clicks, so its note goes on pointerdown
  addEventListener(
    "pointerdown",
    (e) => {
      const hit = (e.target as Element | null)?.closest('[data-testid="nav-automations"], [data-testid="nav-plugins"]');
      if (hit) toast("Coming in a later version of omher.");
    },
    { capture: true },
  );
}
