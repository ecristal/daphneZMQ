#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/utils/run_client_via_tunnel.sh"

CONTROL_MODE="${CONTROL_MODE:-tunnel}"
CONTROL_HOST="${CONTROL_HOST:-}"
CONTROL_PORT="${CONTROL_PORT:-}"
CONTROL_PYTHON="${CONTROL_PYTHON:-python3}"

BOARD="${BOARD:-daphne-13}"
AFE1_BIAS_VALUES="${AFE1_BIAS_VALUES:-784,810,874}"
GROUP_SPECS="${GROUP_SPECS:-12:1100;13:1150;14,15:1200}"
WAVEFORM_LEN="${WAVEFORM_LEN:-1024}"
WAVEFORMS_PER_POINT="${WAVEFORMS_PER_POINT:-15000}"
VGAIN_START="${VGAIN_START:-500}"
VGAIN_STOP="${VGAIN_STOP:-2500}"
VGAIN_STEP="${VGAIN_STEP:-100}"
CH_OFFSET="${CH_OFFSET:-2200}"
TIMEOUT_MS="${TIMEOUT_MS:-30000}"
ROUTE="${ROUTE:-mezz/0}"

BIASCTRL_DAC="${BIASCTRL_DAC:-4095}"
ADC_RESOLUTION="${ADC_RESOLUTION:-0}"
LPF_CUTOFF="${LPF_CUTOFF:-10}"
PGA_CLAMP_LEVEL="${PGA_CLAMP_LEVEL:-0 dBFS}"
PGA_GAIN_CONTROL="${PGA_GAIN_CONTROL:-24 dB}"
LNA_GAIN_CONTROL="${LNA_GAIN_CONTROL:-12 dB}"
LNA_INPUT_CLAMP="${LNA_INPUT_CLAMP:-auto}"

SOFTWARE_TRIGGER="${SOFTWARE_TRIGGER:-0}"
ALIGN_AFES="${ALIGN_AFES:-0}"
SAVE_FE_STATE="${SAVE_FE_STATE:-1}"
SETTLE_S="${SETTLE_S:-0.5}"
DRY_RUN="${DRY_RUN:-0}"

SCAN_WAVELENGTH="${SCAN_WAVELENGTH:-270}"
LED_FIXED_INTENSITY_270NM="${LED_FIXED_INTENSITY_270NM:-0}"
LED_FIXED_INTENSITY_367NM="${LED_FIXED_INTENSITY_367NM:-0}"
LED_RUN_CLIENT="${LED_RUN_CLIENT:-$ROOT_DIR/client/ssp_led_run}"
LED_STOP_CLIENT="${LED_STOP_CLIENT:-$ROOT_DIR/client/ssp_led_stop}"
LED_CONFIG="${LED_CONFIG:-$ROOT_DIR/configs/led_run_defaults.json}"
LED_HOST="${LED_HOST:-127.0.0.1}"
LED_PORT="${LED_PORT:-55001}"
LED_SSH_TUNNEL="${LED_SSH_TUNNEL-np04-srv-017}"
LED_SSH_TUNNEL_REMOTE_HOST="${LED_SSH_TUNNEL_REMOTE_HOST:-10.73.137.61}"
LED_SSH_TUNNEL_REMOTE_PORT="${LED_SSH_TUNNEL_REMOTE_PORT:-55002}"
LED_TIMEOUT_S="${LED_TIMEOUT_S:-5}"
LED_CHANNEL_MASK="${LED_CHANNEL_MASK:-1}"
LED_NUMBER_CHANNELS="${LED_NUMBER_CHANNELS:-12}"
LED_PULSE_WIDTH_TICKS="${LED_PULSE_WIDTH_TICKS:-1}"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_BASE="${OUTPUT_BASE:-$ROOT_DIR/client/dynamic_range_led/runs/${STAMP}_${BOARD}_led_vgain_bias_scan}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0")

Environment overrides:
  CONTROL_MODE=tunnel
  CONTROL_HOST=10.73.137.161
  CONTROL_PORT=40001
  CONTROL_PYTHON=python3
  BOARD=daphne-13
  AFE1_BIAS_VALUES=784,810,874
  GROUP_SPECS='12:1100;13:1150;14,15:1200'
  WAVEFORM_LEN=1024
  WAVEFORMS_PER_POINT=15000
  VGAIN_START=500
  VGAIN_STOP=2500
  VGAIN_STEP=100
  CH_OFFSET=2200
  BIASCTRL_DAC=4095
  TIMEOUT_MS=30000
  ROUTE=mezz/0
  SOFTWARE_TRIGGER=0
  ALIGN_AFES=0
  SAVE_FE_STATE=1
  SETTLE_S=0.5
  DRY_RUN=0
  SCAN_WAVELENGTH=270
  LED_FIXED_INTENSITY_270NM=0
  LED_FIXED_INTENSITY_367NM=0
  LED_CONFIG=$ROOT_DIR/configs/led_run_defaults.json
  LED_HOST=127.0.0.1
  LED_PORT=55001
  LED_SSH_TUNNEL=np04-srv-017
  LED_SSH_TUNNEL_REMOTE_HOST=10.73.137.61
  LED_SSH_TUNNEL_REMOTE_PORT=55002
  LED_TIMEOUT_S=5
  LED_CHANNEL_MASK=1
  LED_NUMBER_CHANNELS=12
  LED_PULSE_WIDTH_TICKS=1
  OUTPUT_BASE=$ROOT_DIR/client/dynamic_range_led/runs/<run_name>

Control modes:
  CONTROL_MODE=tunnel
    Uses ./utils/run_client_via_tunnel.sh and BOARD.

  CONTROL_MODE=direct
    Runs client scripts directly against CONTROL_HOST:CONTROL_PORT.
    This is the mode to use on np04-srv-017.

This script configures the FE once per AFE1-bias x vgain point, then takes one
or more LED acquisitions under that same FE state according to GROUP_SPECS.
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

if [[ "$CONTROL_MODE" != "tunnel" && "$CONTROL_MODE" != "direct" ]]; then
  echo "CONTROL_MODE must be 'tunnel' or 'direct'." >&2
  exit 2
fi

if [[ "$CONTROL_MODE" == "tunnel" ]]; then
  if [[ ! -x "$RUNNER" ]]; then
    echo "Tunnel runner not found or not executable: $RUNNER" >&2
    exit 2
  fi
else
  if [[ -z "$CONTROL_HOST" || -z "$CONTROL_PORT" ]]; then
    echo "CONTROL_MODE=direct requires CONTROL_HOST and CONTROL_PORT." >&2
    exit 2
  fi
fi

if [[ ! -x "$LED_RUN_CLIENT" ]]; then
  echo "LED run client not found or not executable: $LED_RUN_CLIENT" >&2
  exit 2
fi

if [[ ! -x "$LED_STOP_CLIENT" ]]; then
  echo "LED stop client not found or not executable: $LED_STOP_CLIENT" >&2
  exit 2
fi

if [[ "$SCAN_WAVELENGTH" != "270" && "$SCAN_WAVELENGTH" != "367" ]]; then
  echo "SCAN_WAVELENGTH must be 270 or 367." >&2
  exit 2
fi

if [[ "$VGAIN_STEP" == "0" ]]; then
  echo "VGAIN_STEP must be non-zero." >&2
  exit 2
fi

if (( VGAIN_STEP > 0 )) && (( VGAIN_START > VGAIN_STOP )); then
  echo "Positive VGAIN_STEP requires VGAIN_START <= VGAIN_STOP." >&2
  exit 2
fi

if (( VGAIN_STEP < 0 )) && (( VGAIN_START < VGAIN_STOP )); then
  echo "Negative VGAIN_STEP requires VGAIN_START >= VGAIN_STOP." >&2
  exit 2
fi

if [[ -z "$AFE1_BIAS_VALUES" ]]; then
  echo "AFE1_BIAS_VALUES must not be empty." >&2
  exit 2
fi

if [[ -z "$GROUP_SPECS" ]]; then
  echo "GROUP_SPECS must not be empty." >&2
  exit 2
fi

cd "$ROOT_DIR"
mkdir -p "$OUTPUT_BASE"

LED_ACTIVE=0
EMERGENCY_LED_STOP_LOG="$OUTPUT_BASE/emergency_led_stop.log"

cleanup_led() {
  if [[ "$LED_ACTIVE" != "1" ]]; then
    return 0
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
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

run_client_direct() {
  local client="$1"
  shift

  if [[ ! -f "$client" && -f "client/$client" ]]; then
    client="client/$client"
  fi
  if [[ ! -f "$client" ]]; then
    echo "Client script not found: $client" >&2
    return 2
  fi

  local passthru_args=()
  local args=("$@")
  local i=0
  while [[ $i -lt ${#args[@]} ]]; do
    local arg="${args[$i]}"
    case "$arg" in
      --ip|--host|-ip|--port|-port)
        i=$((i + 2))
        ;;
      --ip=*|--host=*|-ip=*|--port=*|-port=*)
        i=$((i + 1))
        ;;
      *)
        passthru_args+=("$arg")
        i=$((i + 1))
        ;;
    esac
  done

  local extra_args=()
  if grep -Eq -- '--ip' "$client"; then
    extra_args+=(--ip "$CONTROL_HOST")
  elif grep -Eq -- '-ip' "$client"; then
    extra_args+=(-ip "$CONTROL_HOST")
  elif grep -Eq -- '--host' "$client"; then
    extra_args+=(--host "$CONTROL_HOST")
  fi

  if grep -Eq -- '--port' "$client"; then
    extra_args+=(--port "$CONTROL_PORT")
  elif grep -Eq -- '-port' "$client"; then
    extra_args+=(-port "$CONTROL_PORT")
  fi

  if [[ "$(basename "$client")" == "configure_fe_min.py" || "$(basename "$client")" == "endpoint.py" ]]; then
    extra_args+=("$CONTROL_HOST" "$CONTROL_PORT")
  fi

  "$CONTROL_PYTHON" "$client" "${extra_args[@]}" "${passthru_args[@]}"
}

run_client() {
  if [[ "$CONTROL_MODE" == "tunnel" ]]; then
    "$RUNNER" "$BOARD" "$@"
  else
    run_client_direct "$@"
  fi
}

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

write_scan_manifest() {
  env \
    OUTPUT_BASE="$OUTPUT_BASE" \
    BOARD="$BOARD" \
    AFE1_BIAS_VALUES="$AFE1_BIAS_VALUES" \
    GROUP_SPECS="$GROUP_SPECS" \
    WAVEFORM_LEN="$WAVEFORM_LEN" \
    WAVEFORMS_PER_POINT="$WAVEFORMS_PER_POINT" \
    VGAIN_START="$VGAIN_START" \
    VGAIN_STOP="$VGAIN_STOP" \
    VGAIN_STEP="$VGAIN_STEP" \
    CH_OFFSET="$CH_OFFSET" \
    BIASCTRL_DAC="$BIASCTRL_DAC" \
    TIMEOUT_MS="$TIMEOUT_MS" \
    ROUTE="$ROUTE" \
    SOFTWARE_TRIGGER="$SOFTWARE_TRIGGER" \
    ALIGN_AFES="$ALIGN_AFES" \
    SAVE_FE_STATE="$SAVE_FE_STATE" \
    SETTLE_S="$SETTLE_S" \
    SCAN_WAVELENGTH="$SCAN_WAVELENGTH" \
    LED_FIXED_INTENSITY_270NM="$LED_FIXED_INTENSITY_270NM" \
    LED_FIXED_INTENSITY_367NM="$LED_FIXED_INTENSITY_367NM" \
    LED_CONFIG="$LED_CONFIG" \
    LED_HOST="$LED_HOST" \
    LED_PORT="$LED_PORT" \
    LED_SSH_TUNNEL="$LED_SSH_TUNNEL" \
    LED_SSH_TUNNEL_REMOTE_HOST="$LED_SSH_TUNNEL_REMOTE_HOST" \
    LED_SSH_TUNNEL_REMOTE_PORT="$LED_SSH_TUNNEL_REMOTE_PORT" \
    LED_TIMEOUT_S="$LED_TIMEOUT_S" \
    LED_CHANNEL_MASK="$LED_CHANNEL_MASK" \
    LED_NUMBER_CHANNELS="$LED_NUMBER_CHANNELS" \
    LED_PULSE_WIDTH_TICKS="$LED_PULSE_WIDTH_TICKS" \
    ADC_RESOLUTION="$ADC_RESOLUTION" \
    LPF_CUTOFF="$LPF_CUTOFF" \
    PGA_CLAMP_LEVEL="$PGA_CLAMP_LEVEL" \
    PGA_GAIN_CONTROL="$PGA_GAIN_CONTROL" \
    LNA_GAIN_CONTROL="$LNA_GAIN_CONTROL" \
    LNA_INPUT_CLAMP="$LNA_INPUT_CLAMP" \
    DRY_RUN="$DRY_RUN" \
    python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

def vgain_values(start: int, stop: int, step: int) -> list[int]:
    out = []
    value = start
    if step > 0:
        while value <= stop:
            out.append(value)
            value += step
    else:
        while value >= stop:
            out.append(value)
            value += step
    return out

groups = []
for raw_group in os.environ["GROUP_SPECS"].split(";"):
    raw_group = raw_group.strip()
    if not raw_group:
        continue
    channels, intensity = raw_group.rsplit(":", 1)
    groups.append(
        {
            "channels": [int(item.strip()) for item in channels.split(",") if item.strip()],
            "led_intensity": int(intensity.strip(), 0),
        }
    )

payload = {
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "type": "led_vgain_bias_scan",
    "board": os.environ["BOARD"],
    "afe1_bias_values": [int(item.strip(), 0) for item in os.environ["AFE1_BIAS_VALUES"].split(",") if item.strip()],
    "vgain_values": vgain_values(
        int(os.environ["VGAIN_START"]),
        int(os.environ["VGAIN_STOP"]),
        int(os.environ["VGAIN_STEP"]),
    ),
    "groups": groups,
    "waveform_len": int(os.environ["WAVEFORM_LEN"]),
    "waveforms_per_point": int(os.environ["WAVEFORMS_PER_POINT"]),
    "timeout_ms": int(os.environ["TIMEOUT_MS"]),
    "route": os.environ["ROUTE"],
    "software_trigger": os.environ["SOFTWARE_TRIGGER"] == "1",
    "align_afes": os.environ["ALIGN_AFES"] == "1",
    "save_fe_state": os.environ["SAVE_FE_STATE"] == "1",
    "dry_run": os.environ["DRY_RUN"] == "1",
    "requested_config": {
        "ch_offset": int(os.environ["CH_OFFSET"]),
        "biasctrl_dac": int(os.environ["BIASCTRL_DAC"]),
        "adc_resolution": int(os.environ["ADC_RESOLUTION"]),
        "lpf_cutoff": int(os.environ["LPF_CUTOFF"]),
        "pga_clamp_level": os.environ["PGA_CLAMP_LEVEL"],
        "pga_gain_control": os.environ["PGA_GAIN_CONTROL"],
        "lna_gain_control": os.environ["LNA_GAIN_CONTROL"],
        "lna_input_clamp": os.environ["LNA_INPUT_CLAMP"],
    },
    "led_settings": {
        "scan_wavelength": int(os.environ["SCAN_WAVELENGTH"]),
        "fixed_intensity_270nm": int(os.environ["LED_FIXED_INTENSITY_270NM"]),
        "fixed_intensity_367nm": int(os.environ["LED_FIXED_INTENSITY_367NM"]),
        "config": os.environ["LED_CONFIG"],
        "host": os.environ["LED_HOST"],
        "port": int(os.environ["LED_PORT"]),
        "ssh_tunnel": os.environ["LED_SSH_TUNNEL"],
        "ssh_tunnel_remote_host": os.environ["LED_SSH_TUNNEL_REMOTE_HOST"],
        "ssh_tunnel_remote_port": int(os.environ["LED_SSH_TUNNEL_REMOTE_PORT"]),
        "timeout_s": float(os.environ["LED_TIMEOUT_S"]),
        "channel_mask": int(os.environ["LED_CHANNEL_MASK"]),
        "number_channels": int(os.environ["LED_NUMBER_CHANNELS"]),
        "pulse_width_ticks": int(os.environ["LED_PULSE_WIDTH_TICKS"]),
    },
}

path = Path(os.environ["OUTPUT_BASE"]) / "scan_manifest.json"
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

write_group_metadata() {
  local group_dir="$1"
  local afe1_bias="$2"
  local vgain="$3"
  local channels="$4"
  local intensity="$5"
  local status="$6"
  env \
    GROUP_DIR="$group_dir" \
    AFE1_BIAS="$afe1_bias" \
    VGAIN="$vgain" \
    CHANNELS="$channels" \
    INTENSITY="$intensity" \
    STATUS="$status" \
    WAVEFORM_LEN="$WAVEFORM_LEN" \
    WAVEFORMS_PER_POINT="$WAVEFORMS_PER_POINT" \
    SOFTWARE_TRIGGER="$SOFTWARE_TRIGGER" \
    SCAN_WAVELENGTH="$SCAN_WAVELENGTH" \
    python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

group_dir = Path(os.environ["GROUP_DIR"])
payload = {
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "status": os.environ["STATUS"],
    "afe1_bias_dac": int(os.environ["AFE1_BIAS"]),
    "vgain": int(os.environ["VGAIN"]),
    "channels": [int(item.strip()) for item in os.environ["CHANNELS"].split(",") if item.strip()],
    "led_intensity": int(os.environ["INTENSITY"]),
    "scan_wavelength": int(os.environ["SCAN_WAVELENGTH"]),
    "waveform_len": int(os.environ["WAVEFORM_LEN"]),
    "waveforms_per_point": int(os.environ["WAVEFORMS_PER_POINT"]),
    "software_trigger": os.environ["SOFTWARE_TRIGGER"] == "1",
    "artifacts": {
        "led_start_log": str(group_dir / "led_start.log"),
        "acquire_log": str(group_dir / "acquire.log"),
        "led_stop_log": str(group_dir / "led_stop.log"),
    },
}
(group_dir / "metadata.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

configure_point() {
  local afe1_bias="$1"
  local vgain="$2"
  local logfile="$3"
  local cmd=(
    run_client
    client/configure_fe_min_v2.py
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
    --route "$ROUTE"
    --biasctrl-dac "$BIASCTRL_DAC"
    --afe-bias-dac "1:$afe1_bias"
  )

  if [[ "$ALIGN_AFES" == "1" ]]; then
    cmd+=(-align_afes)
  fi

  run_logged "$logfile" "${cmd[@]}"
}

capture_fe_state() {
  local point_dir="$1"
  local logfile="$point_dir/fe_state_readback.json"
  local cmd=(
    run_client
    client/read_fe_state_v2.py
    --route "$ROUTE"
    --timeout "$TIMEOUT_MS"
    --json
  )
  run_logged "$logfile" "${cmd[@]}"
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
  local logfile="$group_dir/acquire.log"
  local cmd=(
    run_client
    client/protobuf_acquire_list_channels.py
    --osc_mode
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

  run_logged "$logfile" "${cmd[@]}"
}

cat >"$OUTPUT_BASE/scan_metadata.txt" <<EOF
board=$BOARD
afe1_bias_values=$AFE1_BIAS_VALUES
group_specs=$GROUP_SPECS
waveform_len=$WAVEFORM_LEN
waveforms_per_point=$WAVEFORMS_PER_POINT
vgain_start=$VGAIN_START
vgain_stop=$VGAIN_STOP
vgain_step=$VGAIN_STEP
ch_offset=$CH_OFFSET
biasctrl_dac=$BIASCTRL_DAC
timeout_ms=$TIMEOUT_MS
route=$ROUTE
software_trigger=$SOFTWARE_TRIGGER
align_afes=$ALIGN_AFES
save_fe_state=$SAVE_FE_STATE
settle_s=$SETTLE_S
scan_wavelength=$SCAN_WAVELENGTH
led_fixed_intensity_270nm=$LED_FIXED_INTENSITY_270NM
led_fixed_intensity_367nm=$LED_FIXED_INTENSITY_367NM
led_config=$LED_CONFIG
led_host=$LED_HOST
led_port=$LED_PORT
led_ssh_tunnel=$LED_SSH_TUNNEL
led_ssh_tunnel_remote_host=$LED_SSH_TUNNEL_REMOTE_HOST
led_ssh_tunnel_remote_port=$LED_SSH_TUNNEL_REMOTE_PORT
led_timeout_s=$LED_TIMEOUT_S
led_channel_mask=$LED_CHANNEL_MASK
led_number_channels=$LED_NUMBER_CHANNELS
led_pulse_width_ticks=$LED_PULSE_WIDTH_TICKS
output_base=$OUTPUT_BASE
EOF
write_scan_manifest

SUMMARY_FILE="$OUTPUT_BASE/scan_summary.tsv"
printf "afe1_bias_dac\tvgain\tchannels\tled_intensity\tgroup_dir\tstatus\n" >"$SUMMARY_FILE"

echo "Output base: $OUTPUT_BASE"

IFS=',' read -r -a BIAS_ARRAY <<<"$AFE1_BIAS_VALUES"
IFS=';' read -r -a GROUP_ARRAY <<<"$GROUP_SPECS"

for raw_bias in "${BIAS_ARRAY[@]}"; do
  afe1_bias="${raw_bias//[[:space:]]/}"
  [[ -z "$afe1_bias" ]] && continue

  bias_dir="$OUTPUT_BASE/afe1bias_$(printf '%04d' "$afe1_bias")"
  mkdir -p "$bias_dir"
  echo
  echo "==> afe1_bias=$afe1_bias"

  for ((vgain = VGAIN_START; ; vgain += VGAIN_STEP)); do
    point_dir="$bias_dir/vgain_$(printf '%04d' "$vgain")"
    mkdir -p "$point_dir"

    echo "  -> vgain=$vgain"
    configure_point "$afe1_bias" "$vgain" "$point_dir/configure.log"
    if [[ "$SAVE_FE_STATE" == "1" ]]; then
      capture_fe_state "$point_dir"
    fi
    sleep_if_needed "$SETTLE_S"

    for raw_group in "${GROUP_ARRAY[@]}"; do
      group_spec="${raw_group#"${raw_group%%[![:space:]]*}"}"
      group_spec="${group_spec%"${group_spec##*[![:space:]]}"}"
      [[ -z "$group_spec" ]] && continue
      if [[ "$group_spec" != *:* ]]; then
        echo "Invalid GROUP_SPECS entry: $group_spec" >&2
        exit 2
      fi

      channels="${group_spec%%:*}"
      intensity="${group_spec##*:}"
      channels="${channels//[[:space:]]/}"
      intensity="${intensity//[[:space:]]/}"
      if [[ -z "$channels" || -z "$intensity" ]]; then
        echo "Invalid GROUP_SPECS entry: $group_spec" >&2
        exit 2
      fi

      channels_slug="${channels//,/_}"
      group_dir="$point_dir/led_${intensity}_ch${channels_slug}"
      mkdir -p "$group_dir"

      echo "     acquiring channels=$channels intensity=$intensity"
      start_led "$intensity" "$group_dir/led_start.log"
      sleep_if_needed "$SETTLE_S"
      acquire_group "$channels" "$group_dir"
      stop_led "$group_dir/led_stop.log"
      write_group_metadata "$group_dir" "$afe1_bias" "$vgain" "$channels" "$intensity" "$([[ "$DRY_RUN" == "1" ]] && echo dry_run || echo captured)"
      printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
        "$afe1_bias" "$vgain" "$channels" "$intensity" "$group_dir" "$([[ "$DRY_RUN" == "1" ]] && echo dry_run || echo captured)" \
        >>"$SUMMARY_FILE"
    done

    if (( VGAIN_STEP > 0 )); then
      (( vgain + VGAIN_STEP > VGAIN_STOP )) && break
    else
      (( vgain + VGAIN_STEP < VGAIN_STOP )) && break
    fi
  done
done

echo
echo "LED vgain-bias scan completed."
echo "Data saved under: $OUTPUT_BASE"
