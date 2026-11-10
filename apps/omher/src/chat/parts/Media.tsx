import { useEffect, useState, type ReactNode, type WheelEvent } from "react";
import { createPortal } from "react-dom";
import type { MediaFile } from "../../lib/protocol";
import { canOpenFiles, openMedia, revealLabel } from "../../lib/openMedia";
import { useStore } from "../../state/store";
import { fileName, fileSize, mediaKind, type MediaKind } from "./mediaLines";
import "./media.css";

type Loaded =
  | { state: "loading" }
  | { state: "error" }
  | { state: "ready"; file: MediaFile; url: string | null };

/** Reads one file through `media.read`: bytes as a blob URL for images, video and audio; name and size
 * only for a file card. The blob URL is dropped when the tile goes away. */
function useMedia(bot: string, path: string, kind: MediaKind): Loaded {
  const { readMedia } = useStore();
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  useEffect(() => {
    let alive = true;
    let url: string | null = null;
    setLoaded({ state: "loading" });
    readMedia(bot, path, kind === "file")
      .then(async (file) => {
        if (file.data_base64 && !file.too_big) {
          const blob = await (await fetch(`data:${file.mime};base64,${file.data_base64}`)).blob();
          url = URL.createObjectURL(blob);
        }
        if (alive) setLoaded({ state: "ready", file, url });
        else if (url) URL.revokeObjectURL(url);
      })
      .catch(() => alive && setLoaded({ state: "error" }));
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [bot, path, kind, readMedia]);
  return loaded;
}

/** How a set of files lays out: one picture keeps its own shape (up to 420px); two or more pictures go in a
 *  grid of at most 2 per row. A video, an audio player and a file row always take a whole row. */
export const gridOf = (kinds: MediaKind[]) => (kinds.filter((k) => k === "image").length > 1 ? 2 : 1);

/** Files the bot sent (`MEDIA:` lines), shown under its answer in order, in the bubble's column. */
export function MediaList({ bot, paths }: { bot: string; paths: string[] }) {
  return (
    <div className="media" data-testid="media" data-grid={gridOf(paths.map(mediaKind))}>
      {paths.map((p, i) => (
        <MediaItem key={`${i}:${p}`} bot={bot} path={p} />
      ))}
    </div>
  );
}

function MediaItem({ bot, path }: { bot: string; path: string }) {
  const kind = mediaKind(path);
  const m = useMedia(bot, path, kind);
  if (m.state === "loading") return <div className={`media-skel media-skel-${kind}`} data-testid="media-loading" aria-label="Loading file" />;
  if (m.state === "error")
    return (
      <div className="media-err" data-testid="media-error" title={path}>
        Couldn't load file <span>· {fileName(path)}</span>
      </div>
    );
  const { file, url } = m;
  if (url && kind === "image") return <ImageTile url={url} name={file.name} />;
  if (url && kind === "video")
    return <video className="media-video" data-testid="media-video" src={url} controls preload="metadata" />;
  if (url && kind === "audio") return <audio className="media-audio" data-testid="media-audio" src={url} controls />;
  return <FileCard file={file} />;
}

export function ImageTile({ url, name }: { url: string; name: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="media-img" data-testid="media-image" onClick={() => setOpen(true)} aria-label={`Open ${name}`}>
        <img src={url} alt={name} draggable={false} />
      </button>
      {open && <Lightbox url={url} name={name} onClose={() => setOpen(false)} />}
    </>
  );
}

function Lightbox({ url, name, onClose }: { url: string; name: string; onClose: () => void }) {
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  const onWheel = (e: WheelEvent) => setZoom((z) => Math.min(4, Math.max(1, z * (e.deltaY < 0 ? 1.1 : 1 / 1.1))));
  // On <body>: the thread is masked and scrolls, which would clip a fixed overlay inside it.
  return createPortal(
    <div className="media-lightbox" data-testid="lightbox" role="dialog" aria-label={name} onClick={onClose} onWheel={onWheel}>
      <img src={url} alt={name} style={{ transform: `scale(${zoom})` }} draggable={false} />
    </div>,
    document.body,
  );
}

const FileIcon = () => (
  <svg className="media-ic" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5" />
  </svg>
);

/** One compact row for a file that is not a picture: icon, name, size, then its actions (`children`). */
export function FileRow({ name, size, title, testId, children }: { name: string; size: number; title: string; testId: string; children?: ReactNode }) {
  return (
    <div className="media-file" data-testid={testId} title={title}>
      <FileIcon />
      <span className="media-name" data-testid="media-file-name">
        {name}
      </span>
      <span className="media-size" data-testid="media-file-size">
        {fileSize(size)}
      </span>
      {children}
    </div>
  );
}

function FileCard({ file }: { file: MediaFile }) {
  return (
    <FileRow name={file.name} size={file.size} title={file.path} testId="media-file">
      <span className="media-acts">
        <button type="button" data-testid="media-open" onClick={() => void openMedia(file.path).catch(() => {})}>
          Open
        </button>
        {canOpenFiles() && (
          <button type="button" data-testid="media-reveal" onClick={() => void openMedia(file.path, true).catch(() => {})}>
            {revealLabel()}
          </button>
        )}
      </span>
    </FileRow>
  );
}
