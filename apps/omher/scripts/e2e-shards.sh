#!/usr/bin/env bash
# Run the Playwright e2e suite as N shards at the same time: e2e-shards.sh [N] [extra playwright args...]
#
# playwright.config.ts keeps `workers: 1` because one mock bridge holds shared state (calls log, running turn).
# So instead of more workers, each shard is its own `playwright test` process with its own Vite dev server and
# mock bridge on its own port pair (OMHER_PORT / OMHER_MOCK_PORT), its own Vite dep-optimizer cache
# (OMHER_VITE_CACHE_DIR, read by vite.config.ts: several dev servers optimizing into one node_modules/.vite at
# once can race) and its own output dir. Inside a shard the files still run one at a time against its one mock.
#
# Each shard writes test-results/shard-<i>.log; once all have ended the logs are printed in order and the script
# exits 1 if any shard failed. Run from anywhere; it works in Git Bash on Windows too.
set -uo pipefail

n="${1:-3}"
shift || true
cd "$(dirname "$0")/.."
mkdir -p test-results

pids=()
started=$(date +%s)
for i in $(seq 1 "$n"); do
  OMHER_PORT=$((5310 + 10 * i)) OMHER_MOCK_PORT=$((5311 + 10 * i)) \
    OMHER_VITE_CACHE_DIR="node_modules/.vite-shard-$i" \
    pnpm exec playwright test --shard="$i/$n" --reporter=line --output "test-results/shard-$i" "$@" \
    > "test-results/shard-$i.log" 2>&1 &
  pids+=("$!")
done

failed=0
for i in $(seq 1 "$n"); do
  wait "${pids[$((i - 1))]}"
  rc=$?
  echo "::group::e2e shard $i/$n (exit $rc)"
  cat "test-results/shard-$i.log"
  echo "::endgroup::"
  if [ "$rc" -ne 0 ]; then
    echo "e2e shard $i/$n failed (exit $rc)"
    failed=1
  fi
done
echo "e2e: $n shards in $(( $(date +%s) - started ))s"
exit "$failed"
