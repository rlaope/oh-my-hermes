import { useEffect, useState, type WheelEvent } from "react";
import { createPortal } from "react-dom";
import type { MediaFile } from "../../lib/protocol";
import { canOpenFiles, openMedia, revealLabel } from "../../lib/openMedia";
import { useStore } from "../../state/store";
import { extOf, fileName, fileSize, mediaKind, type MediaKind } from "./mediaLines";
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

/** Files the bot sent (`MEDIA:` lines), shown under its answer in order. */
export function MediaList({ bot, paths }: { bot: string; paths: string[] }) {
  return (
    <div className="media" data-testid="media">
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

function FileCard({ file }: { file: MediaFile }) {
  const ext = extOf(file.name);
  return (
    <div className="media-file" data-testid="media-file" title={file.path}>
      <span className="media-ext">{(ext || "file").slice(0, 4).toUpperCase()}</span>
      <div className="media-meta">
        <span className="media-name" data-testid="media-file-name">
          {file.name}
        </span>
        <span className="media-size" data-testid="media-file-size">
          {fileSize(file.size)}
        </span>
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
      </div>
    </div>
  );
}
