// Attaching files in the composer: the + button (one file picker), the chips row, the drop overlay on the chat,
// and the files in the person's own sent bubble. Sending lives in the store (`sendWithFiles`).
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { OutFile, SentFile } from "../../state/store";
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

/** The + at the composer's left edge: one file picker for every kind of file (pictures, videos, documents).
 *  Pasting into the box and dropping on the chat add files the same way; there is no separate menu. */
export function AttachButton({ disabled, onFiles }: { disabled: boolean; onFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null);

  // ⌘O (Ctrl+O on Windows/Linux) opens the same picker while this chat is open.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const m = isMac() ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
      if (!m || e.altKey || e.shiftKey || disabled || e.key.toLowerCase() !== "o") return;
      e.preventDefault();
      input.current?.click();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [disabled]);

  const picked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = [...(e.target.files ?? [])];
    e.target.value = "";
    if (files.length) onFiles(files);
  };

  return (
    <div className="att-wrap">
      <button
        type="button"
        className="att-plus"
        aria-label={t("att.attach")}
        title={`${t("att.attach")} (${isMac() ? "⌘" : "Ctrl+"}O)`}
        disabled={disabled}
        onClick={() => input.current?.click()}
        data-testid="attach"
      >
        <PlusIcon size={14} />
      </button>
      <input ref={input} type="file" multiple hidden onChange={picked} data-testid="attach-file-input" />
    </div>
  );
}

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
