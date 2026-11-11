import { useStore } from "../state/store";
import { t } from "../i18n";
import { slots } from "../features";
import { CloseIcon, IconButton } from "../ui";

/** Main column while `ui.view === "settings"`: a header plus the `settings` slot (or a plain note). */
export function SettingsView() {
  const s = useStore();
  const Settings = slots.settings;
  return (
    <>
      <header className="head" data-testid="header">
        <span className="head-title">{t("set.title")}</span>
        <div className="head-right" data-testid="head-right">
          <IconButton label={t("set.close")} onClick={() => s.closeSettings()}>
            <CloseIcon />
          </IconButton>
        </div>
      </header>
      <div className="settings-body" data-testid="settings">
        {Settings ? (
          <Settings page={s.ui.settingsPage} onClose={() => s.closeSettings()} />
        ) : (
          <p className="plain-note">{t("set.unavailable")}</p>
        )}
      </div>
    </>
  );
}
