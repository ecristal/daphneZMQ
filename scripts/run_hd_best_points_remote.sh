#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

CONTROL_HOST="${CONTROL_HOST:-10.73.137.161}"
CONTROL_PORT="${CONTROL_PORT:-40001}"
LED_HOST="${LED_HOST:-10.73.137.61}"
LED_PORT="${LED_PORT:-55002}"
LED_CONFIG="${LED_CONFIG:-$ROOT_DIR/configs/led_run_defaults.json}"
ROUTE="${ROUTE:-mezz/0}"

VGAIN="${VGAIN:-500}"
OFFSET="${OFFSET:-2200}"
WAVEFORMS="${WAVEFORMS:-15000}"
WAVEFORM_LEN="${WAVEFORM_LEN:-1024}"
TIMEOUT_MS="${TIMEOUT_MS:-30000}"
CHARGE_WINDOWS_JSON="${CHARGE_WINDOWS_JSON:-$ROOT_DIR/client/dynamic_range_led/runs/calibration/charge_windows.json}"

HD_BIAS_AFE0_DAC="${HD_BIAS_AFE0_DAC:-1201}"
HD_BIAS_AFE1_DAC="${HD_BIAS_AFE1_DAC:-857}"

LED_CHANNEL_MASK="${LED_CHANNEL_MASK:-1}"
LED_NUMBER_CHANNELS="${LED_NUMBER_CHANNELS:-12}"
LED_PULSE_WIDTH_TICKS="${LED_PULSE_WIDTH_TICKS:-1}"
SETTLE_S="${SETTLE_S:-0.5}"
SCAN_WAVELENGTH="${SCAN_WAVELENGTH:-270}"
DRY_RUN="${DRY_RUN:-0}"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_BASE="${OUTPUT_BASE:-$ROOT_DIR/client/dynamic_range_led/runs/${STAMP}_mar14_best_hd_points_remote}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0")

Replays the March 14 HD "best points" remotely:
  ch12 @ 1150
  ch13 @ 1150
  ch14 @ 1200
  ch15 @ 1200

Environment overrides:
  CONTROL_HOST=10.73.137.161
  CONTROL_PORT=40001
  LED_HOST=10.73.137.61
  LED_PORT=55002
  LED_CONFIG=$ROOT_DIR/configs/led_run_defaults.json
  ROUTE=mezz/0
  VGAIN=500
  OFFSET=2200
  WAVEFORMS=15000
  WAVEFORM_LEN=1024
  TIMEOUT_MS=30000
  CHARGE_WINDOWS_JSON=$ROOT_DIR/client/dynamic_range_led/runs/calibration/charge_windows.json
  HD_BIAS_AFE0_DAC=1201
  HD_BIAS_AFE1_DAC=857
  LED_CHANNEL_MASK=1
  LED_NUMBER_CHANNELS=12
  LED_PULSE_WIDTH_TICKS=1
  SETTLE_S=0.5
  SCAN_WAVELENGTH=270
  DRY_RUN=1
  OUTPUT_BASE=$ROOT_DIR/client/dynamic_range_led/runs/<run_name>
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

run_logged() {
  local logfile="$1"
  shift
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '+'
    printf ' %q' "$@"
    printf ' > %q 2>&1\n' "$logfile"
    return 0
  fi
  "$@" >"$logfile" 2>&1
}

sleep_if_needed() {
  local seconds="$1"
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  case "$seconds" in
    0|0.0|0.00) return 0 ;;
  esac
  sleep "$seconds"
}

configure_fe() {
  local logfile="$1"
  local cmd=(
    "$PYTHON"
    "$ROOT_DIR/client/configure_fe_min_v2.py"
    --ip "$CONTROL_HOST"
    --port "$CONTROL_PORT"
    --route "$ROUTE"
    --full
    -vgain "$VGAIN"
    -ch_offset "$OFFSET"
    -lpf_cutoff 10
    -pga_clamp_level '0 dBFS'
    -pga_gain_control '24 dB'
    -lna_gain_control '12 dB'
    -lna_input_clamp auto
    -align_afes
    --adc_resolution 0
    --timeout "$TIMEOUT_MS"
    --cfg-timeout-ms "$TIMEOUT_MS"
    --afe-bias-dac "0:$HD_BIAS_AFE0_DAC"
    --afe-bias-dac "1:$HD_BIAS_AFE1_DAC"
  )
  run_logged "$logfile" "${cmd[@]}"
}

run_point() {
  local out_dir="$1"
  local channel="$2"
  local intensity="$3"
  local cmd=(
    "$PYTHON"
    "$ROOT_DIR/client/dynamic_range_led/scan_led_intensity_charge.py"
    --output-dir "$out_dir"
    --channels "$channel"
    --host "$CONTROL_HOST"
    --port "$CONTROL_PORT"
    --route "$ROUTE"
    --waveforms "$WAVEFORMS"
    --waveform-len "$WAVEFORM_LEN"
    --timeout-ms "$TIMEOUT_MS"
    --scan-wavelength "$SCAN_WAVELENGTH"
    --intensity-start "$intensity"
    --intensity-stop "$intensity"
    --intensity-step 50
    --charge-windows-json "$CHARGE_WINDOWS_JSON"
    --led-config "$LED_CONFIG"
    --led-host "$LED_HOST"
    --led-port "$LED_PORT"
    --led-channel-mask "$LED_CHANNEL_MASK"
    --led-number-channels "$LED_NUMBER_CHANNELS"
    --pulse-width-ticks "$LED_PULSE_WIDTH_TICKS"
    --settle-s "$SETTLE_S"
  )
  if [[ "$DRY_RUN" == "1" ]]; then
    cmd+=(--dry-run)
  fi
  run_logged "$out_dir/run.log" "${cmd[@]}"
}

cd "$ROOT_DIR"
mkdir -p "$OUTPUT_BASE"

cat >"$OUTPUT_BASE/run_metadata.txt" <<EOF
control_host=$CONTROL_HOST
control_port=$CONTROL_PORT
led_host=$LED_HOST
led_port=$LED_PORT
route=$ROUTE
vgain=$VGAIN
offset=$OFFSET
waveforms=$WAVEFORMS
waveform_len=$WAVEFORM_LEN
timeout_ms=$TIMEOUT_MS
charge_windows_json=$CHARGE_WINDOWS_JSON
hd_bias_afe0_dac=$HD_BIAS_AFE0_DAC
hd_bias_afe1_dac=$HD_BIAS_AFE1_DAC
led_config=$LED_CONFIG
led_channel_mask=$LED_CHANNEL_MASK
led_number_channels=$LED_NUMBER_CHANNELS
led_pulse_width_ticks=$LED_PULSE_WIDTH_TICKS
settle_s=$SETTLE_S
scan_wavelength=$SCAN_WAVELENGTH
output_base=$OUTPUT_BASE
dry_run=$DRY_RUN
EOF

echo "Output base: $OUTPUT_BASE"
echo
echo "==> configure FE"
configure_fe "$OUTPUT_BASE/configure.log"
sleep_if_needed "$SETTLE_S"

echo "==> ch12 intensity=1150"
mkdir -p "$OUTPUT_BASE/ch12_i1150"
run_point "$OUTPUT_BASE/ch12_i1150" 12 1150

echo "==> ch13 intensity=1150"
mkdir -p "$OUTPUT_BASE/ch13_i1150"
run_point "$OUTPUT_BASE/ch13_i1150" 13 1150

echo "==> ch14 intensity=1200"
mkdir -p "$OUTPUT_BASE/ch14_i1200"
run_point "$OUTPUT_BASE/ch14_i1200" 14 1200

echo "==> ch15 intensity=1200"
mkdir -p "$OUTPUT_BASE/ch15_i1200"
run_point "$OUTPUT_BASE/ch15_i1200" 15 1200

echo
echo "HD best-point replay completed."
echo "Data saved under: $OUTPUT_BASE"
