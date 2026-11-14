// Attaching files in the composer: the + button (one file picker, plus the bot's plugins in its chat), the chips row, the drop overlay on the chat,
// and the files in the person's own sent bubble. Sending lives in the store (`sendWithFiles`).
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { OutFile, SentFile } from "../../state/store";
import type { PluginRow } from "../../lib/protocol";
import { PlugIcon } from "../../pages/icons";
import { isMac } from "../../app/shortcuts";
import { PlusIcon } from "../../ui";
import { attachKind, badgeFor, limitReason, previewKind } from "./attachFiles";
import { fileSize } from "./mediaLines";
import { FileRow, gridOf, ImageTile } from "./Media";
import { t } from "../../i18n";

export interface Chip extends OutFile {
  id: string;
  /** Why it will not be sent (red chip), or null. */
  reason: string | null;
}

let chipSeq = 0;

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).replace(/^data:[^,]*,/, ""));
    r.onerror = () => reject(r.error ?? new Error(t("att.readFailed")));
    r.readAsDataURL(file);
  });
}

/** New chips for `files`, after the `have` already there (limits count from that position). */
export function chipsFor(files: File[], have: number): Chip[] {
  return files.map((f, i) => {
    const kind = previewKind(f.name, f.type);
    const reason = limitReason(f.size, have + i);
    return {
      id: `chip-${++chipSeq}`,
      name: f.name || "pasted",
      size: f.size,
      kind,
      attach: attachKind(f.name, f.type),
      url: !reason && kind !== "file" ? URL.createObjectURL(f) : null,
      read: () => readBase64(f),
      reason,
    };
  });
}

const mod = () => (isMac() ? "⌘" : "Ctrl+");

/** The + at the composer's left edge. In a bot's chat it opens a two-row menu: "Add photos and files" (one picker
 *  for every kind of file) and "Plugins ›", whose submenu beside it lists the bot's enabled plugins (a colour tile and
 *  the name; the description is the tooltip) and Manage plugins. Picking a plugin names it at the start of the
 *  message. Where there are no plugins (a SESSIONS agent) the + opens the picker straight away. Pasting into the box
 *  and dropping on the chat add files too. */
export function AttachButton({
  disabled,
  onFiles,
  plugins,
  onPlugin,
  onManage,
}: {
  disabled: boolean;
  onFiles: (files: File[]) => void;
  /** Reads the bot's plugins when the menu opens (a bot's chat only). */
  plugins?: () => Promise<PluginRow[]>;
  onPlugin?: (p: PluginRow) => void;
  onManage?: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [sub, setSub] = useState(false);
  const [rows, setRows] = useState<PluginRow[] | null>(null);
  useEffect(() => {
    if (!open) setSub(false);
  }, [open]);
  // → or Enter on "Plugins ›": the first row of the submenu takes the focus once the plugins have been read
  const focusSub = useRef(false);
  useEffect(() => {
    if (!sub || rows === null || !focusSub.current) return;
    focusSub.current = false;
    wrap.current?.querySelector<HTMLButtonElement>(".att-sub .att-row")?.focus();
  }, [sub, rows]);

  // ⌘O (Ctrl+O on Windows/Linux) opens the picker while this chat is open.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const m = isMac() ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
      if (!m || e.altKey || e.shiftKey || disabled || e.key.toLowerCase() !== "o") return;
      e.preventDefault();
      setOpen(false);
      input.current?.click();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [disabled]);

  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  useEffect(() => {
    if (!open || !plugins) return;
    let live = true;
    plugins().then(
      (list) => live && setRows(list.filter((p) => p.enabled)),
      () => live && setRows([]),
    );
    return () => {
      live = false;
    };
  }, [open, plugins]);

  const picked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = [...(e.target.files ?? [])];
    e.target.value = "";
    if (files.length) onFiles(files);
  };
  const pickFiles = () => {
    setOpen(false);
    input.current?.click();
  };

  return (
    <div className="att-wrap" ref={wrap}>
      <button
        type="button"
        className="att-plus"
        aria-label={t("att.attach")}
        title={t("att.attach")}
        aria-haspopup={plugins ? "menu" : undefined}
        aria-expanded={plugins ? open : undefined}
        disabled={disabled}
        onClick={() => (plugins ? setOpen((o) => !o) : input.current?.click())}
        data-testid="attach"
      >
        <PlusIcon size={14} />
      </button>
      <input ref={input} type="file" multiple hidden onChange={picked} data-testid="attach-file-input" />
      {open && (
        <div className="att-menu" role="menu" data-testid="attach-menu">
          <button type="button" role="menuitem" className="att-row" onClick={pickFiles} onMouseEnter={() => setSub(false)} data-testid="attach-files">
            <span className="att-ic">
              <ClipIcon />
            </span>
            <span className="att-n">{t("att.addFiles")}</span>
            <kbd>{mod()}O</kbd>
          </button>
          <button
            type="button"
            role="menuitem"
            className={`att-row att-more${sub ? " on" : ""}`}
            aria-haspopup="menu"
            aria-expanded={sub}
            onMouseEnter={() => setSub(true)}
            onClick={() => setSub(true)}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight" || e.key === "Enter") {
                e.preventDefault();
                focusSub.current = true;
                setSub(true);
              }
            }}
            data-testid="attach-plugins"
          >
            <span className="att-ic">
              <PlugIcon size={15} />
            </span>
            <span className="att-n">{t("att.plugins")}</span>
            <span className="att-chev" aria-hidden="true">
              ›
            </span>
          </button>
          {sub && (
            <div
              className="att-sub"
              role="menu"
              onKeyDown={(e) => {
                if (e.key === "ArrowLeft") {
                  e.preventDefault();
                  setSub(false);
                  wrap.current?.querySelector<HTMLButtonElement>("[data-testid=attach-plugins]")?.focus();
                }
              }}
              data-testid="attach-sub"
            >
              {rows === null ? (
                <div className="att-empty">{t("att.pluginsLoading")}</div>
              ) : (
                rows.map((p) => (
                  <button
                    key={p.key}
                    type="button"
                    role="menuitem"
                    className="att-row"
                    title={p.description || pluginName(p)}
                    onClick={() => {
                      setOpen(false);
                      onPlugin?.(p);
                    }}
                    data-testid="attach-plugin"
                    data-name={p.name}
                  >
                    <PluginTile p={p} />
                    <span className="att-n">{pluginName(p)}</span>
                  </button>
                ))
              )}
              {!!rows?.length && <div className="att-sep" />}
              <button
                type="button"
                role="menuitem"
                className="att-row att-manage"
                onClick={() => {
                  setOpen(false);
                  onManage?.();
                }}
                data-testid="attach-manage"
              >
                <span className="att-ic">
                  <GearIcon />
                </span>
                <span className="att-n">{rows && !rows.length ? t("att.pluginsNone") : t("att.pluginsManage")}</span>
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** A plugin's name for people: the catalog title, else its folder name with the dashes spaced and a capital. */
export function pluginName(p: Pick<PluginRow, "title" | "name">): string {
  if (p.title) return p.title;
  const n = p.name.replace(/[-_]+/g, " ").trim();
  return n ? n[0].toUpperCase() + n.slice(1) : p.name;
}

/** A colour per plugin, the same every time: the logo's violet, coral, amber and pink with green, teal, blue and indigo
 *  between them, so neighbouring hues differ. */
const TILE = ["#b83fa8", "#e0595e", "#c98a2b", "#6f9a2e", "#2fa37a", "#2a8fc4", "#7c5cff", "#d33c8d"];
export function tileColor(name: string): string {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return TILE[h % TILE.length];
}

function PluginTile({ p }: { p: PluginRow }) {
  return (
    <span className="att-tile" style={{ background: tileColor(p.name) }} aria-hidden="true">
      {pluginName(p).charAt(0).toUpperCase()}
    </span>
  );
}

const GearIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
  </svg>
);

const ClipIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M20 11.5 12.4 19a5 5 0 0 1-7.1-7.1l7.6-7.6a3.3 3.3 0 0 1 4.7 4.7l-7.6 7.6a1.7 1.7 0 0 1-2.4-2.4l7-7" />
  </svg>
);

/** The chips row above the input. */
export function Chips({ chips, onRemove }: { chips: Chip[]; onRemove: (id: string) => void }) {
  if (!chips.length) return null;
  return (
    <div className="att-chips" data-testid="attach-chips">
      {chips.map((c) => (
        <div
          key={c.id}
          className={`att-chip${c.reason ? " bad" : ""}`}
          data-testid="attach-chip"
          data-name={c.name}
          title={c.reason ? `${c.name} · ${c.reason}` : c.name}
        >
          <Thumb chip={c} />
          <span className="att-name">{c.name}</span>
          <span className="att-size" data-testid="attach-chip-note">
            {c.reason ?? fileSize(c.size)}
          </span>
          <button type="button" className="att-x" aria-label={t("att.removeOf", { name: c.name })} onClick={() => onRemove(c.id)} data-testid="attach-remove">
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

function Thumb({ chip }: { chip: Chip }) {
  if (chip.url && chip.kind === "image") return <img className="att-thumb" src={chip.url} alt="" />;
  if (chip.url && chip.kind === "video")
    return (
      <span className="att-thumb att-vid">
        <video src={chip.url} muted playsInline preload="metadata" />
        <span className="att-play">▶</span>
      </span>
    );
  return <span className="att-thumb att-badge">{badgeFor(chip.name)}</span>;
}

/** Dragging files over the chat area shows a dashed "Drop to attach" overlay; dropping adds chips. */
export function useDropZone(anchor: React.RefObject<HTMLElement | null>, enabled: boolean, onFiles: (f: File[]) => void) {
  const [zone, setZone] = useState<HTMLElement | null>(null);
  const [over, setOver] = useState(false);
  const cb = useRef(onFiles);
  cb.current = onFiles;
  useEffect(() => {
    const pane = anchor.current?.closest<HTMLElement>(".pane") ?? null;
    setZone(pane);
    if (!pane || !enabled) return;
    let depth = 0;
    const hasFiles = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes("Files");
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth += 1;
      setOver(true);
    };
    const overFn = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (!depth) setOver(false);
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      setOver(false);
      const files = [...(e.dataTransfer?.files ?? [])];
      if (files.length) cb.current(files);
    };
    pane.addEventListener("dragenter", enter);
    pane.addEventListener("dragover", overFn);
    pane.addEventListener("dragleave", leave);
    pane.addEventListener("drop", drop);
    return () => {
      pane.removeEventListener("dragenter", enter);
      pane.removeEventListener("dragover", overFn);
      pane.removeEventListener("dragleave", leave);
      pane.removeEventListener("drop", drop);
    };
  }, [anchor, enabled]);
  return over && zone
    ? createPortal(
        <div className="att-drop" data-testid="attach-drop">
          <span>{t("att.drop")}</span>
        </div>,
        zone,
      )
    : null;
}

/** Files in the person's own bubble, from the local copies made when they were picked. */
export function SentFiles({ files }: { files: SentFile[] }) {
  return (
    <div className="media att-sent" data-testid="sent-files" data-grid={gridOf(files.map((f) => (f.url ? f.kind : "file")))}>
      {files.map((f, i) =>
        f.url && f.kind === "image" ? (
          <ImageTile key={i} url={f.url} name={f.name} />
        ) : f.url && f.kind === "video" ? (
          <video key={i} className="media-video" src={f.url} controls preload="metadata" />
        ) : (
          <FileRow key={i} name={f.name} size={f.size} title={f.name} testId="sent-file" />
        ),
      )}
    </div>
  );
}
