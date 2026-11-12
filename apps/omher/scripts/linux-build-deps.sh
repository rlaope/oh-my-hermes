#!/usr/bin/env bash
# Install omher's Linux build libraries on a GitHub Ubuntu runner: linux-build-deps.sh <package>...
#
# The runner image reads Ubuntu packages through /etc/apt/apt-mirrors.txt (azure.archive.ubuntu.com first).
# When those names do not resolve, a plain `apt-get install` does not fail: it waits about 20 s per package
# and per mirror, so this one step ran for over two hours (2026-11-11, the ubuntu.com name servers timed out).
# This script asks each mirror for its index first, uses the first one that answers, bounds every apt call
# with a timeout, and moves on to the next mirror when one fails.
# The fallbacks are public full mirrors. apt still checks every index and package against the Ubuntu archive
# key already on the runner, so a mirror can be stale or down but cannot hand over a changed package.
set -euo pipefail

[ "$#" -gt 0 ] || { echo "usage: linux-build-deps.sh <package>..." >&2; exit 2; }

# The two paths can be pointed elsewhere so the mirror choice can be exercised off a runner.
LIST="${OMHER_APT_MIRRORS:-/etc/apt/apt-mirrors.txt}"
OS_RELEASE="${OMHER_OS_RELEASE:-/etc/os-release}"
FALLBACKS="https://mirrors.edge.kernel.org/ubuntu/ https://mirrors.mit.edu/ubuntu/ https://mirror.math.princeton.edu/pub/ubuntu/"

# shellcheck disable=SC1090
codename=$(. "$OS_RELEASE" && echo "$VERSION_CODENAME")

# apt_get <seconds> <apt-get arguments>: one bounded apt call.
apt_get() {
  local limit="$1"
  shift
  sudo timeout --kill-after=30 "$limit" apt-get -o Acquire::Retries=2 -o DPkg::Lock::Timeout=120 "$@"
}

answers() { curl -fsS --max-time 15 -o /dev/null "${1%/}/dists/$codename/InRelease"; }

install_all() { apt_get 180 update && apt_get 600 install -y "$@"; }

if [ ! -f "$LIST" ]; then
  echo "linux-build-deps: no $LIST here, using the configured apt sources"
  install_all "$@"
  exit 0
fi

saved=$(mktemp)
cp "$LIST" "$saved"
first=$(awk 'NF { print $1; exit }' "$LIST")

if [ -n "$first" ] && answers "$first"; then
  echo "linux-build-deps: using the runner's mirror list ($first)"
  if install_all "$@"; then
    exit 0
  fi
  echo "linux-build-deps: the runner's mirror list failed, trying a fallback mirror" >&2
else
  echo "linux-build-deps: ${first:-the first runner mirror} does not answer, trying a fallback mirror" >&2
fi

for mirror in $FALLBACKS; do
  if ! answers "$mirror"; then
    echo "linux-build-deps: $mirror does not answer" >&2
    continue
  fi
  echo "linux-build-deps: using $mirror"
  printf '%s\tpriority:1\n' "$mirror" | sudo tee "$LIST" >/dev/null
  if install_all "$@"; then
    exit 0
  fi
  echo "linux-build-deps: $mirror failed" >&2
done

sudo cp "$saved" "$LIST"
echo "linux-build-deps: no Ubuntu mirror answered; the build libraries are not installed" >&2
exit 1
