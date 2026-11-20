// Settings › Terminal › Import from… (macOS only): the colours and font of an iTerm2 or Apple Terminal profile, as
// omher's own custom theme. The menu lists only the apps whose prefs file is there; picking one reads it once (the
// shell's term_import.rs: two fixed files, read-only), the profiles show with their swatches, the picked one shows in
// the page's preview, and Use keeps a copy. omher never writes to the other app and never reads it again by itself.
import { useState } from "react";
import { Popover } from "../../ui";
import { t, type Key } from "../../i18n";
import { getHost } from "../../sessions/host";
import { fontInstalled, importPatch, profileFont, profileTheme, type ImportApp, type ImportFont, type ImportProfile } from "../../sessions/term/import";
import { writeTermSettings, type TermSettings } from "../../sessions/term/settings";
import { ANSI_NORMAL, customTermTheme, type TermTheme } from "../../sessions/term/themes";

const APP: Record<ImportApp, Key> = { iterm2: "term.importIterm2", terminal: "term.importTerminal" };

/** What the preview shows while a profile is picked: its theme and the settings with its font (when it is here). */
export type ImportCandidate = { theme: TermTheme; settings: TermSettings } | null;

type Read = { app: ImportApp; profiles: ImportProfile[] } | { app: ImportApp; error: true };

function fontNote(f: ImportFont): string {
  if (!f) return t("term.importNoFont");
  if ("missing" in f) return t("term.importFontMissing", { font: f.missing });
  return t("term.importFont", { font: f.family, size: f.size });
}

export function TermImport({
  settings,
  slot,
  onCandidate,
  installed = fontInstalled,
}: {
  settings: TermSettings;
  slot: "dark" | "light";
  onCandidate: (c: ImportCandidate) => void;
  installed?: (family: string) => boolean;
}) {
  const [menu, setMenu] = useState<ImportApp[] | null>(null);
  const [read, setRead] = useState<Read | null>(null);
  const [pick, setPick] = useState(-1);
  const [done, setDone] = useState("");

  const close = () => {
    setRead(null);
    setPick(-1);
    onCandidate(null);
  };
  const openMenu = async () => {
    setDone("");
    if (menu) return setMenu(null);
    try {
      setMenu(await getHost().termImportList());
    } catch {
      setMenu([]);
    }
  };
  const choose = async (app: ImportApp) => {
    setMenu(null);
    close();
    try {
      const profiles = await getHost().termImportRead(app);
      setRead({ app, profiles });
      const first = profiles.findIndex((p) => p.ok);
      if (first >= 0) select(profiles, first);
    } catch {
      setRead({ app, error: true });
    }
  };
  const select = (profiles: ImportProfile[], i: number) => {
    const p = profiles[i];
    const theme = p && profileTheme(p);
    if (!theme) return;
    setPick(i);
    const font = profileFont(p, installed);
    const s = { ...settings, ...importPatch(theme, font, slot) } as TermSettings;
    onCandidate({ theme: customTermTheme(theme), settings: s });
  };

  const profiles = read && "profiles" in read ? read.profiles : [];
  const picked = pick >= 0 ? profiles[pick] : undefined;
  const pickedTheme = picked ? profileTheme(picked) : null;
  const pickedFont = picked ? profileFont(picked, installed) : null;

  const use = () => {
    if (!picked || !pickedTheme) return;
    writeTermSettings(importPatch(pickedTheme, pickedFont, slot));
    setDone(t("term.importDone", { name: pickedTheme.name }));
    close();
  };

  return (
    <>
      <div className="tm-imp-at">
        <button type="button" className="st-btn tm-imp-btn" aria-haspopup="menu" aria-expanded={!!menu} onClick={() => void openMenu()} data-testid="term-import">
          {t("term.import")}
        </button>
        <Popover open={!!menu} onClose={() => setMenu(null)} align="right" width={220} label={t("term.importMenu")} className="pv-menu">
          <div className="pv-menu-h">{t("term.importMenu")}</div>
          {menu && menu.length === 0 && (
            <div className="tm-imp-none" data-testid="term-import-none">
              {t("term.importNone")}
            </div>
          )}
          <div role="menu" data-testid="term-import-menu">
            {menu?.map((app) => (
              <button key={app} type="button" role="menuitem" className="pv-menu-i" onClick={() => void choose(app)} data-testid={`term-import-${app}`}>
                {t(APP[app])}
              </button>
            ))}
          </div>
        </Popover>
      </div>
      {done && !read && (
        <div className="tm-imp-done" role="status" data-testid="term-import-done">
          {done}
        </div>
      )}
      {read && (
        <div className="tm-imp" data-testid="term-import-panel">
          <div className="tm-imp-h">
            <b>{t("term.importFrom", { app: t(APP[read.app]) })}</b>
            <span>{t("term.importHint")}</span>
          </div>
          {"error" in read ? (
            <div className="tm-none" data-testid="term-import-error">
              {t("term.importFailed", { app: t(APP[read.app]) })}
            </div>
          ) : profiles.length === 0 ? (
            <div className="tm-none" data-testid="term-import-empty">
              {t("term.importEmpty", { app: t(APP[read.app]) })}
            </div>
          ) : (
            <div className="tm-imp-list" role="radiogroup" aria-label={t("term.importFrom", { app: t(APP[read.app]) })} data-testid="term-import-profiles">
              {profiles.map((p, i) => {
                const th = profileTheme(p);
                const c = th ? customTermTheme(th).theme : null;
                return (
                  <button
                    key={`${i}-${p.name}`}
                    type="button"
                    role="radio"
                    aria-checked={i === pick}
                    aria-disabled={!th}
                    className={`tm-row${i === pick ? " on" : ""}${th ? "" : " off"}`}
                    onClick={() => select(profiles, i)}
                    title={th ? p.name : t("term.importBroken")}
                    data-testid={`term-import-profile-${i}`}
                  >
                    {c ? (
                      <span className="tm-sw" aria-hidden="true" style={{ background: c.background, color: c.foreground }}>
                        {ANSI_NORMAL.map((k) => (
                          <i key={k} style={{ background: c[k] }} />
                        ))}
                      </span>
                    ) : (
                      <span className="tm-sw tm-sw-none" aria-hidden="true" />
                    )}
                    <span className="tm-name">{p.name}</span>
                    {p.default && <span className="tm-imp-tag">{t("term.importDefault")}</span>}
                    {!th && <span className="tm-imp-tag">{t("term.importBroken")}</span>}
                  </button>
                );
              })}
            </div>
          )}
          <div className="tm-imp-foot">
            <span className="tm-imp-font" data-testid="term-import-font">
              {picked ? fontNote(pickedFont) : ""}
            </span>
            <button type="button" className="st-btn" onClick={close} data-testid="term-import-cancel">
              {t("term.importCancel")}
            </button>
            <button type="button" className="st-btn tm-imp-use" disabled={!pickedTheme} onClick={use} data-testid="term-import-use">
              {t("term.importUse")}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
