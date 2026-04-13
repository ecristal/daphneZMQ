#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

SSH_TARGET="${SSH_TARGET:-pi@10.71.87.100}"
SSH_OPTIONS="${SSH_OPTIONS:-}"
PPULSE_TEMPLATE="${PPULSE_TEMPLATE:-ppulse run-trigger -d {d}}"
PPULSE_STARTUP_S="${PPULSE_STARTUP_S:-0.5}"

OSC_IP="${OSC_IP:-127.0.0.1}"
OSC_PORT="${OSC_PORT:-9876}"
OSC_ROUTE="${OSC_ROUTE:-mezz/0}"
OSC_CHANNELS="${OSC_CHANNELS:-0}"
WAVEFORM_LEN="${WAVEFORM_LEN:-2048}"
MAX_WAVEFORMS="${MAX_WAVEFORMS:-100}"
OSC_PERIOD_MS="${OSC_PERIOD_MS:-20}"
OSC_TIMEOUT_MS="${OSC_TIMEOUT_MS:-1000}"
OSC_SAMPLING_RATE_HZ="${OSC_SAMPLING_RATE_HZ:-62500000}"
SOFTWARE_TRIGGER="${SOFTWARE_TRIGGER:-0}"
ENABLE_FFT="${ENABLE_FFT:-0}"
FFT_AVG_WAVES="${FFT_AVG_WAVES:-200}"
FFT_CHANNEL="${FFT_CHANNEL:-}"
FFT_KEEP_DC="${FFT_KEEP_DC:-0}"
FFT_LINEAR_X="${FFT_LINEAR_X:-0}"
AUTOSCALE="${AUTOSCALE:-0}"

D_START="${D_START:-290}"
D_STOP="${D_STOP:-300}"
D_STEP="${D_STEP:-1}"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_BASE="${OUTPUT_BASE:-$ROOT_DIR/client/osc_runs/${STAMP}_ppulse_dscan_${D_START}_${D_STOP}}"

SSH_PID=""
OSC_PID=""
CURRENT_D=""

usage() {
  cat <<EOF
Usage:
  $(basename "$0")

Runs a ppulse command on a remote Raspberry Pi over SSH and acquires osc data
locally with client/osc.py. One output folder is created per d-setting.

Default scan:
  D_START=290
  D_STOP=300
  D_STEP=1

Default remote command template:
  PPULSE_TEMPLATE='ppulse run-trigger -d {d}'

Default osc settings:
  OSC_IP=127.0.0.1
  OSC_PORT=9876
  OSC_ROUTE=mezz/0
  OSC_CHANNELS=0
  WAVEFORM_LEN=2048
  MAX_WAVEFORMS=100

Environment overrides:
  SSH_TARGET=pi@10.71.87.100
  SSH_OPTIONS='-o BatchMode=yes'
  PPULSE_TEMPLATE='ppulse run-trigger -d {d}'
  PPULSE_STARTUP_S=0.5
  OSC_IP=127.0.0.1
  OSC_PORT=9876
  OSC_ROUTE=mezz/0
  OSC_CHANNELS=0,1,2,3
  WAVEFORM_LEN=2048
  MAX_WAVEFORMS=100
  OSC_PERIOD_MS=20
  OSC_TIMEOUT_MS=1000
  OSC_SAMPLING_RATE_HZ=62500000
  SOFTWARE_TRIGGER=0
  ENABLE_FFT=0
  FFT_AVG_WAVES=200
  FFT_CHANNEL=
  FFT_KEEP_DC=0
  FFT_LINEAR_X=0
  AUTOSCALE=0
  D_START=290
  D_STOP=300
  D_STEP=1
  OUTPUT_BASE=$ROOT_DIR/client/osc_runs/<scan_name>
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

if [[ "$D_STEP" == "0" ]]; then
  echo "D_STEP must be non-zero." >&2
  exit 2
fi

if (( D_STEP > 0 )) && (( D_START > D_STOP )); then
  echo "Positive D_STEP requires D_START <= D_STOP." >&2
  exit 2
fi

if (( D_STEP < 0 )) && (( D_START < D_STOP )); then
  echo "Negative D_STEP requires D_START >= D_STOP." >&2
  exit 2
fi

if (( MAX_WAVEFORMS <= 0 )); then
  echo "MAX_WAVEFORMS must be > 0." >&2
  exit 2
fi

mkdir -p "$OUTPUT_BASE"

build_ssh_args() {
  local -a args
  args=(ssh)
  if [[ -n "$SSH_OPTIONS" ]]; then
    # Intentional word splitting for standard SSH option strings.
    # shellcheck disable=SC2206
    local extra=( $SSH_OPTIONS )
    args+=("${extra[@]}")
  fi
  args+=("$SSH_TARGET")
  printf '%s\n' "${args[@]}"
}

stop_osc() {
  if [[ -n "$OSC_PID" ]] && kill -0 "$OSC_PID" 2>/dev/null; then
    kill "$OSC_PID" 2>/dev/null || true
    wait "$OSC_PID" 2>/dev/null || true
  fi
  OSC_PID=""
}

stop_remote_ppulse() {
  if [[ -n "$SSH_PID" ]] && kill -0 "$SSH_PID" 2>/dev/null; then
    kill "$SSH_PID" 2>/dev/null || true
    wait "$SSH_PID" 2>/dev/null || true
  fi
  SSH_PID=""
}

cleanup() {
  stop_osc
  stop_remote_ppulse
}
trap cleanup EXIT INT TERM

start_remote_ppulse() {
  local d_value="$1"
  local logfile="$2"
  local remote_cmd="${PPULSE_TEMPLATE//\{d\}/$d_value}"
  mapfile -t ssh_cmd < <(build_ssh_args)

  (
    exec "${ssh_cmd[@]}" "bash -s" -- "$remote_cmd" <<'EOF'
set -euo pipefail
cmd="$1"
child_pid=""
cleanup_child() {
  if [[ -n "${child_pid:-}" ]]; then
    kill "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
}
trap cleanup_child EXIT INT TERM HUP
bash -lc "$cmd" &
child_pid=$!
wait "$child_pid"
EOF
  ) >"$logfile" 2>&1 &

  SSH_PID="$!"
}

start_osc() {
  local point_dir="$1"
  local d_value="$2"
  local logfile="$3"
  local -a cmd
  cmd=(
    "$PYTHON"
    "$ROOT_DIR/client/osc.py"
    -ip "$OSC_IP"
    -port "$OSC_PORT"
    --route "$OSC_ROUTE"
    --channels "$OSC_CHANNELS"
    -L "$WAVEFORM_LEN"
    --max_waveforms "$MAX_WAVEFORMS"
    -period_ms "$OSC_PERIOD_MS"
    -timeout_ms "$OSC_TIMEOUT_MS"
    --sampling_rate_hz "$OSC_SAMPLING_RATE_HZ"
    --save_dir "$point_dir"
    --run_label "ppulse d=$d_value"
    --run_notes "remote_command=${PPULSE_TEMPLATE//\{d\}/$d_value}"
  )

  if [[ "$SOFTWARE_TRIGGER" == "1" ]]; then
    cmd+=(-software_trigger)
  fi
  if [[ "$ENABLE_FFT" == "1" ]]; then
    cmd+=(-enable_fft -fft_avg_waves "$FFT_AVG_WAVES")
    if [[ -n "$FFT_CHANNEL" ]]; then
      cmd+=(--fft_channel "$FFT_CHANNEL")
    fi
  fi
  if [[ "$FFT_KEEP_DC" == "1" ]]; then
    cmd+=(--fft_keep_dc)
  fi
  if [[ "$FFT_LINEAR_X" == "1" ]]; then
    cmd+=(--fft_linear_x)
  fi
  if [[ "$AUTOSCALE" == "1" ]]; then
    cmd+=(--autoscale)
  fi

  "${cmd[@]}" >"$logfile" 2>&1 &
  OSC_PID="$!"
}

write_scan_manifest() {
  local manifest="$OUTPUT_BASE/scan_manifest.txt"
  {
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "ssh_target=$SSH_TARGET"
    echo "ppulse_template=$PPULSE_TEMPLATE"
    echo "osc_ip=$OSC_IP"
    echo "osc_port=$OSC_PORT"
    echo "osc_route=$OSC_ROUTE"
    echo "osc_channels=$OSC_CHANNELS"
    echo "waveform_len=$WAVEFORM_LEN"
    echo "max_waveforms=$MAX_WAVEFORMS"
    echo "d_start=$D_START"
    echo "d_stop=$D_STOP"
    echo "d_step=$D_STEP"
  } >"$manifest"
}

write_point_metadata() {
  local point_dir="$1"
  local d_value="$2"
  {
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "d_value=$d_value"
    echo "ssh_target=$SSH_TARGET"
    echo "ppulse_command=${PPULSE_TEMPLATE//\{d\}/$d_value}"
    echo "osc_channels=$OSC_CHANNELS"
    echo "waveform_len=$WAVEFORM_LEN"
    echo "max_waveforms=$MAX_WAVEFORMS"
  } >"$point_dir/scan_point.txt"
}

write_scan_manifest

current_value="$D_START"
while :; do
  CURRENT_D="$current_value"
  point_dir="$OUTPUT_BASE/d_$(printf '%03d' "$current_value")"
  mkdir -p "$point_dir"
  write_point_metadata "$point_dir" "$current_value"

  ppulse_log="$point_dir/ppulse.log"
  osc_log="$point_dir/osc.log"

  echo "[scan] d=$current_value -> $point_dir"
  start_remote_ppulse "$current_value" "$ppulse_log"
  sleep "$PPULSE_STARTUP_S"
  start_osc "$point_dir" "$current_value" "$osc_log"

  osc_status=0
  wait "$OSC_PID" || osc_status=$?
  OSC_PID=""
  stop_remote_ppulse

  if [[ "$osc_status" -ne 0 ]]; then
    echo "[error] osc.py failed at d=$current_value with status $osc_status" >&2
    exit "$osc_status"
  fi

  echo "[done] d=$current_value"

  if (( current_value == D_STOP )); then
    break
  fi
  current_value=$(( current_value + D_STEP ))
  if (( D_STEP > 0 && current_value > D_STOP )); then
    break
  fi
  if (( D_STEP < 0 && current_value < D_STOP )); then
    break
  fi
done

echo "[complete] scan saved under $OUTPUT_BASE"
