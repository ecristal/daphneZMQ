#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/utils/run_client_via_tunnel.sh"

BOARD="${BOARD:-daphne-13}"
CHANNELS="${CHANNELS:-12,13,14,15}"
WAVEFORM_LEN="${WAVEFORM_LEN:-2048}"
WAVEFORMS_PER_POINT="${WAVEFORMS_PER_POINT:-10000}"
VGAIN_START="${VGAIN_START:-500}"
VGAIN_STOP="${VGAIN_STOP:-3000}"
VGAIN_STEP="${VGAIN_STEP:-100}"
TRIM_START="${TRIM_START:-0}"
TRIM_STOP="${TRIM_STOP:-4000}"
TRIM_STEP="${TRIM_STEP:-100}"
CH_OFFSET="${CH_OFFSET:-2200}"
TIMEOUT_MS="${TIMEOUT_MS:-30000}"
ROUTE="${ROUTE:-mezz/0}"

BIASCTRL_DAC="${BIASCTRL_DAC:-4095}"
AFE_BIAS_OVERRIDES="${AFE_BIAS_OVERRIDES:-1:873}"
ADC_RESOLUTION="${ADC_RESOLUTION:-0}"
LPF_CUTOFF="${LPF_CUTOFF:-10}"
PGA_CLAMP_LEVEL="${PGA_CLAMP_LEVEL:-0 dBFS}"
PGA_GAIN_CONTROL="${PGA_GAIN_CONTROL:-24 dB}"
LNA_GAIN_CONTROL="${LNA_GAIN_CONTROL:-12 dB}"
LNA_INPUT_CLAMP="${LNA_INPUT_CLAMP:-auto}"

SOFTWARE_TRIGGER="${SOFTWARE_TRIGGER:-0}"
ALIGN_AFES="${ALIGN_AFES:-1}"
SAVE_FE_STATE="${SAVE_FE_STATE:-1}"
DRY_RUN="${DRY_RUN:-0}"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_BASE="${OUTPUT_BASE:-$ROOT_DIR/client/vgain_trim_runs/${STAMP}_${BOARD}_vgain_trim_scan}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0")

Environment overrides:
  BOARD=daphne-13
  CHANNELS=12,13,14,15
  WAVEFORM_LEN=2048
  WAVEFORMS_PER_POINT=10000
  VGAIN_START=500
  VGAIN_STOP=3000
  VGAIN_STEP=100
  TRIM_START=0
  TRIM_STOP=4000
  TRIM_STEP=100
  CH_OFFSET=2200
  BIASCTRL_DAC=4095
  AFE_BIAS_OVERRIDES=1:873
  TIMEOUT_MS=30000
  ROUTE=mezz/0
  SOFTWARE_TRIGGER=0
  ALIGN_AFES=1
  SAVE_FE_STATE=1
  DRY_RUN=0
  OUTPUT_BASE=$ROOT_DIR/client/vgain_trim_runs/<run_name>

This configures each point with:
  - vgain = current vgain scan point
  - trim = current trim scan point on CHANNELS only
  - channel offset = CH_OFFSET for all channels
  - bias control DAC = BIASCTRL_DAC
  - per-AFE bias overrides = AFE_BIAS_OVERRIDES

Acquisition uses:
  client/protobuf_acquire_list_channels.py --osc_mode
without -software_trigger unless SOFTWARE_TRIGGER=1.
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

if [[ "$VGAIN_STEP" == "0" || "$TRIM_STEP" == "0" ]]; then
  echo "VGAIN_STEP and TRIM_STEP must be non-zero." >&2
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

if (( TRIM_STEP > 0 )) && (( TRIM_START > TRIM_STOP )); then
  echo "Positive TRIM_STEP requires TRIM_START <= TRIM_STOP." >&2
  exit 2
fi

if (( TRIM_STEP < 0 )) && (( TRIM_START < TRIM_STOP )); then
  echo "Negative TRIM_STEP requires TRIM_START >= TRIM_STOP." >&2
  exit 2
fi

IFS=',' read -r -a CHANNEL_ARRAY <<<"$CHANNELS"
if [[ ${#CHANNEL_ARRAY[@]} -eq 0 ]]; then
  echo "CHANNELS must not be empty." >&2
  exit 2
fi

cd "$ROOT_DIR"

run_client() {
  "$RUNNER" "$BOARD" "$@"
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

write_scan_manifest() {
  env \
    OUTPUT_BASE="$OUTPUT_BASE" \
    BOARD="$BOARD" \
    CHANNELS="$CHANNELS" \
    WAVEFORM_LEN="$WAVEFORM_LEN" \
    WAVEFORMS_PER_POINT="$WAVEFORMS_PER_POINT" \
    VGAIN_START="$VGAIN_START" \
    VGAIN_STOP="$VGAIN_STOP" \
    VGAIN_STEP="$VGAIN_STEP" \
    TRIM_START="$TRIM_START" \
    TRIM_STOP="$TRIM_STOP" \
    TRIM_STEP="$TRIM_STEP" \
    CH_OFFSET="$CH_OFFSET" \
    BIASCTRL_DAC="$BIASCTRL_DAC" \
    AFE_BIAS_OVERRIDES="$AFE_BIAS_OVERRIDES" \
    ROUTE="$ROUTE" \
    TIMEOUT_MS="$TIMEOUT_MS" \
    SOFTWARE_TRIGGER="$SOFTWARE_TRIGGER" \
    ALIGN_AFES="$ALIGN_AFES" \
    SAVE_FE_STATE="$SAVE_FE_STATE" \
    ADC_RESOLUTION="$ADC_RESOLUTION" \
    LPF_CUTOFF="$LPF_CUTOFF" \
    PGA_CLAMP_LEVEL="$PGA_CLAMP_LEVEL" \
    PGA_GAIN_CONTROL="$PGA_GAIN_CONTROL" \
    LNA_GAIN_CONTROL="$LNA_GAIN_CONTROL" \
    LNA_INPUT_CLAMP="$LNA_INPUT_CLAMP" \
    python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

def values(start: int, stop: int, step: int) -> list[int]:
    out = []
    v = start
    if step > 0:
        while v <= stop:
            out.append(v)
            v += step
    else:
        while v >= stop:
            out.append(v)
            v += step
    return out

afe_bias = {}
raw_bias = os.environ["AFE_BIAS_OVERRIDES"].strip()
if raw_bias:
    for item in raw_bias.split(","):
        item = item.strip()
        if not item:
            continue
        afe_s, value_s = item.split(":", 1)
        afe_bias[afe_s.strip()] = int(value_s.strip(), 0)

payload = {
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "type": "vgain_trim_scan",
    "board": os.environ["BOARD"],
    "channels": [int(item) for item in os.environ["CHANNELS"].split(",") if item.strip()],
    "waveform_len": int(os.environ["WAVEFORM_LEN"]),
    "waveforms_per_point": int(os.environ["WAVEFORMS_PER_POINT"]),
    "vgain_values": values(int(os.environ["VGAIN_START"]), int(os.environ["VGAIN_STOP"]), int(os.environ["VGAIN_STEP"])),
    "trim_values": values(int(os.environ["TRIM_START"]), int(os.environ["TRIM_STOP"]), int(os.environ["TRIM_STEP"])),
    "route": os.environ["ROUTE"],
    "timeout_ms": int(os.environ["TIMEOUT_MS"]),
    "software_trigger": os.environ["SOFTWARE_TRIGGER"] == "1",
    "align_afes": os.environ["ALIGN_AFES"] == "1",
    "save_fe_state": os.environ["SAVE_FE_STATE"] == "1",
    "requested_config": {
        "ch_offset": int(os.environ["CH_OFFSET"]),
        "biasctrl_dac": int(os.environ["BIASCTRL_DAC"]),
        "afe_bias_dac": afe_bias,
        "adc_resolution": int(os.environ["ADC_RESOLUTION"]),
        "lpf_cutoff": int(os.environ["LPF_CUTOFF"]),
        "pga_clamp_level": os.environ["PGA_CLAMP_LEVEL"],
        "pga_gain_control": os.environ["PGA_GAIN_CONTROL"],
        "lna_gain_control": os.environ["LNA_GAIN_CONTROL"],
        "lna_input_clamp": os.environ["LNA_INPUT_CLAMP"],
    },
}

path = Path(os.environ["OUTPUT_BASE"]) / "scan_manifest.json"
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

write_point_metadata() {
  local point_dir="$1"
  local vgain="$2"
  local trim="$3"
  env \
    POINT_DIR="$point_dir" \
    VGAIN="$vgain" \
    TRIM="$trim" \
    CHANNELS="$CHANNELS" \
    WAVEFORM_LEN="$WAVEFORM_LEN" \
    WAVEFORMS_PER_POINT="$WAVEFORMS_PER_POINT" \
    ROUTE="$ROUTE" \
    SOFTWARE_TRIGGER="$SOFTWARE_TRIGGER" \
    SAVE_FE_STATE="$SAVE_FE_STATE" \
    CH_OFFSET="$CH_OFFSET" \
    BIASCTRL_DAC="$BIASCTRL_DAC" \
    AFE_BIAS_OVERRIDES="$AFE_BIAS_OVERRIDES" \
    ADC_RESOLUTION="$ADC_RESOLUTION" \
    LPF_CUTOFF="$LPF_CUTOFF" \
    PGA_CLAMP_LEVEL="$PGA_CLAMP_LEVEL" \
    PGA_GAIN_CONTROL="$PGA_GAIN_CONTROL" \
    LNA_GAIN_CONTROL="$LNA_GAIN_CONTROL" \
    LNA_INPUT_CLAMP="$LNA_INPUT_CLAMP" \
    python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

point_dir = Path(os.environ["POINT_DIR"])
afe_bias = {}
raw_bias = os.environ["AFE_BIAS_OVERRIDES"].strip()
if raw_bias:
    for item in raw_bias.split(","):
        item = item.strip()
        if not item:
            continue
        afe_s, value_s = item.split(":", 1)
        afe_bias[afe_s.strip()] = int(value_s.strip(), 0)

payload = {
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "vgain": int(os.environ["VGAIN"]),
    "trim": int(os.environ["TRIM"]),
    "channels": [int(item) for item in os.environ["CHANNELS"].split(",") if item.strip()],
    "waveform_len": int(os.environ["WAVEFORM_LEN"]),
    "waveforms_per_point": int(os.environ["WAVEFORMS_PER_POINT"]),
    "route": os.environ["ROUTE"],
    "software_trigger": os.environ["SOFTWARE_TRIGGER"] == "1",
    "requested_config": {
        "vgain": int(os.environ["VGAIN"]),
        "trim": int(os.environ["TRIM"]),
        "ch_offset": int(os.environ["CH_OFFSET"]),
        "biasctrl_dac": int(os.environ["BIASCTRL_DAC"]),
        "afe_bias_dac": afe_bias,
        "adc_resolution": int(os.environ["ADC_RESOLUTION"]),
        "lpf_cutoff": int(os.environ["LPF_CUTOFF"]),
        "pga_clamp_level": os.environ["PGA_CLAMP_LEVEL"],
        "pga_gain_control": os.environ["PGA_GAIN_CONTROL"],
        "lna_gain_control": os.environ["LNA_GAIN_CONTROL"],
        "lna_input_clamp": os.environ["LNA_INPUT_CLAMP"],
    },
    "artifacts": {
        "configure_log": str(point_dir / "configure.log"),
        "acquire_log": str(point_dir / "acquire.log"),
        "fe_state_readback_json": str(point_dir / "fe_state_readback.json") if os.environ["SAVE_FE_STATE"] == "1" else "",
    },
}

(point_dir / "metadata.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

configure_point() {
  local vgain="$1"
  local trim="$2"
  local logfile="$3"
  local cmd=(
    run_client
    client/configure_fe_min_v2.py
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
  )

  if [[ -n "$AFE_BIAS_OVERRIDES" ]]; then
    cmd+=(--afe-bias-dac "$AFE_BIAS_OVERRIDES")
  fi

  local ch
  for ch in "${CHANNEL_ARRAY[@]}"; do
    cmd+=(--ch-trim "${ch}:${trim}")
  done

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

acquire_point() {
  local point_dir="$1"
  local logfile="$point_dir/acquire.log"
  local cmd=(
    run_client
    client/protobuf_acquire_list_channels.py
    --osc_mode
    -foldername "$point_dir"
    -channel_list "$CHANNELS"
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

count_values() {
  local start="$1"
  local stop="$2"
  local step="$3"
  local count=0
  local value="$start"
  if (( step > 0 )); then
    while (( value <= stop )); do
      count=$((count + 1))
      value=$((value + step))
    done
  else
    while (( value >= stop )); do
      count=$((count + 1))
      value=$((value + step))
    done
  fi
  echo "$count"
}

mkdir -p "$OUTPUT_BASE"
cat >"$OUTPUT_BASE/scan_metadata.txt" <<EOF
board=$BOARD
channels=$CHANNELS
waveform_len=$WAVEFORM_LEN
waveforms_per_point=$WAVEFORMS_PER_POINT
vgain_start=$VGAIN_START
vgain_stop=$VGAIN_STOP
vgain_step=$VGAIN_STEP
trim_start=$TRIM_START
trim_stop=$TRIM_STOP
trim_step=$TRIM_STEP
ch_offset=$CH_OFFSET
biasctrl_dac=$BIASCTRL_DAC
afe_bias_overrides=$AFE_BIAS_OVERRIDES
route=$ROUTE
timeout_ms=$TIMEOUT_MS
software_trigger=$SOFTWARE_TRIGGER
align_afes=$ALIGN_AFES
adc_resolution=$ADC_RESOLUTION
lpf_cutoff=$LPF_CUTOFF
pga_clamp_level=$PGA_CLAMP_LEVEL
pga_gain_control=$PGA_GAIN_CONTROL
lna_gain_control=$LNA_GAIN_CONTROL
lna_input_clamp=$LNA_INPUT_CLAMP
output_base=$OUTPUT_BASE
EOF
write_scan_manifest

trim_count="$(count_values "$TRIM_START" "$TRIM_STOP" "$TRIM_STEP")"
vgain_count="$(count_values "$VGAIN_START" "$VGAIN_STOP" "$VGAIN_STEP")"
point_count=$((trim_count * vgain_count))
total_waveforms=$((point_count * WAVEFORMS_PER_POINT))

echo "Output base: $OUTPUT_BASE"
echo "Trim points: $trim_count"
echo "Vgain points: $vgain_count"
echo "Total scan points: $point_count"
echo "Total waveforms: $total_waveforms"

for ((trim = TRIM_START; ; trim += TRIM_STEP)); do
  trim_dir="$OUTPUT_BASE/trim_$(printf '%04d' "$trim")"
  mkdir -p "$trim_dir"

  for ((vgain = VGAIN_START; ; vgain += VGAIN_STEP)); do
    point_dir="$trim_dir/vgain_$(printf '%04d' "$vgain")"
    mkdir -p "$point_dir"

    echo
    echo "==> trim=$trim vgain=$vgain"
    configure_point "$vgain" "$trim" "$point_dir/configure.log"
    if [[ "$SAVE_FE_STATE" == "1" ]]; then
      capture_fe_state "$point_dir"
    fi
    acquire_point "$point_dir"
    write_point_metadata "$point_dir" "$vgain" "$trim"

    if (( VGAIN_STEP > 0 )); then
      (( vgain + VGAIN_STEP > VGAIN_STOP )) && break
    else
      (( vgain + VGAIN_STEP < VGAIN_STOP )) && break
    fi
  done

  if (( TRIM_STEP > 0 )); then
    (( trim + TRIM_STEP > TRIM_STOP )) && break
  else
    (( trim + TRIM_STEP < TRIM_STOP )) && break
  fi
done

echo
echo "Vgain-trim scan completed."
echo "Data saved under: $OUTPUT_BASE"
