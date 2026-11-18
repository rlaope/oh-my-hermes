// The macOS 2-Set Korean input replay, shared by term-exit.spec.ts and term-park.spec.ts.
import type { Page } from "@playwright/test";

/** Replay what WebKit sends for the macOS 2-Set Korean input source (xterm.js#6284's Safari 26.2 trace): no
 *  composition events; each syllable starts as `insertText` and is edited in place with `insertReplacementText`; each
 *  keyCode 229 keydown arrives after its input. `plain` keys pass through the IME; `enter` comes right after the last
 *  syllable. */
export async function webkit2Set(page: Page, steps: (string[] | string)[]) {
  await page.evaluate(async (all) => {
    const ta = document.querySelector<HTMLTextAreaElement>('[data-testid="terminal"] .xterm-helper-textarea')!;
    ta.focus();
    let start = ta.value.length;
    const input = (inputType: string, data: string) => {
      ta.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, composed: true, inputType, data }));
      if (inputType === "insertReplacementText") ta.value = ta.value.slice(0, start) + data;
      else {
        start = ta.value.length;
        ta.value += data;
      }
      ta.dispatchEvent(new InputEvent("input", { bubbles: true, composed: true, inputType, data }));
    };
    const key = (type: string, k: string, code: number) => {
      const e = new KeyboardEvent(type, { bubbles: true, cancelable: true, key: k, code: k === "Enter" ? "Enter" : "KeyA" });
      Object.defineProperty(e, "keyCode", { value: code });
      Object.defineProperty(e, "which", { value: code });
      ta.dispatchEvent(e);
      return !e.defaultPrevented;
    };
    const k229 = () => {
      key("keydown", "Process", 229);
      key("keyup", "Process", 229);
    };
    for (const step of all) {
      if (Array.isArray(step)) {
        // one syllable: [first jamo, edits...] (an edit equal to the syllable's end state repeats as WebKit does)
        input("insertText", step[0]);
        k229();
        for (const e of step.slice(1)) {
          input("insertReplacementText", e);
          k229();
        }
      } else if (step === "\r") {
        key("keydown", "Enter", 13);
        key("keyup", "Enter", 13);
      } else {
        const ok = key("keydown", step, step.toUpperCase().charCodeAt(0));
        if (ok) {
          const kp = new KeyboardEvent("keypress", { bubbles: true, cancelable: true, key: step });
          Object.defineProperty(kp, "charCode", { value: step.charCodeAt(0) });
          Object.defineProperty(kp, "keyCode", { value: step.charCodeAt(0) });
          ta.dispatchEvent(kp);
        }
        key("keyup", step, step.toUpperCase().charCodeAt(0));
      }
      await new Promise((r) => setTimeout(r, 4));
    }
  }, steps);
}

export const S = {
  안: ["ㅇ", "아", "안", "안"],
  녕: ["ㄴ", "녀", "녕", "녕"],
  하: ["ㅎ", "하", "핫", "하"],
  세: ["세", "셍", "세"],
  요: ["요", "요"],
  한: ["ㅎ", "하", "한", "한"],
  글: ["ㄱ", "그", "글"],
  입: ["ㅇ", "이", "입", "입"],
  력: ["ㄹ", "려", "력"],
};
