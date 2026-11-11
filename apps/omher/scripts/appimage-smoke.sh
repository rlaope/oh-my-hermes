#!/usr/bin/env bash
# Start an omher AppImage on a headless Linux host and check that it really runs.
#
#   apps/omher/scripts/appimage-smoke.sh <path-to-AppImage>
#
# Passes only when, with a fresh HOME under xvfb-run:
#   1. the app process is still alive 20 seconds after launch,
#   2. a visible window titled "omher" exists (xdotool),
#   3. the bundled bridge (<AppImage>/usr/lib/omher/bridge/omher_bridge.py) started as a process.
# Then it kills the app. Each observation is printed on its own line; on failure the app's stderr follows.
#
# CI runners have no FUSE, so the AppImage is unpacked with --appimage-extract and its AppRun started.
# The fresh HOME gets a stand-in Hermes venv (~/.hermes/hermes-agent/venv with websockets and pyyaml), the
# layout omher looks for, so the bridge has a Python to start on. Needs: xvfb-run, xdotool, python3 -m venv.
set -uo pipefail

ALIVE_AFTER=20   # seconds the app must stay up
WAIT_MAX=45      # give up waiting for the window and the bridge after this many seconds

if [ -z "${OMHER_SMOKE_UNDER_XVFB:-}" ]; then
  img="${1:?usage: appimage-smoke.sh <path-to-AppImage>}"
  for tool in xvfb-run xdotool python3; do
    command -v "$tool" >/dev/null || { echo "missing tool: $tool"; exit 2; }
  done
  [ -f "$img" ] || { echo "no such file: $img"; exit 2; }
  img="$(cd "$(dirname "$img")" && pwd)/$(basename "$img")"
  OMHER_SMOKE_UNDER_XVFB=1 exec timeout 115 xvfb-run -a -s "-screen 0 1280x800x24" bash "$0" "$img"
fi

img="$1"
work="$(mktemp -d)"
home="$work/home"
mkdir -p "$home"
app_pid=""

# shellcheck disable=SC2329  # called by the EXIT trap
cleanup() {
  if [ -n "$app_pid" ]; then
    kill -TERM -- "-$app_pid" 2>/dev/null
    sleep 2
    kill -KILL -- "-$app_pid" 2>/dev/null
  fi
  rm -rf "$work"
}
trap cleanup EXIT

echo "appimage: $img ($(stat -c %s "$img") bytes)"
chmod +x "$img"
(cd "$work" && "$img" --appimage-extract >/dev/null) || { echo "RESULT: FAIL (--appimage-extract failed)"; exit 1; }
root="$work/squashfs-root"
bridge_script="$root/usr/lib/omher/bridge/omher_bridge.py"
[ -f "$bridge_script" ] && echo "bundled bridge: $bridge_script" || echo "bundled bridge: MISSING at usr/lib/omher/bridge/omher_bridge.py"

venv="$home/.hermes/hermes-agent/venv"
if ! { python3 -m venv "$venv" && timeout 60 "$venv/bin/python" -m pip install -q "websockets>=14" pyyaml; } >"$work/venv.log" 2>&1; then
  echo "RESULT: FAIL (could not make the stand-in Hermes venv)"; cat "$work/venv.log"; exit 1
fi
echo "hermes python: $venv/bin/python ($("$venv/bin/python" --version 2>&1))"

# No GPU under Xvfb: keep WebKitGTK on its software paths.
export HOME="$home" WEBKIT_DISABLE_COMPOSITING_MODE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1
unset HERMES_HOME OMHER_HERMES_PYTHON
echo "display: $DISPLAY, HOME=$HOME"

# The AppImage runtime sets APPIMAGE and APPDIR before it starts AppRun (also for --appimage-extract-and-run);
# starting the unpacked AppRun skips the runtime, so set them as it would. omher keys its host-environment
# handling for the programs it starts (the bridge's Python first) on both being set.
# setsid: the app leads its own process group, so cleanup kills it with its WebKit and bridge children.
(cd "$root" && APPIMAGE="$img" APPDIR="$root" exec setsid ./AppRun >"$work/app.out" 2>"$work/app.err") &
app_pid=$!
start=$(date +%s)

window="" bridge="" app_bin=""
while :; do
  t=$(( $(date +%s) - start ))
  [ -z "$window" ] && window="$(xdotool search --onlyvisible --name '^omher$' 2>/dev/null | head -1)" \
    && [ -n "$window" ] && echo "window seen after ${t}s"
  [ -z "$bridge" ] && bridge="$(pgrep -f -a "omher_bridge\.py" | head -1)" \
    && [ -n "$bridge" ] && echo "bridge process seen after ${t}s"
  kill -0 "$app_pid" 2>/dev/null || break
  # AppRun may be a wrapper; the app is the process whose executable is the image's usr/bin/omher.
  if [ -z "$app_bin" ]; then
    for p in $(pgrep omher); do
      [ "$(readlink -f "/proc/$p/exe" 2>/dev/null)" = "$(readlink -f "$root/usr/bin/omher")" ] && { app_bin=$p; break; }
    done
  fi
  [ "$t" -ge "$ALIVE_AFTER" ] && [ -n "$window" ] && [ -n "$bridge" ] && break
  [ "$t" -ge "$WAIT_MAX" ] && break
  sleep 1
done
t=$(( $(date +%s) - start ))

fail=0
if [ -n "$app_bin" ] && kill -0 "$app_bin" 2>/dev/null && [ "$t" -ge "$ALIVE_AFTER" ]; then
  echo "OBSERVED alive: omher pid $app_bin ($(ps -o args= -p "$app_bin" | cut -c1-120)) still running after ${t}s"
else
  echo "NOT OBSERVED alive: the app exited or was not up for ${ALIVE_AFTER}s (checked at ${t}s)"; fail=1
fi
if [ -n "$window" ]; then
  echo "OBSERVED window: \"$(xdotool getwindowname "$window" 2>/dev/null)\" id $window $(xdotool getwindowgeometry "$window" 2>/dev/null | sed -n 's/.*Geometry: //p')"
else
  echo "NOT OBSERVED window: no visible window titled omher"; fail=1
  echo "windows present: $(xdotool search --name . getwindowname %@ 2>/dev/null | sort -u | tr '\n' '|')"
fi
case "$bridge" in
  *"$root/"*"omher_bridge.py "*) ;;  # the script inside the unpacked image, not some other copy
  ?*) echo "bridge process is not the bundled one: $bridge" | sed 's/--token [^ ]*/--token <redacted>/'; bridge="" ;;
esac
if [ -n "$bridge" ]; then
  echo "OBSERVED bridge: pid ${bridge%% *} ${bridge#* }" | sed 's/--token [^ ]*/--token <redacted>/'
else
  echo "NOT OBSERVED bridge: no process running $bridge_script"; fail=1
  pgrep -a python | sed 's/^/python process: /; s/--token [^ ]*/--token <redacted>/'
fi
grep -E '^omher: bridge (pid|ready|failed)' "$work/app.err" | sed 's/^/app log: /'

if [ "$fail" = 0 ]; then
  echo "RESULT: PASS"
else
  echo "RESULT: FAIL"
  echo "---- app stderr (last 200 lines)"
  tail -n 200 "$work/app.err"
  echo "---- app stdout (last 50 lines)"
  tail -n 50 "$work/app.out"
fi
exit "$fail"
