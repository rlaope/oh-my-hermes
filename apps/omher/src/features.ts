// Slot registry. Feature folders plug into the shell by adding a `<folder>/<name>.slot.tsx` file:
//
//   import type { SlotProps } from "../features";           // path relative to your file
//   export const slot = "activity";                           // one SlotName
//   export default function Activity(props: SlotProps["activity"]) { … }
//
// The shell renders a slot only when one is registered, else a plain fallback. Nobody edits this
// file after the shell node: add a slot file instead. Slot components may also call useStore().
import type { ComponentType } from "react";
import type { Bot } from "./lib/protocol";
import type { ActivityItem, ApprovalItem, AwayItem, Chat, ClarifyItem, RoutineItem } from "./state/store";

export type SlotName =
  | "activity"
  | "cards"
  | "elsewhereLine"
  | "detailsPanel"
  | "headerPlaces"
  | "modelPicker"
  | "settings"
  | "addBot"
  | "routineLine";

/** Timeline: the one activity line of a turn. `live` = this is the running turn (`chat.turn`). */
export interface ActivitySlotProps {
  bot: string;
  item: ActivityItem;
  live: boolean;
}
/** Timeline: an approval or clarify request (switch on `item.kind`). */
export interface CardsSlotProps {
  bot: string;
  item: ApprovalItem | ClarifyItem;
}
/** Timeline: one read-only line for a session of the bot elsewhere (Slack, Discord…). */
export interface ElsewhereLineSlotProps {
  bot: string;
  item: AwayItem;
  /** false: a bot bubble is right above, so keep the indent without repeating the face. */
  face?: boolean;
}
/** Timeline: one line for a `routine.ran` row. */
export interface RoutineLineSlotProps {
  bot: string;
  item: RoutineItem;
}
/** Right column (300px when `ui.panelOpen`). Always mounted while a bot is selected; the column animates. */
export interface DetailsPanelSlotProps {
  bot: Bot;
  open: boolean;
  onClose: () => void;
}
/** Header, right after the bot name ("3 other places" chip). Click should call `togglePanel()`. */
export interface HeaderPlacesSlotProps {
  bot: Bot;
}
/** Header right: the ONE control (model | reasoning pill + popover). Render a single root element. */
export interface ModelPickerSlotProps {
  bot: Bot;
  /** The bot's main chat (model/provider/reasoning come from `chat.open` and `chat.set_model`). */
  chat: Chat | undefined;
}
/** Main column when `ui.view === "settings"`, below the "Settings" header. */
export interface SettingsSlotProps {
  page: string;
  onClose: () => void;
}
/** Popover from the sidebar `+`. Rendered only while open, inside a `position: relative` wrapper. */
export interface AddBotSlotProps {
  onClose: () => void;
  /** Connect over SSH was picked: the popover closes and the sidebar opens the confirm card (it outlives the popover). */
  onSsh?: () => void;
}

export interface SlotProps {
  activity: ActivitySlotProps;
  cards: CardsSlotProps;
  elsewhereLine: ElsewhereLineSlotProps;
  detailsPanel: DetailsPanelSlotProps;
  headerPlaces: HeaderPlacesSlotProps;
  modelPicker: ModelPickerSlotProps;
  settings: SettingsSlotProps;
  addBot: AddBotSlotProps;
  routineLine: RoutineLineSlotProps;
}

export type Slots = { [K in SlotName]?: ComponentType<SlotProps[K]> };

const SLOT_NAMES: readonly SlotName[] = [
  "activity",
  "cards",
  "elsewhereLine",
  "detailsPanel",
  "headerPlaces",
  "modelPicker",
  "settings",
  "addBot",
  "routineLine",
];

interface SlotModule {
  slot?: unknown;
  default?: unknown;
}

/** Builds the registry from `{ path: module }`. Unknown names and missing defaults are skipped with a warning. */
export function collectSlots(modules: Record<string, SlotModule>): Slots {
  const out: Record<string, unknown> = {};
  for (const path of Object.keys(modules).sort()) {
    const m = modules[path];
    const name = m.slot as SlotName;
    if (!SLOT_NAMES.includes(name) || typeof m.default !== "function") {
      console.warn(`[omher] ${path}: needs \`export const slot: SlotName\` and a default component`);
      continue;
    }
    if (out[name]) console.warn(`[omher] slot "${name}" registered twice; ${path} wins`);
    out[name] = m.default;
  }
  return out as Slots;
}

export const slots: Slots = collectSlots(
  import.meta.glob<SlotModule>("./**/*.slot.tsx", { eager: true }),
);
