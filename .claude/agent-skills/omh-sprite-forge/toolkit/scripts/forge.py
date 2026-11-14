#!/usr/bin/env python3
"""Original OMH optional sprite-sheet processing helper; MIT, copyright 2026 OMH contributors."""
from __future__ import annotations

import argparse
from array import array
from datetime import datetime, timezone
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import re
import statistics
import sys
import tempfile

# Module constants so tests can lower them (patch.object) instead of
# synthesizing giant sheets.
MAX_SIDE_PX = 8192
MAX_FILE_BYTES = 64 * 1024 * 1024

DEFAULT_KEY = "FF00FF"
DEFAULT_TOLERANCE = 30
ALPHA_OPAQUE_THRESHOLD = 128
SMALL_COMPONENT_FRACTION = 0.05
THRESHOLDS = {"body_scale_cv": 0.08, "anchor_y_max_dev": 0.05, "free_height_ratio_dev": 0.3}
MAX_FREE_SHARE = 3  # at most one frame in three may be freed
SCHEMA = "sprite_forge_qc/v1"


def parser():
    cli = argparse.ArgumentParser(
        description="Split a sprite sheet into aligned equal-size frames with numeric QC.")
    sub = cli.add_subparsers(dest="command", required=True)
    proc = sub.add_parser("process", help="process a sprite sheet into frames")
    proc.add_argument("--input", required=True)
    proc.add_argument("--rows", type=int, required=True)
    proc.add_argument("--cols", type=int, required=True)
    proc.add_argument("--output", required=True)
    proc.add_argument("--key", default=DEFAULT_KEY)
    proc.add_argument("--tolerance", type=int, default=DEFAULT_TOLERANCE)
    proc.add_argument("--target-height", type=int, default=None)
    proc.add_argument("--free-frames", default="",
                      help="comma-separated 0-based frame indices that keep the place their "
                           "source cell gave them (jump, fall, lunge). Decided from the "
                           "art-direction record BEFORE the run, never after a REGENERATE. "
                           "Every other frame stays gated on feet alignment")
    test = sub.add_parser("selftest", help="run the built-in synthetic self test")
    test.add_argument("--output", required=True)
    return cli


def system_alias(part):
    # macOS ships /etc, /tmp and /var (home of the default temp dir) as links
    # into /private. Only root can create a top-level entry, so trust exactly
    # those three, and only when the link names the same directory there.
    if sys.platform != "darwin" or part.parent != Path("/") or part.name not in ("etc", "tmp", "var"):
        return False
    try:
        return os.readlink(part) in ("private/" + part.name, "/private/" + part.name)
    except OSError:
        return False


def is_link(part):
    # From Python 3.14, Path.is_symlink() swallows every OSError, so an entry
    # under a directory that cannot be searched reads as "not a link". lstat it
    # first: a missing entry is fine, any other error means it cannot be checked.
    try:
        os.lstat(part)
    except OSError as exc:
        if exc.errno not in (errno.ENOENT, errno.ENOTDIR):
            raise ValueError(f"path could not be checked: {exc.strerror}") from exc
    return part.is_symlink()


def safe_path(value):
    path = Path(value)
    if ".." in path.parts:
        raise ValueError("path traversal is not accepted")
    path = path.absolute()
    if any(is_link(part) and not system_alias(part) for part in (path, *path.parents)):
        raise ValueError("symlink paths are not accepted")
    return path


def parse_key(value):
    text = value.strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", text):
        raise ValueError("--key must be a 6-digit hex color such as FF00FF")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def validate_process(args):
    if args.rows < 1 or args.cols < 1:
        raise ValueError("--rows and --cols must be positive integers")
    if args.rows * args.cols > 1 and (args.rows == 1 or args.cols == 1):
        raise ValueError(
            "strip layout (rows==1 or cols==1) is refused; "
            "regenerate the sheet as a grid (2x2, 2x3, ...)")
    if args.tolerance < 0:
        raise ValueError("--tolerance must be zero or positive")
    if args.target_height is not None and args.target_height < 1:
        raise ValueError("--target-height must be a positive integer")
    key = parse_key(args.key)
    source = safe_path(args.input)
    output = safe_path(args.output)
    if output.exists() or not output.parent.is_dir():
        raise ValueError("output directory must be new and its parent must already exist")
    if not source.is_file():
        raise ValueError("input must be a regular sprite-sheet file")
    if source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"input file exceeds the maximum size ({MAX_FILE_BYTES} bytes)")
    return key, source, output


def parse_free_frames(value, count):
    """Parse --free-frames into a set of valid 0-based frame indices."""
    free = set()
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or int(part) >= count:
            raise ValueError(f"--free-frames entry {part!r} is not a frame index below {count}")
        free.add(int(part))
    return free


def cell_mask(cell_bytes, cw, ch, alpha_input, key, tolerance):
    """Return a 0/1 bytearray marking opaque pixels for one cell crop.

    alpha_input: use the alpha channel as-is, no key guess. Otherwise a pixel
    is background when every RGB channel is within tolerance of the key.
    """
    mask = bytearray(cw * ch)
    n = cw * ch
    if alpha_input:
        for i in range(n):
            if cell_bytes[4 * i + 3] >= ALPHA_OPAQUE_THRESHOLD:
                mask[i] = 1
    else:
        kr, kg, kb = key
        for i in range(n):
            r, g, b = cell_bytes[3 * i], cell_bytes[3 * i + 1], cell_bytes[3 * i + 2]
            if abs(r - kr) > tolerance or abs(g - kg) > tolerance or abs(b - kb) > tolerance:
                mask[i] = 1
    return mask


def components(mask, w, h):
    """Label 4-connected opaque regions; return (labels, component list)."""
    labels = array("i", b"\xff\xff\xff\xff" * (w * h))
    comps = []
    for start in range(w * h):
        if not mask[start] or labels[start] >= 0:
            continue
        index = len(comps)
        labels[start] = index
        stack = [start]
        area = 0
        minx = maxx = start % w
        miny = maxy = start // w
        while stack:
            p = stack.pop()
            x = p % w
            y = p // w
            area += 1
            if x < minx:
                minx = x
            if x > maxx:
                maxx = x
            if y < miny:
                miny = y
            if y > maxy:
                maxy = y
            if x > 0 and mask[p - 1] and labels[p - 1] < 0:
                labels[p - 1] = index
                stack.append(p - 1)
            if x < w - 1 and mask[p + 1] and labels[p + 1] < 0:
                labels[p + 1] = index
                stack.append(p + 1)
            if y > 0 and mask[p - w] and labels[p - w] < 0:
                labels[p - w] = index
                stack.append(p - w)
            if y < h - 1 and mask[p + w] and labels[p + w] < 0:
                labels[p + w] = index
                stack.append(p + w)
        comps.append({"area": area, "bbox": [minx, miny, maxx, maxy]})
    return labels, comps


def process_cell(cell_index, row, col, cell_bytes, cw, ch, alpha_input, key, tolerance):
    """Extract one cell's retained body. Refuse empty cells and edge bleed."""
    mask = cell_mask(cell_bytes, cw, ch, alpha_input, key, tolerance)
    labels, comps = components(mask, cw, ch)
    name = f"cell {cell_index} (row {row}, col {col})"
    if not comps:
        raise ValueError(f"{name} is empty")
    largest = max(c["area"] for c in comps)
    floor_area = max(1, int(round(SMALL_COMPONENT_FRACTION * largest)))
    kept = {i for i, c in enumerate(comps) if c["area"] >= floor_area}
    x0 = min(comps[i]["bbox"][0] for i in kept)
    y0 = min(comps[i]["bbox"][1] for i in kept)
    x1 = max(comps[i]["bbox"][2] for i in kept)
    y1 = max(comps[i]["bbox"][3] for i in kept)
    if x0 == 0 or y0 == 0 or x1 == cw - 1 or y1 == ch - 1:
        raise ValueError(
            f"{name}: opaque region touches the cell edge (bleed); "
            "regenerate the sheet with margins inside each cell")
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    body = bytearray(bw * bh * 4)
    for y in range(bh):
        base = (y0 + y) * cw + x0
        for x in range(bw):
            label = labels[base + x]
            if label < 0 or label not in kept:
                continue
            di = (y * bw + x) * 4
            si = (base + x) * (4 if alpha_input else 3)
            if alpha_input:
                body[di:di + 4] = cell_bytes[si:si + 4]
            else:
                body[di] = cell_bytes[si]
                body[di + 1] = cell_bytes[si + 1]
                body[di + 2] = cell_bytes[si + 2]
                body[di + 3] = 255
    spill = 0
    if not alpha_input:
        kr, kg, kb = key
        wide = 2 * tolerance
        for i in range(0, len(body), 4):
            if (body[i + 3] and abs(body[i] - kr) <= wide and abs(body[i + 1] - kg) <= wide
                    and abs(body[i + 2] - kb) <= wide):
                spill += 1
    opaque = sum(1 for i in range(3, len(body), 4) if body[i])
    return {"bbox": [x0, y0, x1, y1], "width": bw, "height": bh, "body": bytes(body),
            "spill": spill, "opaque": opaque}


def png_bytes(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def write_new(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)


def run_process(args, argv):
    key, source, output = validate_process(args)
    try:
        from PIL import Image
        import PIL
    except ImportError as exc:
        raise ValueError(
            "optional dependency missing; install Pillow in an isolated "
            "operator environment (for example: uv run --with pillow)") from exc

    with source.open("rb") as fh:
        try:
            image = Image.open(fh)
            image.load()
        except Image.DecompressionBombError as exc:
            raise ValueError("input exceeds the image size budget") from exc
    width, height = image.size
    if width > MAX_SIDE_PX or height > MAX_SIDE_PX:
        raise ValueError(f"input exceeds the maximum side length ({MAX_SIDE_PX}px)")
    if width % args.cols or height % args.rows:
        raise ValueError(
            "sheet size is not divisible by the requested grid; "
            "rows and cols must divide the sheet exactly")

    # Alpha rule: an alpha channel with any transparency is used as-is; only a
    # fully opaque sheet is chroma-keyed.
    has_alpha_slot = image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info)
    rgba = image.convert("RGBA")
    alpha_input = has_alpha_slot and rgba.getchannel("A").getextrema()[0] < 255
    if alpha_input:
        base = rgba
    else:
        base = rgba.convert("RGB")

    cw, ch = width // args.cols, height // args.rows
    cells = []
    for row in range(args.rows):
        for col in range(args.cols):
            index = row * args.cols + col
            crop = base.crop((col * cw, row * ch, (col + 1) * cw, (row + 1) * ch))
            cells.append(process_cell(index, row, col, crop.tobytes(), cw, ch,
                                      alpha_input, key, args.tolerance))

    # One common scale for every frame: the median body height maps onto
    # --target-height; with no target the median is kept (scale 1.0).
    heights = [c["height"] for c in cells]
    median = statistics.median(heights)
    scale = 1.0 if args.target_height is None else args.target_height / median
    scaled = [(c, max(1, int(round(c["width"] * scale))),
               max(1, int(round(c["height"] * scale)))) for c in cells]
    # Alignment is judged on the INPUT: the lowest opaque row of each retained
    # body inside its own cell, as a share of the cell height. Measuring the
    # output would only read back the row the code just chose.
    free = parse_free_frames(args.free_frames, len(cells))
    gated = [i for i in range(len(cells)) if i not in free]
    if len(free) > len(cells) // MAX_FREE_SHARE:
        raise ValueError(
            f"--free-frames may free at most one frame in {MAX_FREE_SHARE} "
            f"({len(cells) // MAX_FREE_SHARE} of {len(cells)}); a sheet that needs more "
            "should be regenerated or split by animation")
    if len(gated) < 2:
        raise ValueError("--free-frames must leave at least two gated frames")
    feet_in = [c["bbox"][3] for c in cells]
    gated_feet = [feet_in[i] for i in gated]
    feet_median = statistics.median(gated_feet)
    anchor_y_std = statistics.pstdev(gated_feet) / ch
    # The gate is the largest deviation from the median, not the spread: a
    # standard deviation dilutes one lifted frame among many.
    anchor_y_max_dev = max(abs(f - feet_median) for f in gated_feet) / ch
    centre_x = [(c["bbox"][0] + c["bbox"][2]) / 2 for c in cells]
    centre_median = statistics.median(centre_x[i] for i in gated)
    gated_height_median = statistics.median(heights[i] for i in gated)
    # A freed frame is a pose, not a scale change: its body height stays near the
    # gated frames' median or the sheet is regenerated.
    free_height_ratio_dev = max(
        (abs(heights[i] / gated_height_median - 1) for i in free), default=0.0)
    if free:
        frame_w = max(1, int(round(cw * scale)))
        frame_h = max(1, int(round(ch * scale)))
        baseline_y = min(frame_h - 1, int(round(feet_median * scale)))
    else:
        frame_w = max(s[1] for s in scaled)
        frame_h = max(s[2] for s in scaled)
        baseline_y = frame_h - 1

    frames = []
    for index, (cell, nw, nh) in enumerate(scaled):
        body_img = Image.frombytes("RGBA", (cell["width"], cell["height"]),
                                   cell["body"]).resize((nw, nh), Image.NEAREST)
        frame = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
        if index in free:
            # Relative to the gated frames' pivot (median centre x, median feet row),
            # so a jump keeps its offset from the others instead of its raw cell place.
            feet_at = baseline_y + (feet_in[index] - feet_median) * scale
            at = ((frame_w - nw) // 2 + int(round((centre_x[index] - centre_median) * scale)),
                  int(round(feet_at - nh + 1)))
        elif free:
            at = ((frame_w - nw) // 2, baseline_y - nh + 1)
        else:
            at = ((frame_w - nw) // 2, frame_h - nh)
        if at[0] < 0 or at[1] < 0 or at[0] + nw > frame_w or at[1] + nh > frame_h:
            raise ValueError(f"frame {index} does not fit the shared canvas; "
                             "regenerate the sheet with margins inside each cell")
        frame.paste(body_img, at)
        frames.append(frame)
    gated_heights = [heights[i] for i in gated]
    mean_h = statistics.fmean(gated_heights)
    if mean_h <= 0:
        raise ValueError("degenerate body heights")
    body_scale_cv = statistics.pstdev(gated_heights) / mean_h
    verdict = ("PASS" if body_scale_cv <= THRESHOLDS["body_scale_cv"]
               and anchor_y_max_dev <= THRESHOLDS["anchor_y_max_dev"]
               and free_height_ratio_dev <= THRESHOLDS["free_height_ratio_dev"] else "REGENERATE")
    if verdict == "PASS" and free:
        verdict = "PASS_FREE_FRAMES"
    spill = sum(c["spill"] for c in cells)
    kept_px = sum(c["opaque"] for c in cells)

    sheet = Image.new("RGBA", (frame_w * args.cols, frame_h * args.rows), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        row, col = divmod(i, args.cols)
        sheet.paste(frame, (col * frame_w, row * frame_h))

    # All computation and all refusals happen before anything is written.
    output.mkdir()
    raw = source.read_bytes()
    input_sha = sha256(raw)
    output_shas = {}
    for i, frame in enumerate(frames):
        name = f"frame_{i:03d}.png"
        blob = png_bytes(frame)
        write_new(output / name, blob)
        output_shas[name] = sha256(blob)
    blob = png_bytes(sheet)
    write_new(output / "sheet.png", blob)
    output_shas["sheet.png"] = sha256(blob)

    frames_qc = []
    for i, (cell, nw, nh) in enumerate(scaled):
        row, col = divmod(i, args.cols)
        frames_qc.append({"index": i, "row": row, "col": col, "bbox": cell["bbox"],
                          "width": cell["width"], "height": cell["height"],
                          "scaled_size": [nw, nh]})
    qc = {
        "schema": SCHEMA,
        "verdict": verdict,
        "frame_count": len(frames),
        "rows": args.rows,
        "cols": args.cols,
        "cell_size": [cw, ch],
        "frame_size": [frame_w, frame_h],
        "baseline_y": baseline_y,
        "scale": scale,
        "median_body_height": median,
        "frames": frames_qc,
        "body_scale_cv": body_scale_cv,
        "anchor_y_std": anchor_y_std,
        "anchor_y_max_dev": anchor_y_max_dev,
        "free_height_ratio_dev": free_height_ratio_dev,
        "free_frames": sorted(free),
        "gated_frames": gated,
        "key_spill_pixels": None if alpha_input else spill,
        "key_spill_share": None if alpha_input else ((spill / kept_px) if kept_px else 0.0),
        "thresholds": dict(THRESHOLDS),
        "metric_definitions": {
            "body_height": ("pixel rows spanned by the opaque bbox of the retained "
                            "components in a cell, measured before common scaling"),
            "body_scale_cv": ("population std / mean of the per-frame body heights, "
                              "measured before common scaling"),
            "feet_row": "lowest opaque row of each retained body inside its source cell",
            "anchor_y_std": ("population std of the gated frames' feet rows measured on "
                             "the input sheet, divided by the cell height; reported only"),
            "anchor_y_max_dev": ("largest distance of a gated frame's feet row from the median "
                                 "feet row on the input sheet, divided by the cell height; "
                                 "the gate. REGENERATE here means a pose stands off the "
                                 "baseline in the source image, not that outputs are misaligned"),
            "key_spill_pixels": ("retained opaque pixels within twice the tolerance of the "
                                 "key colour: fringe or key-coloured costume; reported, "
                                 "not gated"),
            "free_height_ratio_dev": ("largest |height / gated median height - 1| over the "
                                      "freed frames; gated at 0.3 so a freed frame is a pose, "
                                      "not a scale change"),
            "verdict": ("PASS when body_scale_cv <= 0.08 and anchor_y_max_dev <= 0.05 over the "
                        "gated frames and free_height_ratio_dev <= 0.3, otherwise REGENERATE the "
                        "source sheet; never retouch frames. PASS_FREE_FRAMES is the same "
                        "pass when frames named in free_frames (at most one in three, at least "
                        "two frames stay gated) were excluded from both feet and scale gates; "
                        "they keep their offset from the gated frames' pivot"),
        },
        "input_sha256": input_sha,
        "output_sha256s": output_shas,
        "qc_self_hash": "excluded; hash this file externally",
        "script_sha256": sha256(Path(__file__).read_bytes()),
        "pillow_version": PIL.__version__,
        "argv": argv,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    blob = (json.dumps(qc, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
    write_new(output / "qc.json", blob)

    status = {"PASS": "ok", "PASS_FREE_FRAMES": "ok_free_frames"}.get(verdict, "regenerate")
    print(json.dumps({"status": status,
                      "output_dir": str(output), "verdict": verdict,
                      "frame_count": len(frames), "frame_size": [frame_w, frame_h],
                      "body_scale_cv": round(body_scale_cv, 6),
                      "anchor_y_std": round(anchor_y_std, 6),
                      "anchor_y_max_dev": round(anchor_y_max_dev, 6),
                      "free_frames": sorted(free),
                      "gated_frames": gated,
                      "key_spill_pixels": None if alpha_input else spill}))
    return 0 if verdict in ("PASS", "PASS_FREE_FRAMES") else 3


def run_selftest(output_value):
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ValueError(
            "optional dependency missing; install Pillow in an isolated "
            "operator environment (for example: uv run --with pillow)") from exc
    output = safe_path(output_value)
    if output.exists() or not output.parent.is_dir():
        raise ValueError("output directory must be new and its parent must already exist")
    # Do NOT pre-create: `process` requires a brand-new --output and creates it
    # itself; pre-creating would make the nested process call refuse.
    tmp_paths = []
    try:
        # A 2x2 #FF00FF sheet whose four figures vary slightly in height and
        # vertical offset, well inside the QC thresholds.
        sheet = Image.new("RGB", (512, 512), (255, 0, 255))
        draw = ImageDraw.Draw(sheet)
        heights = (170, 176, 164, 172)
        offsets = (0, 6, 3, 9)
        for index, body_h in enumerate(heights):
            row, col = divmod(index, 2)
            x0 = col * 256 + 108
            bottom = row * 256 + 244 - offsets[index]
            draw.rectangle([x0, bottom - body_h, x0 + 40, bottom], fill=(230, 235, 240))
            draw.ellipse([x0 + 5, bottom - body_h - 30, x0 + 35, bottom - body_h],
                         fill=(240, 200, 90))
        grid_png = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        grid_png.close()
        tmp_paths.append(grid_png.name)
        sheet.save(grid_png.name, "PNG")

        code = main(["process", "--input", grid_png.name, "--rows", "2",
                     "--cols", "2", "--output", str(output)])
        if code != 0:
            raise AssertionError(f"grid process exited {code}, expected 0")
        qc = json.loads((output / "qc.json").read_text())
        if qc["frame_count"] != 4:
            raise AssertionError(f"expected 4 frames, got {qc['frame_count']}")
        if qc["verdict"] != "PASS":
            raise AssertionError(f"expected PASS, got {qc['verdict']}")
        frame_paths = sorted(output.glob("frame_*.png"))
        if len(frame_paths) != 4:
            raise AssertionError(f"expected 4 frame files, got {len(frame_paths)}")
        sizes = {Image.open(p).size for p in frame_paths}
        if len(sizes) != 1:
            raise AssertionError(f"frame sizes differ: {sizes}")

        # A 1x4 strip must be refused with no output written.
        strip = Image.new("RGB", (1024, 256), (255, 0, 255))
        sdraw = ImageDraw.Draw(strip)
        sdraw.rectangle([100, 60, 140, 220], fill=(230, 235, 240))
        strip_png = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        strip_png.close()
        tmp_paths.append(strip_png.name)
        strip.save(strip_png.name, "PNG")
        strip_code = main(["process", "--input", strip_png.name, "--rows", "1",
                           "--cols", "4", "--output", str(output / "strip")])
        if strip_code != 2:
            raise AssertionError(f"strip process exited {strip_code}, expected 2")
        if (output / "strip").exists():
            raise AssertionError("strip refusal created an output directory")
    except AssertionError as exc:
        print(f"selftest: FAIL ({exc})", file=sys.stderr)
        return 1
    finally:
        for path in tmp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass
    print("selftest: PASS (4 frames, equal size, PASS verdict, strip layout refused)")
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "selftest":
            return run_selftest(args.output)
        return run_process(args, list(argv) if argv is not None else list(sys.argv))
    except (ValueError, OSError) as exc:
        print(f"forge refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
