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
LED_TIMEOUT_S="${LED_TIMEOUT_S:-5}"
LED_CHANNEL_MASK="${LED_CHANNEL_MASK:-1}"
LED_NUMBER_CHANNELS="${LED_NUMBER_CHANNELS:-12}"
LED_PULSE_WIDTH_TICKS="${LED_PULSE_WIDTH_TICKS:-2}"
LED_RUN_CLIENT="${LED_RUN_CLIENT:-$ROOT_DIR/client/ssp_led_run}"
LED_STOP_CLIENT="${LED_STOP_CLIENT:-$ROOT_DIR/client/ssp_led_stop}"
SCAN_WAVELENGTH="${SCAN_WAVELENGTH:-270}"
LED_FIXED_INTENSITY_270NM="${LED_FIXED_INTENSITY_270NM:-0}"
LED_FIXED_INTENSITY_367NM="${LED_FIXED_INTENSITY_367NM:-0}"

BIAS_AFE="${BIAS_AFE:-0}"
BIAS_VALUES="${BIAS_VALUES:-1130,1143,1156,1169,1182,1195,1208}"
FIXED_AFE_BIAS_OVERRIDES="${FIXED_AFE_BIAS_OVERRIDES:-1:857}"
GROUP_SPECS="${GROUP_SPECS:-0:750;1:750;2:770;3:760}"

VGAIN="${VGAIN:-900}"
CH_OFFSET="${CH_OFFSET:-2275}"
BIASCTRL_DAC="${BIASCTRL_DAC:-1300}"
WAVEFORM_LEN="${WAVEFORM_LEN:-1024}"
WAVEFORMS_PER_POINT="${WAVEFORMS_PER_POINT:-15000}"
TIMEOUT_MS="${TIMEOUT_MS:-30000}"
SETTLE_S="${SETTLE_S:-0.5}"
SAVE_FE_STATE="${SAVE_FE_STATE:-1}"
SOFTWARE_TRIGGER="${SOFTWARE_TRIGGER:-0}"
ALIGN_AFES="${ALIGN_AFES:-0}"

ADC_RESOLUTION="${ADC_RESOLUTION:-0}"
LPF_CUTOFF="${LPF_CUTOFF:-10}"
PGA_CLAMP_LEVEL="${PGA_CLAMP_LEVEL:-0 dBFS}"
PGA_GAIN_CONTROL="${PGA_GAIN_CONTROL:-24 dB}"
LNA_GAIN_CONTROL="${LNA_GAIN_CONTROL:-12 dB}"
LNA_INPUT_CLAMP="${LNA_INPUT_CLAMP:-auto}"

DRY_RUN="${DRY_RUN:-0}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_BASE="${OUTPUT_BASE:-$ROOT_DIR/client/dynamic_range_led/runs/${STAMP}_led_bias_scan_remote}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0")

Direct remote LED bias scan with one FE configure per bias point and one or more
fixed-intensity acquisitions under that FE state.

Environment overrides:
  CONTROL_HOST=10.73.137.161
  CONTROL_PORT=40001
  ROUTE=mezz/0
  LED_HOST=10.73.137.61
  LED_PORT=55002
  LED_CONFIG=$ROOT_DIR/configs/led_run_defaults.json
  LED_SSH_TUNNEL=
  LED_CHANNEL_MASK=1
  LED_NUMBER_CHANNELS=12
  LED_PULSE_WIDTH_TICKS=2
  BIAS_AFE=0
  BIAS_VALUES=1130,1143,1156,1169,1182,1195,1208
  FIXED_AFE_BIAS_OVERRIDES=1:857
  GROUP_SPECS='0:750;1:750;2:770;3:760'
  VGAIN=900
  CH_OFFSET=2275
  BIASCTRL_DAC=1300
  WAVEFORM_LEN=1024
  WAVEFORMS_PER_POINT=15000
  SOFTWARE_TRIGGER=0
  ALIGN_AFES=0
  SAVE_FE_STATE=1
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

LED_ACTIVE=0
EMERGENCY_LED_STOP_LOG="$OUTPUT_BASE/emergency_led_stop.log"

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
  if [[ "$DRY_RUN" != "1" && "$seconds" != "0" && "$seconds" != "0.0" ]]; then
    sleep "$seconds"
  fi
}

cleanup_led() {
  if [[ "$LED_ACTIVE" != "1" || "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  local cmd=(
    "$LED_STOP_CLIENT"
    --host "$LED_HOST"
    --port "$LED_PORT"
    --timeout "$LED_TIMEOUT_S"
  )
  if [[ -n "$LED_SSH_TUNNEL" ]]; then
    cmd+=(
      --ssh-tunnel "$LED_SSH_TUNNEL"
      --ssh-tunnel-remote-host "$LED_SSH_TUNNEL_REMOTE_HOST"
      --ssh-tunnel-remote-port "$LED_SSH_TUNNEL_REMOTE_PORT"
    )
  fi
  {
    echo "[cleanup] attempting emergency LED stop at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    "${cmd[@]}" || true
  } >>"$EMERGENCY_LED_STOP_LOG" 2>&1
}
trap cleanup_led EXIT

combined_afe_bias_arg() {
  local scan_bias="$1"
  local out="${BIAS_AFE}:${scan_bias}"
  if [[ -n "$FIXED_AFE_BIAS_OVERRIDES" ]]; then
    out+=",${FIXED_AFE_BIAS_OVERRIDES}"
  fi
  printf '%s' "$out"
}

configure_point() {
  local scan_bias="$1"
  local logfile="$2"
  local afe_bias_arg
  afe_bias_arg="$(combined_afe_bias_arg "$scan_bias")"
  local cmd=(
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
    --afe-bias-dac "$afe_bias_arg"
  )
  if [[ "$ALIGN_AFES" == "1" ]]; then
    cmd+=(-align_afes)
  fi
  run_logged "$logfile" "${cmd[@]}"
}

capture_fe_state() {
  local point_dir="$1"
  local cmd=(
    "$PYTHON"
    "$ROOT_DIR/client/read_fe_state_v2.py"
    --host "$CONTROL_HOST"
    --port "$CONTROL_PORT"
    --route "$ROUTE"
    --timeout "$TIMEOUT_MS"
    --json
  )
  run_logged "$point_dir/fe_state_readback.json" "${cmd[@]}"
}

start_led() {
  local intensity="$1"
  local logfile="$2"
  local led_270="$LED_FIXED_INTENSITY_270NM"
  local led_367="$LED_FIXED_INTENSITY_367NM"
  if [[ "$SCAN_WAVELENGTH" == "270" ]]; then
    led_270="$intensity"
  else
    led_367="$intensity"
  fi
  local cmd=(
    "$LED_RUN_CLIENT"
    --config "$LED_CONFIG"
    --host "$LED_HOST"
    --port "$LED_PORT"
    --timeout "$LED_TIMEOUT_S"
    --channel-mask "$LED_CHANNEL_MASK"
    --number-channels "$LED_NUMBER_CHANNELS"
    --pulse-width-ticks "$LED_PULSE_WIDTH_TICKS"
    --pulse-bias-percent-270nm "$led_270"
    --pulse-bias-percent-367nm "$led_367"
  )
  if [[ -n "$LED_SSH_TUNNEL" ]]; then
    cmd+=(
      --ssh-tunnel "$LED_SSH_TUNNEL"
      --ssh-tunnel-remote-host "$LED_SSH_TUNNEL_REMOTE_HOST"
      --ssh-tunnel-remote-port "$LED_SSH_TUNNEL_REMOTE_PORT"
    )
  fi
  run_logged "$logfile" "${cmd[@]}"
  LED_ACTIVE=1
}

stop_led() {
  local logfile="$1"
  local cmd=(
    "$LED_STOP_CLIENT"
    --host "$LED_HOST"
    --port "$LED_PORT"
    --timeout "$LED_TIMEOUT_S"
  )
  if [[ -n "$LED_SSH_TUNNEL" ]]; then
    cmd+=(
      --ssh-tunnel "$LED_SSH_TUNNEL"
      --ssh-tunnel-remote-host "$LED_SSH_TUNNEL_REMOTE_HOST"
      --ssh-tunnel-remote-port "$LED_SSH_TUNNEL_REMOTE_PORT"
    )
  fi
  run_logged "$logfile" "${cmd[@]}"
  LED_ACTIVE=0
}

acquire_group() {
  local channels="$1"
  local group_dir="$2"
  local cmd=(
    "$PYTHON"
    "$ROOT_DIR/client/protobuf_acquire_list_channels.py"
    --osc_mode
    -ip "$CONTROL_HOST"
    -port "$CONTROL_PORT"
    -foldername "$group_dir"
    -channel_list "$channels"
    -N "$WAVEFORMS_PER_POINT"
    -L "$WAVEFORM_LEN"
    --timeout_ms "$TIMEOUT_MS"
    --route "$ROUTE"
  )
  if [[ "$SOFTWARE_TRIGGER" == "1" ]]; then
    cmd+=(-software_trigger)
  fi
  run_logged "$group_dir/acquire.log" "${cmd[@]}"
}

cat >"$OUTPUT_BASE/scan_metadata.txt" <<EOF
control_host=$CONTROL_HOST
control_port=$CONTROL_PORT
route=$ROUTE
bias_afe=$BIAS_AFE
bias_values=$BIAS_VALUES
fixed_afe_bias_overrides=$FIXED_AFE_BIAS_OVERRIDES
group_specs=$GROUP_SPECS
vgain=$VGAIN
ch_offset=$CH_OFFSET
biasctrl_dac=$BIASCTRL_DAC
waveform_len=$WAVEFORM_LEN
waveforms_per_point=$WAVEFORMS_PER_POINT
scan_wavelength=$SCAN_WAVELENGTH
led_config=$LED_CONFIG
led_host=$LED_HOST
led_port=$LED_PORT
led_channel_mask=$LED_CHANNEL_MASK
led_number_channels=$LED_NUMBER_CHANNELS
led_pulse_width_ticks=$LED_PULSE_WIDTH_TICKS
output_base=$OUTPUT_BASE
EOF

SUMMARY_FILE="$OUTPUT_BASE/scan_summary.tsv"
printf "bias_afe\tbias_dac\tchannels\tled_intensity\tgroup_dir\tstatus\n" >"$SUMMARY_FILE"

echo "Output base: $OUTPUT_BASE"

IFS=',' read -r -a BIAS_ARRAY <<<"$BIAS_VALUES"
IFS=';' read -r -a GROUP_ARRAY <<<"$GROUP_SPECS"

for raw_bias in "${BIAS_ARRAY[@]}"; do
  scan_bias="${raw_bias//[[:space:]]/}"
  [[ -z "$scan_bias" ]] && continue

  point_dir="$OUTPUT_BASE/afe${BIAS_AFE}bias_$(printf '%04d' "$scan_bias")"
  mkdir -p "$point_dir"

  echo
  echo "==> afe${BIAS_AFE}_bias=$scan_bias"
  configure_point "$scan_bias" "$point_dir/configure.log"
  if [[ "$SAVE_FE_STATE" == "1" ]]; then
    capture_fe_state "$point_dir"
  fi
  sleep_if_needed "$SETTLE_S"

  for raw_group in "${GROUP_ARRAY[@]}"; do
    group_spec="${raw_group#"${raw_group%%[![:space:]]*}"}"
    group_spec="${group_spec%"${group_spec##*[![:space:]]}"}"
    [[ -z "$group_spec" ]] && continue
    channels="${group_spec%%:*}"
    intensity="${group_spec##*:}"
    channels="${channels//[[:space:]]/}"
    intensity="${intensity//[[:space:]]/}"
    channels_slug="${channels//,/_}"
    group_dir="$point_dir/led_${intensity}_ch${channels_slug}"
    mkdir -p "$group_dir"

    echo "     acquiring channels=$channels intensity=$intensity"
    start_led "$intensity" "$group_dir/led_start.log"
    sleep_if_needed "$SETTLE_S"
    acquire_group "$channels" "$group_dir"
    stop_led "$group_dir/led_stop.log"
    printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
      "$BIAS_AFE" "$scan_bias" "$channels" "$intensity" "$group_dir" "$([[ "$DRY_RUN" == "1" ]] && echo dry_run || echo captured)" \
      >>"$SUMMARY_FILE"
  done
done

echo
echo "LED bias scan completed."
echo "Data saved under: $OUTPUT_BASE"
