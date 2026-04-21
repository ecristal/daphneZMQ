#!/usr/bin/env bash
set -euo pipefail

# Compare raw run directories across local, np04-srv-017, and lxplus.
# When SYNC=1, rsync missing run directories to lxplus, preferring the remote
# source when a run exists there.

REMOTE_HOST="${REMOTE_HOST:-np04-srv-017}"
LXPLUS_HOST="${LXPLUS_HOST:-marroyav@lxplus.cern.ch}"
LXPLUS_BASE="${LXPLUS_BASE:-/eos/experiment/neutplatform/protodune/experiments/ColdBoxVD/2026March}"
SYNC_MODE="${SYNC:-0}"

LOCAL_DYNAMIC="${LOCAL_DYNAMIC:-$HOME/repo/daphne-server/client/dynamic_range_led/runs}"
LOCAL_DARK="${LOCAL_DARK:-$HOME/repo/daphne-server/client/dark_vgain_runs}"
LOCAL_OSC="${LOCAL_OSC:-$HOME/repo/daphne-server/client/osc_runs}"

REMOTE_DYNAMIC="${REMOTE_DYNAMIC:-~/repo/daphne-server/client/dynamic_range_led/runs}"
REMOTE_DARK="${REMOTE_DARK:-~/repo/daphne-server/client/dark_vgain_runs}"
REMOTE_OSC="${REMOTE_OSC:-~/repo/daphne-server/client/osc_runs}"

WORKDIR="${WORKDIR:-/tmp/lxplus_run_sync}"
mkdir -p "$WORKDIR"

local_manifest() {
  local root="$1"
  local out="$2"
  if [ ! -d "$root" ]; then
    : >"$out"
    return 0
  fi
  python3 - "$root" >"$out" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1]).expanduser()
exclude_exact = {"calibration", "points"}
exclude_substrings = ("_local", "_clean", "localcheck", "remote_check")

for p in sorted(d for d in root.iterdir() if d.is_dir()):
    name = p.name
    if root.name == "runs":
        if name in exclude_exact or any(s in name for s in exclude_substrings):
            continue
    print(name)
PY
}

remote_manifest() {
  local root="$1"
  local out="$2"
  ssh "$REMOTE_HOST" "find $root -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | sort" | \
    python3 - "$root" >"$out" <<'PY'
import sys

root = sys.argv[1]
exclude_exact = {"calibration", "points"} if root.endswith("/runs") else set()
exclude_substrings = ("_local", "_clean", "localcheck", "remote_check") if root.endswith("/runs") else ()

for line in sys.stdin:
    name = line.strip()
    if not name:
        continue
    if name in exclude_exact:
        continue
    if any(s in name for s in exclude_substrings):
        continue
    print(name)
PY
}

lxplus_manifest() {
  local out="$1"
  ssh "$LXPLUS_HOST" "find '$LXPLUS_BASE' -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | sort" >"$out"
}

sync_run() {
  local category="$1"
  local run="$2"
  local local_root remote_root

  case "$category" in
    dynamic)
      local_root="$LOCAL_DYNAMIC"
      remote_root="$REMOTE_DYNAMIC"
      ;;
    dark)
      local_root="$LOCAL_DARK"
      remote_root="$REMOTE_DARK"
      ;;
    osc)
      local_root="$LOCAL_OSC"
      remote_root="$REMOTE_OSC"
      ;;
    *)
      echo "unknown category: $category" >&2
      return 1
      ;;
  esac

  ssh "$LXPLUS_HOST" "mkdir -p '$LXPLUS_BASE/$run'"
  if ssh "$REMOTE_HOST" "[ -d $remote_root/'$run' ]"; then
    echo "[sync] remote -> lxplus: $run"
    rsync -az --ignore-existing "$REMOTE_HOST:$remote_root/$run/" "$LXPLUS_HOST:$LXPLUS_BASE/$run/"
  elif [ -d "$local_root/$run" ]; then
    echo "[sync] local -> lxplus: $run"
    rsync -az --ignore-existing "$local_root/$run/" "$LXPLUS_HOST:$LXPLUS_BASE/$run/"
  else
    echo "[missing] no source found for $run" >&2
  fi
}

local_manifest "$LOCAL_DYNAMIC" "$WORKDIR/local_dynamic.txt"
local_manifest "$LOCAL_DARK" "$WORKDIR/local_dark.txt"
local_manifest "$LOCAL_OSC" "$WORKDIR/local_osc.txt"

remote_manifest "$REMOTE_DYNAMIC" "$WORKDIR/remote_dynamic.txt"
remote_manifest "$REMOTE_DARK" "$WORKDIR/remote_dark.txt"
remote_manifest "$REMOTE_OSC" "$WORKDIR/remote_osc.txt"

lxplus_manifest "$WORKDIR/lxplus.txt"

sort "$WORKDIR/local_dynamic.txt" "$WORKDIR/remote_dynamic.txt" | uniq >"$WORKDIR/union_dynamic.txt"
sort "$WORKDIR/local_dark.txt" "$WORKDIR/remote_dark.txt" | uniq >"$WORKDIR/union_dark.txt"
sort "$WORKDIR/local_osc.txt" "$WORKDIR/remote_osc.txt" | uniq >"$WORKDIR/union_osc.txt"

comm -23 "$WORKDIR/union_dynamic.txt" "$WORKDIR/lxplus.txt" >"$WORKDIR/missing_dynamic.txt"
comm -23 "$WORKDIR/union_dark.txt" "$WORKDIR/lxplus.txt" >"$WORKDIR/missing_dark.txt"
comm -23 "$WORKDIR/union_osc.txt" "$WORKDIR/lxplus.txt" >"$WORKDIR/missing_osc.txt"

printf '=== dynamic missing from lxplus ===\n'
cat "$WORKDIR/missing_dynamic.txt"
printf '\n=== dark missing from lxplus ===\n'
cat "$WORKDIR/missing_dark.txt"
printf '\n=== osc missing from lxplus ===\n'
cat "$WORKDIR/missing_osc.txt"
printf '\nWorkdir: %s\n' "$WORKDIR"

if [ "$SYNC_MODE" = "1" ]; then
  while IFS= read -r run; do
    [ -n "$run" ] && sync_run dynamic "$run"
  done <"$WORKDIR/missing_dynamic.txt"

  while IFS= read -r run; do
    [ -n "$run" ] && sync_run dark "$run"
  done <"$WORKDIR/missing_dark.txt"

  while IFS= read -r run; do
    [ -n "$run" ] && sync_run osc "$run"
  done <"$WORKDIR/missing_osc.txt"

  echo
  echo "Sync complete. Re-run with SYNC=0 to verify the remaining gaps."
fi
