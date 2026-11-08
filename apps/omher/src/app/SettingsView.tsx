import { useStore } from "../state/store";
import { slots } from "../features";
import { CloseIcon, IconButton } from "../ui";

/** Main column while `ui.view === "settings"`: a header plus the `settings` slot (or a plain note). */
export function SettingsView() {
  const s = useStore();
  const Settings = slots.settings;
  return (
    <>
      <header className="head" data-testid="header">
        <span className="head-title">Settings</span>
        <div className="head-right" data-testid="head-right">
          <IconButton label="Close settings" onClick={() => s.closeSettings()}>
            <CloseIcon />
          </IconButton>
        </div>
      </header>
      <div className="settings-body" data-testid="settings">
        {Settings ? (
          <Settings page={s.ui.settingsPage} onClose={() => s.closeSettings()} />
        ) : (
          <p className="plain-note">Settings are not available in this build.</p>
        )}
      </div>
    </>
  );
}
