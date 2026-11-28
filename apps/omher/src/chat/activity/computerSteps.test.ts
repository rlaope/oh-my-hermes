import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../../i18n";
import { activityText } from "../../state/store";
import { computerLine } from "./computerSteps";

describe("a computer_use step", () => {
  afterEach(() => setLang("en"));

  it("reads as its action in the app", () => {
    expect(computerLine("click", "Safari", false)).toBe("Clicked in Safari");
    expect(computerLine("double_click", "Safari", true)).toBe("Clicking in Safari");
    expect(computerLine("capture", "", false)).toBe("Looked at the screen");
    expect(computerLine("type", "Notes", false)).toBe("Typed in Notes");
    expect(computerLine("set_value", "Notes", true)).toBe("Typing in Notes");
    expect(computerLine("focus_app", "Mail", false)).toBe("Switched to Mail");
    expect(computerLine("focus_app", "", true)).toBe("Switching apps");
    // the app adds nothing to these
    expect(computerLine("list_apps", "Finder", false)).toBe("Checked the open apps");
    expect(computerLine("wait", "Finder", true)).toBe("Waiting");
    // an action Hermes does not have, or none
    expect(computerLine("launch", "Safari", false)).toBe("Used the computer in Safari");
    expect(computerLine(undefined, "", true)).toBe("Using the computer");
    // Hermes' whole-screen targets are not apps
    expect(computerLine("capture", "screen", false)).toBe("Looked at the screen");
    expect(computerLine("click", "Desktop", true)).toBe("Clicking");
  });

  it("is the running line too, in the current language", () => {
    expect(activityText("computer_use", "Safari", "click")).toBe("Clicking in Safari");
    setLang("ko");
    expect(activityText("computer_use", "Safari", "click")).toBe("Safari에서 클릭 중");
    expect(computerLine("capture", "", false)).toBe("화면 확인");
    setLang("zh");
    expect(computerLine("type", "Notes", false)).toBe("输入（Notes）");
  });
});
