#!/bin/sh
# Build the omher.app hero preview: the real omher UI (apps/omher/src at a pinned commit) with the in-page host in
# apps/omher/preview/, into site/app-preview/ (static, hashed assets, no network).
#
#   tools/build_omher_preview.sh [<app commit>]
#
# The app source comes from <app commit> (default: OMHER_PREVIEW_APP below), so the preview can show a newer app
# than the one on this branch; the preview entry always comes from this checkout. The commit's tree is exported
# into a temporary folder next to apps/omher's node_modules (pnpm install there first). Nothing in the repo is
# changed except site/app-preview/.
set -eu
OMHER_PREVIEW_APP=b9d913ad64a06ed2fc31f7a9a299ee840d9fb6d2   # omher v0.2.8 (#2864): six more ACP agents, More agents, responsive session header
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SHA=${1:-$OMHER_PREVIEW_APP}
NM=${OMHER_NODE_MODULES:-$ROOT/apps/omher/node_modules}
[ -d "$NM/vite" ] || { echo "need apps/omher/node_modules (cd apps/omher && pnpm install), or OMHER_NODE_MODULES=<dir>" >&2; exit 1; }
TMP=$(mktemp -d "${TMPDIR:-/tmp}/omher-preview.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
git -C "$ROOT" archive "$SHA" apps/omher/src apps/omher/package.json apps/omher/tsconfig.json | tar -x -C "$TMP"
APP="$TMP/apps/omher"
cp -R "$ROOT/apps/omher/preview" "$APP/preview"
ln -s "$NM" "$APP/node_modules"
OMHER_PREVIEW_OUT="$ROOT/site/app-preview" "$APP/node_modules/.bin/vite" build --config "$APP/preview/vite.config.ts" --logLevel warn
printf '%s\n' "$SHA" > "$ROOT/site/app-preview/APP_COMMIT"
echo "built site/app-preview from apps/omher@$SHA"
ls -la "$ROOT/site/app-preview/assets"
