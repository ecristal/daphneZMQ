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
GROUP_SPECS="${GROUP_SPECS:-0,1:750;2:770;3:760}"

VGAIN_START="${VGAIN_START:-500}"
VGAIN_STOP="${VGAIN_STOP:-2800}"
VGAIN_STEP="${VGAIN_STEP:-100}"
CH_OFFSET="${CH_OFFSET:-2275}"
BIASCTRL_DAC="${BIASCTRL_DAC:-1300}"
WAVEFORM_LEN="${WAVEFORM_LEN:-1024}"
WAVEFORMS_PER_POINT="${WAVEFORMS_PER_POINT:-15000}"
TIMEOUT_MS="${TIMEOUT_MS:-30000}"
SETTLE_S="${SETTLE_S:-0.5}"
SAVE_FE_STATE="${SAVE_FE_STATE:-1}"
SOFTWARE_TRIGGER="${SOFTWARE_TRIGGER:-0}"
ALIGN_AFES="${ALIGN_AFES:-0}"
CONFIGURE_RETRIES="${CONFIGURE_RETRIES:-2}"
LED_START_RETRIES="${LED_START_RETRIES:-3}"
ACQUIRE_RETRIES="${ACQUIRE_RETRIES:-2}"
LED_STOP_RETRIES="${LED_STOP_RETRIES:-3}"
RETRY_SLEEP_S="${RETRY_SLEEP_S:-2}"
STOP_FAILURE_IS_FATAL="${STOP_FAILURE_IS_FATAL:-0}"

ADC_RESOLUTION="${ADC_RESOLUTION:-0}"
LPF_CUTOFF="${LPF_CUTOFF:-10}"
PGA_CLAMP_LEVEL="${PGA_CLAMP_LEVEL:-0 dBFS}"
PGA_GAIN_CONTROL="${PGA_GAIN_CONTROL:-24 dB}"
LNA_GAIN_CONTROL="${LNA_GAIN_CONTROL:-12 dB}"
LNA_INPUT_CLAMP="${LNA_INPUT_CLAMP:-auto}"

DRY_RUN="${DRY_RUN:-0}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_BASE="${OUTPUT_BASE:-$ROOT_DIR/client/dynamic_range_led/runs/${STAMP}_led_vgain_bias_scan_remote}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0")

Direct remote LED vgain x bias scan with one FE configure per (vgain, bias)
point and one or more fixed-intensity acquisitions under that FE state.

Environment overrides:
  CONTROL_HOST=10.73.137.161
  CONTROL_PORT=40001
  ROUTE=mezz/0
  LED_HOST=10.73.137.61
  LED_PORT=55002
  LED_CONFIG=$ROOT_DIR/configs/led_run_defaults.json
  LED_CHANNEL_MASK=1
  LED_NUMBER_CHANNELS=12
  LED_PULSE_WIDTH_TICKS=2
  BIAS_AFE=0
  BIAS_VALUES=1130,1143,1156,1169,1182,1195,1208
  FIXED_AFE_BIAS_OVERRIDES=1:857
  GROUP_SPECS='0,1:750;2:770;3:760'
  VGAIN_START=500
  VGAIN_STOP=2800
  VGAIN_STEP=100
  CH_OFFSET=2275
  BIASCTRL_DAC=1300
  WAVEFORM_LEN=1024
  WAVEFORMS_PER_POINT=15000
  SOFTWARE_TRIGGER=0
  ALIGN_AFES=0
  CONFIGURE_RETRIES=2
  LED_START_RETRIES=3
  ACQUIRE_RETRIES=2
  LED_STOP_RETRIES=3
  RETRY_SLEEP_S=2
  STOP_FAILURE_IS_FATAL=0
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
  set +e
  "$@" >"$logfile" 2>&1
  local rc=$?
  set -e
  return "$rc"
}

run_logged_with_retries() {
  local logfile="$1"
  local retries="$2"
  shift 2

  if [[ "$DRY_RUN" == "1" ]]; then
    run_logged "$logfile" "$@"
    return 0
  fi

  local attempt rc
  : >"$logfile"
  for ((attempt=1; attempt<=retries; attempt++)); do
    {
      echo "== attempt ${attempt}/${retries} :: $(date -u +%Y-%m-%dT%H:%M:%SZ) =="
      printf '+'
      printf ' %q' "$@"
      printf '\n'
    } >>"$logfile"
    set +e
    "$@" >>"$logfile" 2>&1
    rc=$?
    set -e
    if [[ "$rc" -eq 0 ]]; then
      return 0
    fi
    echo "[attempt ${attempt}/${retries}] rc=${rc}" >>"$logfile"
    if (( attempt < retries )); then
      sleep "$RETRY_SLEEP_S"
    fi
  done
  return "$rc"
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
  local vgain="$1"
  local scan_bias="$2"
  local logfile="$3"
  local afe_bias_arg
  afe_bias_arg="$(combined_afe_bias_arg "$scan_bias")"
  local cmd=(
    "$PYTHON"
    "$ROOT_DIR/client/configure_fe_min_v2.py"
    --ip "$CONTROL_HOST"
    --port "$CONTROL_PORT"
    --route "$ROUTE"
    --full
    -vgain "$vgain"
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
  run_logged_with_retries "$logfile" "$CONFIGURE_RETRIES" "${cmd[@]}"
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
  run_logged_with_retries "$logfile" "$LED_START_RETRIES" "${cmd[@]}"
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
  if run_logged_with_retries "$logfile" "$LED_STOP_RETRIES" "${cmd[@]}"; then
    LED_ACTIVE=0
    return 0
  fi
  {
    echo "[warn] LED stop failed after ${LED_STOP_RETRIES} attempts."
    if [[ "$STOP_FAILURE_IS_FATAL" == "1" ]]; then
      echo "[warn] STOP_FAILURE_IS_FATAL=1, aborting scan."
    else
      echo "[warn] Continuing after best-effort cleanup."
    fi
  } >>"$logfile"
  if [[ "$STOP_FAILURE_IS_FATAL" == "1" ]]; then
    return 1
  fi
  cleanup_led || true
  LED_ACTIVE=0
  return 0
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
  run_logged_with_retries "$group_dir/acquire.log" "$ACQUIRE_RETRIES" "${cmd[@]}"
}

cat >"$OUTPUT_BASE/scan_metadata.txt" <<EOF
control_host=$CONTROL_HOST
control_port=$CONTROL_PORT
route=$ROUTE
bias_afe=$BIAS_AFE
bias_values=$BIAS_VALUES
fixed_afe_bias_overrides=$FIXED_AFE_BIAS_OVERRIDES
group_specs=$GROUP_SPECS
vgain_start=$VGAIN_START
vgain_stop=$VGAIN_STOP
vgain_step=$VGAIN_STEP
ch_offset=$CH_OFFSET
biasctrl_dac=$BIASCTRL_DAC
waveform_len=$WAVEFORM_LEN
waveforms_per_point=$WAVEFORMS_PER_POINT
configure_retries=$CONFIGURE_RETRIES
led_start_retries=$LED_START_RETRIES
acquire_retries=$ACQUIRE_RETRIES
led_stop_retries=$LED_STOP_RETRIES
retry_sleep_s=$RETRY_SLEEP_S
stop_failure_is_fatal=$STOP_FAILURE_IS_FATAL
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
printf "vgain\tbias_afe\tbias_dac\tchannels\tled_intensity\tgroup_dir\tstatus\n" >"$SUMMARY_FILE"

echo "Output base: $OUTPUT_BASE"

IFS=',' read -r -a BIAS_ARRAY <<<"$BIAS_VALUES"
IFS=';' read -r -a GROUP_ARRAY <<<"$GROUP_SPECS"

for ((vgain=VGAIN_START; vgain<=VGAIN_STOP; vgain+=VGAIN_STEP)); do
  echo
  echo "==> vgain=$vgain"

  for raw_bias in "${BIAS_ARRAY[@]}"; do
    scan_bias="${raw_bias//[[:space:]]/}"
    [[ -z "$scan_bias" ]] && continue

    point_dir="$OUTPUT_BASE/vgain_$(printf '%04d' "$vgain")/afe${BIAS_AFE}bias_$(printf '%04d' "$scan_bias")"
    mkdir -p "$point_dir"

    echo "  -> afe${BIAS_AFE}_bias=$scan_bias"
    configure_point "$vgain" "$scan_bias" "$point_dir/configure.log"
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
      printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
        "$vgain" "$BIAS_AFE" "$scan_bias" "$channels" "$intensity" "$group_dir" "$([[ "$DRY_RUN" == "1" ]] && echo dry_run || echo captured)" \
        >>"$SUMMARY_FILE"
    done
  done
done

echo
echo "LED vgain x bias scan completed."
echo "Data saved under: $OUTPUT_BASE"
