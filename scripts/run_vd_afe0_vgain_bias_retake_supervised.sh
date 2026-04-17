#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/scripts/run_vd_afe0_vgain_bias_retake_remote.sh"

SYNC_TO_LXPLUS="${SYNC_TO_LXPLUS:-1}"
LXPLUS_USER="${LXPLUS_USER:-marroyav}"
LXBASE="${LXBASE:-/eos/experiment/neutplatform/protodune/experiments/ColdBoxVD/2026March}"
MONITOR_INTERVAL_S="${MONITOR_INTERVAL_S:-15}"
RSYNC_INTERVAL_S="${RSYNC_INTERVAL_S:-300}"
RUN_LOG_DIR="${RUN_LOG_DIR:-$ROOT_DIR/client/dynamic_range_led/runs}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0")

Behavior:
  - launches the dedicated VD AFE0 retake runner in the background
  - monitors both expected run directories via scan_summary.tsv
  - rsyncs any existing run directories to lxplus periodically
  - performs one final rsync after the runner exits

Environment:
  RUN_SUFFIX=_r1
  DATE_TAG=20260325
  SYNC_TO_LXPLUS=1
  LXPLUS_USER=marroyav
  LXBASE=/eos/experiment/neutplatform/protodune/experiments/ColdBoxVD/2026March
  MONITOR_INTERVAL_S=15
  RSYNC_INTERVAL_S=300
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 0 ]]; then
  usage
  exit 2
fi

if [[ ! -f "$RUNNER" ]]; then
  echo "Runner not found: $RUNNER" >&2
  exit 1
fi

RUN_DIRS=()
while IFS= read -r line; do
  [[ -n "$line" ]] && RUN_DIRS+=("$line")
done < <(PRINT_OUTPUTS=1 bash "$RUNNER")

if [[ "${#RUN_DIRS[@]}" -eq 0 ]]; then
  echo "No run directories resolved." >&2
  exit 1
fi

timestamp() {
  date '+%Y-%m-%d %H:%M:%S'
}

expected_groups() {
  local run_dir="$1"
  local name
  name="$(basename "$run_dir")"
  if [[ "$name" == *"_vg0500"* ]]; then
    echo $((1 * 3 * 4))
  else
    echo $((14 * 3 * 4))
  fi
}

progress_line() {
  local run_dir="$1"
  local label expected done status

  label="$(basename "$run_dir")"
  expected="$(expected_groups "$run_dir")"

  if [[ ! -d "$run_dir" ]]; then
    printf 'pending   %3s/%-3s groups  %s\n' "0" "$expected" "$label"
    return 0
  fi

  if [[ -f "$run_dir/scan_summary.tsv" ]]; then
    done="$(awk 'END{print NR-1}' "$run_dir/scan_summary.tsv" 2>/dev/null || echo 0)"
  else
    done=0
  fi

  status="running"
  if [[ "$done" -ge "$expected" ]]; then
    status="done"
  fi
  printf '%-8s %3s/%-3s groups  %s\n' "$status" "$done" "$expected" "$label"
}

sync_once() {
  [[ "$SYNC_TO_LXPLUS" != "1" ]] && return 0
  local run_dir run_name
  for run_dir in "${RUN_DIRS[@]}"; do
    [[ -d "$run_dir" ]] || continue
    run_name="$(basename "$run_dir")"
    ssh "${LXPLUS_USER}@lxplus.cern.ch" "mkdir -p '$LXBASE/$run_name'" >/dev/null 2>&1 || true
    rsync -az --partial --progress \
      "$run_dir/" \
      "${LXPLUS_USER}@lxplus.cern.ch:$LXBASE/$run_name/" >/dev/null 2>&1 || true
  done
}

mkdir -p "$RUN_LOG_DIR"
SUP_LOG="$RUN_LOG_DIR/$(date +%Y%m%d_%H%M%S)_vd_afe0_vgain_bias_retake_supervisor.log"

echo "Run log: $SUP_LOG"
echo "Expected runs:"
printf '  %s\n' "${RUN_DIRS[@]}"

bash "$RUNNER" >"$SUP_LOG" 2>&1 &
RUNNER_PID=$!

echo "Runner PID: $RUNNER_PID"
echo

LAST_SYNC_TS=0
while kill -0 "$RUNNER_PID" 2>/dev/null; do
  printf '[%s]\n' "$(timestamp)"
  for run_dir in "${RUN_DIRS[@]}"; do
    progress_line "$run_dir"
  done
  echo
  tail -n 12 "$SUP_LOG" 2>/dev/null || true
  echo

  if [[ "$SYNC_TO_LXPLUS" == "1" ]]; then
    now="$(date +%s)"
    if (( now - LAST_SYNC_TS >= RSYNC_INTERVAL_S )); then
      echo "[sync] mirroring current data to lxplus"
      sync_once
      LAST_SYNC_TS="$now"
      echo
    fi
  fi

  sleep "$MONITOR_INTERVAL_S"
done

wait "$RUNNER_PID"
rc=$?

echo
printf '[%s] runner exited rc=%s\n' "$(timestamp)" "$rc"
for run_dir in "${RUN_DIRS[@]}"; do
  progress_line "$run_dir"
done
echo
tail -n 20 "$SUP_LOG" 2>/dev/null || true

if [[ "$SYNC_TO_LXPLUS" == "1" ]]; then
  echo
  echo "[sync] final lxplus mirror"
  sync_once
fi

exit "$rc"
