#!/usr/bin/env bash
# MIT; Copyright (c) 2026 Minho Hwang (revfactory).
# Modified for OMH from revfactory/showreel@64521220a2f8e91cb9894400c48c15b7f45205d6
# scripts/codex_ref_image.sh: OPT-IN, run only by a user with their own signed-in codex CLI;
# refuses (exit 2) without it. Prompt and messages in English.
# Full permission/warranty: ../LICENSE.upstream. OMH core never runs this file.
#
# Generates an image in which the same person, animal or product from reference photos appears in a NEW scene,
# using codex with the reference images attached (codex-image batch scripts take no reference image, hence this wrapper).
#
# Usage: codex_ref_image.sh <out.png> "<scene prompt>" <ref1.jpg> [ref2.jpg ...]
#   - The folder of out.png becomes the working folder (inside the project, for example assets/gen/).
#   - References of about 1024 px on the long side are faster (sips -Z 1024 in.jpg --out ref.jpg).
#   - Restate the subject's identity features in words (markings, eye colour, clothing, props), plus the framing
#     ("landscape 16:9 composition") and "no text or logos".
#   - Run up to 5 at once in the background; more queue up and get slower.
#   - An existing out.png is skipped (easy to rerun only the failures).
set -u
if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found: this opt-in script uses your own signed-in codex; nothing was sent." >&2
  exit 2
fi
if [ "$#" -lt 3 ]; then
  echo "usage: codex_ref_image.sh <out.png> \"<scene prompt>\" <ref1.jpg> [ref2.jpg ...]" >&2
  exit 5
fi
OUT="$1"; PROMPT="$2"; shift 2
[ -s "$OUT" ] && { echo "SKIP $OUT"; exit 0; }
DIR="$(cd "$(dirname "$OUT")" && pwd)"; NAME="$(basename "$OUT")"
mkdir -p "$DIR/.codex-logs"
IMGS=()
for r in "$@"; do IMGS+=(-i "$(cd "$(dirname "$r")" && pwd)/$(basename "$r")"); done
BASE="Keep the look, markings, build and distinctive features of the subject in the attached real photos as faithfully as possible, and use the image generation tool to make a new image in which the same subject appears. Do not copy or edit the attached photos; generate the scene below as if it were newly photographed."
START=$(date +%s)
codex exec --sandbox workspace-write --skip-git-repo-check --cd "$DIR" "${IMGS[@]}" -o "$DIR/.codex-logs/${NAME%.*}.md" \
  "$BASE

Scene: $PROMPT

Save the generated image as ./$NAME (PNG). After saving, report only the file path on one line." > "$DIR/.codex-logs/${NAME%.*}.out" 2>&1 < /dev/null
END=$(date +%s)
if [ -s "$OUT" ]; then echo "OK $OUT $((END-START))s"; else echo "FAIL $OUT $((END-START))s (log: $DIR/.codex-logs/${NAME%.*}.out; rerun when it says 'at capacity')"; exit 1; fi
