#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/scripts/run_mar24_led_repeats_remote.sh"
PYTHON="${PYTHON:-python3}"

MODE="${1:-}"
TECH="${2:-}"

SYNC_TO_LXPLUS="${SYNC_TO_LXPLUS:-1}"
LXPLUS_USER="${LXPLUS_USER:-marroyav}"
LXBASE="${LXBASE:-/eos/experiment/neutplatform/protodune/experiments/ColdBoxVD/2026March}"
MONITOR_INTERVAL_S="${MONITOR_INTERVAL_S:-15}"
RSYNC_INTERVAL_S="${RSYNC_INTERVAL_S:-300}"
RUN_LOG_DIR="${RUN_LOG_DIR:-$ROOT_DIR/client/dynamic_range_led/runs}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0") <mode> <tech>

Examples:
  $(basename "$0") saturation vd
  $(basename "$0") vgain hd
  $(basename "$0") all all

Environment:
  SYNC_TO_LXPLUS=1
  LXPLUS_USER=marroyav
  LXBASE=/eos/experiment/neutplatform/protodune/experiments/ColdBoxVD/2026March
  MONITOR_INTERVAL_S=15
  RSYNC_INTERVAL_S=300

Behavior:
  - launches the mar24 campaign runner in the background
  - prints compact progress for each expected run directory
  - rsyncs any existing run directories to lxplus periodically
  - does one final rsync after the runner exits
EOF
}

if [[ "$MODE" == "-h" || "$MODE" == "--help" || -z "$MODE" || -z "$TECH" ]]; then
  usage
  exit 0
fi

if [[ ! -f "$RUNNER" ]]; then
  echo "Runner not found: $RUNNER" >&2
  exit 1
fi

RUN_DIRS=()
while IFS= read -r line; do
  [[ -n "$line" ]] && RUN_DIRS+=("$line")
done < <(PRINT_OUTPUTS=1 bash "$RUNNER" "$MODE" "$TECH")

if [[ "${#RUN_DIRS[@]}" -eq 0 ]]; then
  echo "No run directories resolved for mode=$MODE tech=$TECH" >&2
  exit 1
fi

timestamp() {
  date '+%Y-%m-%d %H:%M:%S'
}

saturation_expected_points() {
  local start=500 stop=4095 step=50
  local count last
  count=$(( (stop - start) / step + 1 ))
  last=$(( start + (count - 1) * step ))
  if [[ "$last" -ne "$stop" ]]; then
    count=$((count + 1))
  fi
  echo "$count"
}

vgain_expected_groups() {
  local run_dir="$1"
  case "$(basename "$run_dir")" in
    *_hd_*)
      echo $(( ((2500 - 500) / 100 + 1) * 4 ))
      ;;
    *)
      echo $(( ((2800 - 500) / 100 + 1) * 4 ))
      ;;
  esac
}

run_kind() {
  local run_dir="$1"
  case "$(basename "$run_dir")" in
    *_vgain_scan_*) echo "vgain" ;;
    *) echo "saturation" ;;
  esac
}

progress_line() {
  local run_dir="$1"
  local label expected done summary_file log_file status snapshot

  label="$(basename "$run_dir")"
  if [[ ! -d "$run_dir" ]]; then
    printf 'pending   %s\n' "$label"
    return 0
  fi

  case "$(run_kind "$run_dir")" in
    vgain)
      summary_file="$run_dir/scan_summary.tsv"
      expected="$(vgain_expected_groups "$run_dir")"
      log_file="$run_dir/scan_metadata.txt"
      if [[ -f "$summary_file" ]]; then
        done="$(awk 'END{print NR-1}' "$summary_file" 2>/dev/null || echo 0)"
      else
        done=0
      fi
      status="running"
      if [[ "$done" -ge "$expected" ]]; then
        status="done"
      fi
      printf '%-8s %3s/%-3s groups  %s\n' "$status" "$done" "$expected" "$label"
      ;;
    saturation)
      expected="$(saturation_expected_points)"
      done=0
      if [[ -f "$run_dir/scan_manifest.json" ]]; then
        snapshot="$("$PYTHON" "$ROOT_DIR/client/dynamic_range_led/monitor_led_run.py" "$run_dir" --once --json 2>/dev/null || true)"
        if [[ -n "$snapshot" ]]; then
          done="$(printf '%s' "$snapshot" | "$PYTHON" -c 'import json,sys; data=json.load(sys.stdin); print(data.get("done_points", 0))' 2>/dev/null || echo 0)"
          expected="$(printf '%s' "$snapshot" | "$PYTHON" -c 'import json,sys; data=json.load(sys.stdin); print(data.get("planned_points") or 72)' 2>/dev/null || echo "$expected")"
        fi
      elif [[ -f "$run_dir/summary_by_point.csv" ]]; then
        done="$(awk 'END{print NR-1}' "$run_dir/summary_by_point.csv" 2>/dev/null || echo 0)"
      fi
      status="running"
      if [[ "$done" -ge "$expected" ]]; then
        status="done"
      fi
      printf '%-8s %3s/%-3s points  %s\n' "$status" "$done" "$expected" "$label"
      ;;
  esac
}

sync_once() {
  [[ "$SYNC_TO_LXPLUS" != "1" ]] && return 0
  local run_dir run_name
  for run_dir in "${RUN_DIRS[@]}"; do
    [[ -d "$run_dir" ]] || continue
    run_name="$(basename "$run_dir")"
    ssh "${LXPLUS_USER}@lxplus.cern.ch" "mkdir -p '$LXBASE/$run_name'" >/dev/null 2>&1 || true
    rsync -az --partial --append-verify \
      "$run_dir/" \
      "${LXPLUS_USER}@lxplus.cern.ch:$LXBASE/$run_name/" >/dev/null 2>&1 || true
  done
}

mkdir -p "$RUN_LOG_DIR"
SUP_LOG="$RUN_LOG_DIR/$(date +%Y%m%d_%H%M%S)_mar24_supervisor_${MODE}_${TECH}.log"

echo "Run log: $SUP_LOG"
echo "Expected runs:"
printf '  %s\n' "${RUN_DIRS[@]}"

bash "$RUNNER" "$MODE" "$TECH" >"$SUP_LOG" 2>&1 &
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
  tail -n 8 "$SUP_LOG" 2>/dev/null || true
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
