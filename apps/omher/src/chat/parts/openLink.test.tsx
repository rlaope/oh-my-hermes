import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Markdown } from "./Markdown";
import { openLink } from "./LinkChip";
import { getStore } from "../../state/store";
import { t } from "../../i18n";

describe("an upper-case scheme in a bot reply", () => {
  it("renders as a link chip and opens as the lower-case address", async () => {
    expect(renderToStaticMarkup(<Markdown text="see HTTPS://Example.com/Path now" />)).toContain("link-plain");
    const open = vi.fn(async () => {});
    await openLink("HTTPS://Example.com/Path", open);
    expect(open).toHaveBeenCalledWith("https://example.com/Path");
  });

  it("keeps the credentials rule's input intact: a user name is still in the href the opener refuses", async () => {
    const open = vi.fn(async () => {});
    await openLink("HTTPS://github.com@evil.io/", open);
    expect(open).toHaveBeenCalledWith("https://github.com@evil.io/");
  });

  it("surfaces a refused open on the app's error line", async () => {
    await openLink("https://example.com/", async () => {
      throw new Error("not a link omher opens");
    });
    expect(getStore().getState().lastError).toBe(t("lk.openFailed", { error: "not a link omher opens" }));
  });
});
