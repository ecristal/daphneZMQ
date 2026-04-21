#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/utils/run_client_via_tunnel.sh"

EXPECTED_HOST="${EXPECTED_HOST:-np04-srv-017}"
BOARD="${BOARD:-daphne-13}"
ROUTE="${ROUTE:-mezz/0}"

VGAIN="${VGAIN:-1000}"
OFFSET="${OFFSET:-2275}"
BIASCTRL_DAC="${BIASCTRL_DAC:-0}"
AFE_BIAS_OVERRIDES="${AFE_BIAS_OVERRIDES:-0:0,1:0,2:0,3:0,4:0}"

CHANNELS="${CHANNELS:-16,17,18,19}"
WAVEFORMS="${WAVEFORMS:-15000}"
CALIBRATION_WAVEFORMS="${CALIBRATION_WAVEFORMS:-128}"
WAVEFORM_LEN="${WAVEFORM_LEN:-1024}"
TIMEOUT_MS="${TIMEOUT_MS:-30000}"

INTENSITY_START="${INTENSITY_START:-800}"
INTENSITY_STOP="${INTENSITY_STOP:-1000}"
INTENSITY_STEP="${INTENSITY_STEP:-10}"
CALIBRATION_INTENSITY="${CALIBRATION_INTENSITY:-1000}"

LED_CLIENT="${LED_CLIENT:-$ROOT_DIR/client/ssp_led_run}"
LED_STOP_CLIENT="${LED_STOP_CLIENT:-$ROOT_DIR/client/ssp_led_stop}"
LED_CONFIG="${LED_CONFIG:-$ROOT_DIR/configs/led_run_defaults.json}"
LED_HOST="${LED_HOST:-10.73.137.61}"
LED_PORT="${LED_PORT:-55001}"
LED_CHANNEL_MASK="${LED_CHANNEL_MASK:-1}"
LED_NUMBER_CHANNELS="${LED_NUMBER_CHANNELS:-12}"
LED_PULSE_WIDTH_TICKS="${LED_PULSE_WIDTH_TICKS:-2}"
LED_TIMEOUT_S="${LED_TIMEOUT_S:-5.0}"
LED_SSH_TUNNEL="${LED_SSH_TUNNEL:-}"
LED_SSH_TUNNEL_REMOTE_HOST="${LED_SSH_TUNNEL_REMOTE_HOST:-10.73.137.61}"
LED_SSH_TUNNEL_REMOTE_PORT="${LED_SSH_TUNNEL_REMOTE_PORT:-55001}"

SCAN_WAVELENGTH="${SCAN_WAVELENGTH:-270}"
FIXED_BIAS_367NM="${FIXED_BIAS_367NM:-0}"
SETTLE_S="${SETTLE_S:-0.5}"
CHARGE_WINDOWS_JSON="${CHARGE_WINDOWS_JSON:-}"
DRY_RUN="${DRY_RUN:-0}"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_BASE="${OUTPUT_BASE:-$ROOT_DIR/client/dynamic_range_led/runs/${STAMP}_sof_led_scan_remote}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0")

Run this on ${EXPECTED_HOST}. It configures the FE through:
  $ROOT_DIR/utils/run_client_via_tunnel.sh ${BOARD}
and launches the LED intensity scan for SoF channels 16-19.

Defaults:
  CHANNELS=16,17,18,19
  VGAIN=1000
  OFFSET=2275
  BIASCTRL_DAC=0
  AFE_BIAS_OVERRIDES=0:0,1:0,2:0,3:0,4:0
  INTENSITY_START=800
  INTENSITY_STOP=1000
  INTENSITY_STEP=10
  WAVEFORMS=15000
  CALIBRATION_WAVEFORMS=128
  WAVEFORM_LEN=1024
  LED_HOST=10.73.137.61
  LED_PORT=55001
  LED_CHANNEL_MASK=1
  LED_NUMBER_CHANNELS=12
  LED_PULSE_WIDTH_TICKS=2
  SCAN_WAVELENGTH=270
  FIXED_BIAS_367NM=0
  CALIBRATION_INTENSITY=1000

Notes:
  - If CHARGE_WINDOWS_JSON is empty, the scan driver takes one short calibration capture
    at CALIBRATION_INTENSITY before the 800:10:1000 sweep.
  - Because this is meant to run on ${EXPECTED_HOST}, LED_SSH_TUNNEL is empty by default.
    If you still want the LED client to tunnel, set LED_SSH_TUNNEL and the remote host/port.

Environment overrides:
  EXPECTED_HOST=np04-srv-017
  BOARD=daphne-13
  ROUTE=mezz/0
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

if [[ ! -x "$RUNNER" ]]; then
  echo "Tunnel runner not found or not executable: $RUNNER" >&2
  exit 2
fi

if [[ ! -x "$LED_CLIENT" ]]; then
  echo "LED client not found or not executable: $LED_CLIENT" >&2
  exit 2
fi

if [[ ! -x "$LED_STOP_CLIENT" ]]; then
  echo "LED stop client not found or not executable: $LED_STOP_CLIENT" >&2
  exit 2
fi

current_host="$(hostname -s 2>/dev/null || true)"
if [[ -n "$EXPECTED_HOST" && "$current_host" != "$EXPECTED_HOST" ]]; then
  echo "Warning: this script is intended to run on $EXPECTED_HOST, current host is ${current_host:-unknown}." >&2
fi

cd "$ROOT_DIR"
mkdir -p "$OUTPUT_BASE"

cat >"$OUTPUT_BASE/run_metadata.txt" <<EOF
expected_host=$EXPECTED_HOST
current_host=$current_host
board=$BOARD
route=$ROUTE
vgain=$VGAIN
offset=$OFFSET
biasctrl_dac=$BIASCTRL_DAC
afe_bias_overrides=$AFE_BIAS_OVERRIDES
channels=$CHANNELS
waveforms=$WAVEFORMS
calibration_waveforms=$CALIBRATION_WAVEFORMS
waveform_len=$WAVEFORM_LEN
timeout_ms=$TIMEOUT_MS
intensity_start=$INTENSITY_START
intensity_stop=$INTENSITY_STOP
intensity_step=$INTENSITY_STEP
calibration_intensity=$CALIBRATION_INTENSITY
led_client=$LED_CLIENT
led_stop_client=$LED_STOP_CLIENT
led_config=$LED_CONFIG
led_host=$LED_HOST
led_port=$LED_PORT
led_channel_mask=$LED_CHANNEL_MASK
led_number_channels=$LED_NUMBER_CHANNELS
led_pulse_width_ticks=$LED_PULSE_WIDTH_TICKS
led_timeout_s=$LED_TIMEOUT_S
led_ssh_tunnel=$LED_SSH_TUNNEL
led_ssh_tunnel_remote_host=$LED_SSH_TUNNEL_REMOTE_HOST
led_ssh_tunnel_remote_port=$LED_SSH_TUNNEL_REMOTE_PORT
scan_wavelength=$SCAN_WAVELENGTH
fixed_bias_367nm=$FIXED_BIAS_367NM
settle_s=$SETTLE_S
charge_windows_json=$CHARGE_WINDOWS_JSON
dry_run=$DRY_RUN
EOF

run_client() {
  "$RUNNER" "$BOARD" "$@"
}

echo "Output base: $OUTPUT_BASE"
echo
echo "==> configure FE on $BOARD"

CONFIGURE_CMD=(
  run_client
  client/configure_fe_min_v2.py
  -vgain "$VGAIN"
  -ch_offset "$OFFSET"
  -lpf_cutoff 10
  -pga_clamp_level '0 dBFS'
  -pga_gain_control '24 dB'
  -lna_gain_control '12 dB'
  -lna_input_clamp auto
  --full
  -align_afes
  --adc_resolution 0
  --timeout "$TIMEOUT_MS"
  --cfg-timeout-ms "$TIMEOUT_MS"
  --route "$ROUTE"
  --biasctrl-dac "$BIASCTRL_DAC"
)

if [[ -n "$AFE_BIAS_OVERRIDES" ]]; then
  CONFIGURE_CMD+=(--afe-bias-dac "$AFE_BIAS_OVERRIDES")
fi

printf '+'
printf ' %q' "${CONFIGURE_CMD[@]}"
printf '\n'
if [[ "$DRY_RUN" != "1" ]]; then
  "${CONFIGURE_CMD[@]}" | tee "$OUTPUT_BASE/configure.log"
fi

echo
echo "==> scan channels=$CHANNELS intensities=${INTENSITY_START}:${INTENSITY_STEP}:${INTENSITY_STOP}"

SCAN_CMD=(
  run_client
  client/dynamic_range_led/scan_led_intensity_charge.py
  --output-dir "$OUTPUT_BASE"
  --channels "$CHANNELS"
  --scan-wavelength "$SCAN_WAVELENGTH"
  --intensity-start "$INTENSITY_START"
  --intensity-stop "$INTENSITY_STOP"
  --intensity-step "$INTENSITY_STEP"
  --calibration-intensity "$CALIBRATION_INTENSITY"
  --waveforms "$WAVEFORMS"
  --calibration-waveforms "$CALIBRATION_WAVEFORMS"
  --waveform-len "$WAVEFORM_LEN"
  --timeout-ms "$TIMEOUT_MS"
  --route "$ROUTE"
  --led-client "$LED_CLIENT"
  --led-stop-client "$LED_STOP_CLIENT"
  --led-config "$LED_CONFIG"
  --led-host "$LED_HOST"
  --led-port "$LED_PORT"
  --led-timeout-s "$LED_TIMEOUT_S"
  --led-channel-mask "$LED_CHANNEL_MASK"
  --led-number-channels "$LED_NUMBER_CHANNELS"
  --pulse-width-ticks "$LED_PULSE_WIDTH_TICKS"
  --fixed-bias-367nm "$FIXED_BIAS_367NM"
  --settle-s "$SETTLE_S"
)

if [[ -n "$CHARGE_WINDOWS_JSON" ]]; then
  SCAN_CMD+=(--charge-windows-json "$CHARGE_WINDOWS_JSON")
fi

if [[ -n "$LED_SSH_TUNNEL" ]]; then
  SCAN_CMD+=(
    --led-ssh-tunnel "$LED_SSH_TUNNEL"
    --led-ssh-tunnel-remote-host "$LED_SSH_TUNNEL_REMOTE_HOST"
    --led-ssh-tunnel-remote-port "$LED_SSH_TUNNEL_REMOTE_PORT"
  )
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
echo "SoF LED scan completed."
echo "Data saved under: $OUTPUT_BASE"
