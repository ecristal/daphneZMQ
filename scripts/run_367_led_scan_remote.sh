#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

CONTROL_HOST="${CONTROL_HOST:-10.73.137.161}"
CONTROL_PORT="${CONTROL_PORT:-40001}"
ROUTE="${ROUTE:-mezz/0}"

LED_HOST="${LED_HOST:-10.73.137.61}"
LED_PORT="${LED_PORT:-55002}"
LED_CONFIG="${LED_CONFIG:-$ROOT_DIR/configs/led_run_defaults.json}"
LED_SSH_TUNNEL="${LED_SSH_TUNNEL:-}"
LED_SSH_TUNNEL_REMOTE_HOST="${LED_SSH_TUNNEL_REMOTE_HOST:-10.73.137.61}"
LED_SSH_TUNNEL_REMOTE_PORT="${LED_SSH_TUNNEL_REMOTE_PORT:-55001}"
LED_CHANNEL_MASK="${LED_CHANNEL_MASK:-512}"
LED_NUMBER_CHANNELS="${LED_NUMBER_CHANNELS:-12}"
LED_PULSE_WIDTH_TICKS="${LED_PULSE_WIDTH_TICKS:-4}"
LED_TIMEOUT_S="${LED_TIMEOUT_S:-5}"

CHANNELS="${CHANNELS:-12,13,14,15}"
VGAIN="${VGAIN:-2100}"
CH_OFFSET="${CH_OFFSET:-1500}"
WAVEFORM_LEN="${WAVEFORM_LEN:-1024}"
WAVEFORMS="${WAVEFORMS:-500}"
TIMEOUT_MS="${TIMEOUT_MS:-30000}"

BIASCTRL_DAC="${BIASCTRL_DAC:-4095}"
AFE_BIAS_OVERRIDES="${AFE_BIAS_OVERRIDES:-1:810}"
ADC_RESOLUTION="${ADC_RESOLUTION:-0}"
LPF_CUTOFF="${LPF_CUTOFF:-10}"
PGA_CLAMP_LEVEL="${PGA_CLAMP_LEVEL:-0 dBFS}"
PGA_GAIN_CONTROL="${PGA_GAIN_CONTROL:-24 dB}"
LNA_GAIN_CONTROL="${LNA_GAIN_CONTROL:-12 dB}"
LNA_INPUT_CLAMP="${LNA_INPUT_CLAMP:-auto}"
ALIGN_AFES="${ALIGN_AFES:-1}"

SCAN_WAVELENGTH="${SCAN_WAVELENGTH:-367}"
INTENSITY_START="${INTENSITY_START:-1095}"
INTENSITY_STOP="${INTENSITY_STOP:-4095}"
INTENSITY_STEP="${INTENSITY_STEP:-50}"
FIXED_BIAS_270NM="${FIXED_BIAS_270NM:-4095}"
FIXED_BIAS_367NM="${FIXED_BIAS_367NM:-0}"
CALIBRATION_INTENSITY="${CALIBRATION_INTENSITY:-3000}"
CALIBRATION_WAVEFORMS="${CALIBRATION_WAVEFORMS:-128}"
SETTLE_S="${SETTLE_S:-0.5}"
CHARGE_WINDOWS_JSON="${CHARGE_WINDOWS_JSON:-}"
DRY_RUN="${DRY_RUN:-0}"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_BASE="${OUTPUT_BASE:-$ROOT_DIR/client/dynamic_range_led/runs/${STAMP}_367nm_scan_remote}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0")

Direct remote 367nm LED scan on np04-srv-017.

Defaults:
  CONTROL_HOST=10.73.137.161
  CONTROL_PORT=40001
  LED_HOST=10.73.137.61
  LED_PORT=55002
  LED_CONFIG=$ROOT_DIR/configs/led_run_defaults.json
  LED_SSH_TUNNEL=
  LED_SSH_TUNNEL_REMOTE_HOST=10.73.137.61
  LED_SSH_TUNNEL_REMOTE_PORT=55001
  LED_CHANNEL_MASK=512
  LED_NUMBER_CHANNELS=12
  LED_PULSE_WIDTH_TICKS=4
  CHANNELS=12,13,14,15
  VGAIN=2100
  CH_OFFSET=1500
  WAVEFORM_LEN=1024
  WAVEFORMS=500
  BIASCTRL_DAC=4095
  AFE_BIAS_OVERRIDES=1:810
  SCAN_WAVELENGTH=367
  INTENSITY_START=1095
  INTENSITY_STOP=4095
  INTENSITY_STEP=50
  FIXED_BIAS_270NM=4095
  FIXED_BIAS_367NM=0
  CALIBRATION_INTENSITY=3000
  CALIBRATION_WAVEFORMS=128
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

echo "Output base: $OUTPUT_BASE"
cat >"$OUTPUT_BASE/run_metadata.txt" <<EOF
control_host=$CONTROL_HOST
control_port=$CONTROL_PORT
route=$ROUTE
led_host=$LED_HOST
led_port=$LED_PORT
led_config=$LED_CONFIG
led_ssh_tunnel=$LED_SSH_TUNNEL
led_ssh_tunnel_remote_host=$LED_SSH_TUNNEL_REMOTE_HOST
led_ssh_tunnel_remote_port=$LED_SSH_TUNNEL_REMOTE_PORT
led_channel_mask=$LED_CHANNEL_MASK
led_number_channels=$LED_NUMBER_CHANNELS
led_pulse_width_ticks=$LED_PULSE_WIDTH_TICKS
channels=$CHANNELS
vgain=$VGAIN
ch_offset=$CH_OFFSET
waveform_len=$WAVEFORM_LEN
waveforms=$WAVEFORMS
timeout_ms=$TIMEOUT_MS
biasctrl_dac=$BIASCTRL_DAC
afe_bias_overrides=$AFE_BIAS_OVERRIDES
scan_wavelength=$SCAN_WAVELENGTH
intensity_start=$INTENSITY_START
intensity_stop=$INTENSITY_STOP
intensity_step=$INTENSITY_STEP
fixed_bias_270nm=$FIXED_BIAS_270NM
fixed_bias_367nm=$FIXED_BIAS_367NM
calibration_intensity=$CALIBRATION_INTENSITY
calibration_waveforms=$CALIBRATION_WAVEFORMS
charge_windows_json=$CHARGE_WINDOWS_JSON
dry_run=$DRY_RUN
EOF

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
  -ch_offset "$CH_OFFSET"
  -lpf_cutoff "$LPF_CUTOFF"
  -pga_clamp_level "$PGA_CLAMP_LEVEL"
  -pga_gain_control "$PGA_GAIN_CONTROL"
  -lna_gain_control "$LNA_GAIN_CONTROL"
  -lna_input_clamp "$LNA_INPUT_CLAMP"
  --adc_resolution "$ADC_RESOLUTION"
  --timeout "$TIMEOUT_MS"
  --cfg-timeout-ms "$TIMEOUT_MS"
  --biasctrl-dac "$BIASCTRL_DAC"
  --afe-bias-dac "$AFE_BIAS_OVERRIDES"
)
if [[ "$ALIGN_AFES" == "1" ]]; then
  CONFIGURE_CMD+=(-align_afes)
fi
printf '+'
printf ' %q' "${CONFIGURE_CMD[@]}"
printf '\n'
if [[ "$DRY_RUN" != "1" ]]; then
  "${CONFIGURE_CMD[@]}" | tee "$OUTPUT_BASE/configure.log"
fi

echo
echo "==> scan 367nm intensities ${INTENSITY_START}:${INTENSITY_STEP}:${INTENSITY_STOP}"
SCAN_CMD=(
  "$PYTHON"
  "$ROOT_DIR/client/dynamic_range_led/scan_led_intensity_charge.py"
  --output-dir "$OUTPUT_BASE"
  --channels "$CHANNELS"
  --host "$CONTROL_HOST"
  --port "$CONTROL_PORT"
  --route "$ROUTE"
  --waveforms "$WAVEFORMS"
  --calibration-waveforms "$CALIBRATION_WAVEFORMS"
  --waveform-len "$WAVEFORM_LEN"
  --timeout-ms "$TIMEOUT_MS"
  --scan-wavelength "$SCAN_WAVELENGTH"
  --intensity-start "$INTENSITY_START"
  --intensity-stop "$INTENSITY_STOP"
  --intensity-step "$INTENSITY_STEP"
  --calibration-intensity "$CALIBRATION_INTENSITY"
  --led-config "$LED_CONFIG"
  --led-host "$LED_HOST"
  --led-port "$LED_PORT"
  --led-timeout-s "$LED_TIMEOUT_S"
  --led-channel-mask "$LED_CHANNEL_MASK"
  --led-number-channels "$LED_NUMBER_CHANNELS"
  --pulse-width-ticks "$LED_PULSE_WIDTH_TICKS"
  --fixed-bias-270nm "$FIXED_BIAS_270NM"
  --fixed-bias-367nm "$FIXED_BIAS_367NM"
  --settle-s "$SETTLE_S"
)
if [[ -n "$LED_SSH_TUNNEL" ]]; then
  SCAN_CMD+=(
    --led-ssh-tunnel "$LED_SSH_TUNNEL"
    --led-ssh-tunnel-remote-host "$LED_SSH_TUNNEL_REMOTE_HOST"
    --led-ssh-tunnel-remote-port "$LED_SSH_TUNNEL_REMOTE_PORT"
  )
fi
if [[ -n "$CHARGE_WINDOWS_JSON" ]]; then
  SCAN_CMD+=(--charge-windows-json "$CHARGE_WINDOWS_JSON")
fi
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
echo "367nm LED scan completed."
echo "Data saved under: $OUTPUT_BASE"
