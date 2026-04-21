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

CHANNELS="${CHANNELS:-12,13,14,15}"
INTENSITY_START="${INTENSITY_START:-1000}"
INTENSITY_STOP="${INTENSITY_STOP:-1160}"
INTENSITY_STEP="${INTENSITY_STEP:-20}"

LED_CHANNEL_MASK="${LED_CHANNEL_MASK:-1}"
LED_NUMBER_CHANNELS="${LED_NUMBER_CHANNELS:-12}"
LED_PULSE_WIDTH_TICKS="${LED_PULSE_WIDTH_TICKS:-1}"
SETTLE_S="${SETTLE_S:-0.5}"
SCAN_WAVELENGTH="${SCAN_WAVELENGTH:-270}"
DRY_RUN="${DRY_RUN:-0}"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_BASE="${OUTPUT_BASE:-$ROOT_DIR/client/dynamic_range_led/runs/${STAMP}_hd_intensity_scan_remote}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0")

Runs a shared LED intensity scan over the HD channels with the March 14 FE setup.

Defaults:
  CHANNELS=12,13,14,15
  INTENSITY_START=1000
  INTENSITY_STOP=1160
  INTENSITY_STEP=20
  VGAIN=500
  OFFSET=2200
  WAVEFORMS=15000
  WAVEFORM_LEN=1024
  HD_BIAS_AFE0_DAC=1201
  HD_BIAS_AFE1_DAC=857

Environment overrides:
  CONTROL_HOST=10.73.137.161
  CONTROL_PORT=40001
  LED_HOST=10.73.137.61
  LED_PORT=55002
  LED_CONFIG=$ROOT_DIR/configs/led_run_defaults.json
  ROUTE=mezz/0
  CHARGE_WINDOWS_JSON=$ROOT_DIR/client/dynamic_range_led/runs/calibration/charge_windows.json
  OUTPUT_BASE=$ROOT_DIR/client/dynamic_range_led/runs/<run_name>
  DRY_RUN=1
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

cd "$ROOT_DIR"
mkdir -p "$OUTPUT_BASE"

cat >"$OUTPUT_BASE/run_metadata.txt" <<EOF
control_host=$CONTROL_HOST
control_port=$CONTROL_PORT
led_host=$LED_HOST
led_port=$LED_PORT
led_config=$LED_CONFIG
route=$ROUTE
vgain=$VGAIN
offset=$OFFSET
waveforms=$WAVEFORMS
waveform_len=$WAVEFORM_LEN
timeout_ms=$TIMEOUT_MS
charge_windows_json=$CHARGE_WINDOWS_JSON
hd_bias_afe0_dac=$HD_BIAS_AFE0_DAC
hd_bias_afe1_dac=$HD_BIAS_AFE1_DAC
channels=$CHANNELS
intensity_start=$INTENSITY_START
intensity_stop=$INTENSITY_STOP
intensity_step=$INTENSITY_STEP
scan_wavelength=$SCAN_WAVELENGTH
settle_s=$SETTLE_S
dry_run=$DRY_RUN
EOF

echo "Output base: $OUTPUT_BASE"
echo
echo "==> configure FE"

CONFIGURE_CMD=(
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

printf '+'
printf ' %q' "${CONFIGURE_CMD[@]}"
printf '\n'
if [[ "$DRY_RUN" != "1" ]]; then
  "${CONFIGURE_CMD[@]}" | tee "$OUTPUT_BASE/configure.log"
fi

echo
echo "==> scan channels=$CHANNELS intensities=${INTENSITY_START}:${INTENSITY_STEP}:${INTENSITY_STOP}"

SCAN_CMD=(
  "$PYTHON"
  "$ROOT_DIR/client/dynamic_range_led/scan_led_intensity_charge.py"
  --output-dir "$OUTPUT_BASE"
  --channels "$CHANNELS"
  --host "$CONTROL_HOST"
  --port "$CONTROL_PORT"
  --route "$ROUTE"
  --waveforms "$WAVEFORMS"
  --waveform-len "$WAVEFORM_LEN"
  --timeout-ms "$TIMEOUT_MS"
  --scan-wavelength "$SCAN_WAVELENGTH"
  --intensity-start "$INTENSITY_START"
  --intensity-stop "$INTENSITY_STOP"
  --intensity-step "$INTENSITY_STEP"
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
  SCAN_CMD+=(--dry-run)
fi

printf '+'
printf ' %q' "${SCAN_CMD[@]}"
printf '\n'
if [[ "$DRY_RUN" != "1" ]]; then
  "${SCAN_CMD[@]}" | tee "$OUTPUT_BASE/scan.log"
fi

echo
echo "HD intensity scan completed."
echo "Data saved under: $OUTPUT_BASE"
