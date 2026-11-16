import { useStore } from "../state/store";
import { t } from "../i18n";
import { ArrowLeft, IconButton } from "../ui";

/** Top left of Settings, Automations and Plugins: back to the chat (or session) the page was opened from. */
export function PageBack() {
  const s = useStore();
  return (
    <IconButton label={t("page.back")} className="head-back" onClick={() => s.closeSettings()} data-testid="page-back">
      <ArrowLeft />
    </IconButton>
  );
}
