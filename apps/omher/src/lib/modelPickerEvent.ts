// `/model` typed in a bot's chat opens the header's model picker instead of going to the bot as a message, during a
// turn too, as Claude Code's `/model` does: a pick made while a turn runs is Hermes' deferred switch, from the next
// turn (the picker says so). The store sends this event; the picker (chat/model/ModelPicker.slot.tsx) listens.

export const OPEN_MODEL_PICKER = "omher:open-model-picker";

/** Ask the model picker of `bot`'s chat to open. */
export function openModelPicker(bot: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<string>(OPEN_MODEL_PICKER, { detail: bot }));
}
