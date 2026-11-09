// Header right: the ONE control. `● <Model> | <Reasoning> ⌄` opens a popover with the providers' models
// and a reasoning control. Changes go to `chat.set_model` for the bot's main chat; when the bridge refuses
// (e.g. `unsupported`) the old value stays and a one-line note says to change it in Hermes.
import { useEffect, useState } from "react";
import "./model.css";
import type { SlotProps } from "../../features";
import { getStore, useStore } from "../../state/store";
import { ChevronDown, ModelIcon, Popover } from "../../ui";
import { Seg } from "./Seg";
import { CheckIcon } from "./CheckIcon";
import { levelOptions, reasoningLabel } from "./levels";

export const slot = "modelPicker";

type Change = { model?: string; provider?: string; reasoning?: string };

export default function ModelPicker({ bot, chat }: SlotProps["modelPicker"]) {
  const s = useStore();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const opts = s.models[bot.name];
  const model = chat?.model || opts?.current.model || bot.model;
  const provider = chat?.provider || opts?.current.provider || bot.provider;
  const reasoning = chat?.reasoning || opts?.current.reasoning || "";
  const offline = bot.status === "offline";

  useEffect(() => {
    setOpen(false);
    setNote(null);
  }, [bot.name]);
  useEffect(() => {
    if (open && !opts && !offline) void s.loadModels(bot.name);
    // load once per opening
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, bot.name]);

  const apply = async (change: Change) => {
    const store = getStore();
    setBusy(true);
    setNote(null);
    // The store reports a failed request only through lastError: clear it, then look after the call.
    store.dispatch({ type: "error", message: null });
    await s.setModel(change);
    const after = store.getState();
    const c = after.chats[bot.name];
    const got: Change = { model: c?.model, provider: c?.provider, reasoning: c?.reasoning };
    const applied = (Object.keys(change) as (keyof Change)[]).every((k) => got[k] === change[k]);
    if (!applied && after.lastError !== null) setNote(after.lastError);
    setBusy(false);
  };

  return (
    <div className="mp-wrap">
      <button
        type="button"
        className={`mp${open ? " on" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Model and reasoning"
        data-testid="model-pill"
      >
        <span className="mp-mk" title={offline ? "Not connected" : "Connected"}>
          <ModelIcon model={model} provider={provider} size={14} />
          <span className={`mp-d${offline ? "" : " live"}`} aria-hidden="true" />
        </span>
        <span data-testid="model-label" title={model}>
          {model}
        </span>
        {reasoning && (
          <>
            <span className="sep" />
            <span className="eff" data-testid="reasoning-label">
              {reasoningLabel(reasoning)}
            </span>
          </>
        )}
        <ChevronDown />
      </button>
      <Popover open={open} onClose={() => setOpen(false)} label="Model and reasoning" width={256} className="mp-pop">
        <div data-testid="model-pop" aria-busy={busy}>
          <div className="mp-h">Model</div>
          <div className="mp-list">
            {!opts ? (
              <div className="mp-empty">{offline ? `${bot.display_name} is offline` : "Loading models…"}</div>
            ) : (
              opts.providers
                .filter((p) => p.models.length)
                .map((p) => (
                  <div key={p.slug} role="group" aria-label={p.name}>
                    <div className="mp-g">{p.name}</div>
                    {p.models.map((m) => {
                      const on = m === model && p.slug === provider;
                      return (
                        <button
                          key={m}
                          type="button"
                          className={`mp-opt${on ? " on" : ""}`}
                          aria-pressed={on}
                          disabled={busy}
                          onClick={() => !on && void apply({ model: m, provider: p.slug })}
                          data-testid="model-opt"
                        >
                          <ModelIcon model={m} provider={`${p.slug} ${p.name}`} size={13} />
                          <span className="mp-n">{m}</span>
                          <span className="mp-ck">
                            <CheckIcon />
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ))
            )}
          </div>
          <div className="mp-h mp-h2">Reasoning</div>
          <Seg
            label="Reasoning"
            value={reasoning}
            options={levelOptions(opts?.reasoning_levels)}
            onChange={(r) => void apply({ reasoning: r })}
            disabled={busy || offline}
            testId="reasoning-seg"
          />
          {note !== null && (
            <div className="mp-note" role="status" title={note || undefined} data-testid="model-note">
              Change it in Hermes for now
            </div>
          )}
          <div className="mp-f">
            Applies to this chat ·{" "}
            <button
              type="button"
              className="mp-link"
              onClick={() => {
                setOpen(false);
                s.openSettings(`bot:${bot.name}`);
              }}
            >
              Bot settings
            </button>
          </div>
        </div>
      </Popover>
    </div>
  );
}
