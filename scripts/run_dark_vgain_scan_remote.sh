#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

CONTROL_HOST="${CONTROL_HOST:-10.73.137.161}"
CONTROL_PORT="${CONTROL_PORT:-40001}"
ROUTE="${ROUTE:-mezz/0}"

CHANNELS="${CHANNELS:-12,13,14,15}"
WAVEFORM_LEN="${WAVEFORM_LEN:-1024}"
WAVEFORMS_PER_POINT="${WAVEFORMS_PER_POINT:-5000}"
VGAIN_START="${VGAIN_START:-500}"
VGAIN_STOP="${VGAIN_STOP:-2500}"
VGAIN_STEP="${VGAIN_STEP:-100}"
CH_OFFSET="${CH_OFFSET:-2200}"
TIMEOUT_MS="${TIMEOUT_MS:-30000}"

BIASCTRL_DAC="${BIASCTRL_DAC:-0}"
AFE_BIAS_OVERRIDES="${AFE_BIAS_OVERRIDES:-0:0,1:0}"
ADC_RESOLUTION="${ADC_RESOLUTION:-0}"
LPF_CUTOFF="${LPF_CUTOFF:-10}"
PGA_CLAMP_LEVEL="${PGA_CLAMP_LEVEL:-0 dBFS}"
PGA_GAIN_CONTROL="${PGA_GAIN_CONTROL:-24 dB}"
LNA_GAIN_CONTROL="${LNA_GAIN_CONTROL:-12 dB}"
LNA_INPUT_CLAMP="${LNA_INPUT_CLAMP:-auto}"

SOFTWARE_TRIGGER="${SOFTWARE_TRIGGER:-0}"
ALIGN_AFES="${ALIGN_AFES:-0}"
SAVE_FE_STATE="${SAVE_FE_STATE:-1}"
DRY_RUN="${DRY_RUN:-0}"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_BASE="${OUTPUT_BASE:-$ROOT_DIR/client/dark_vgain_runs/${STAMP}_daphne-13_dark_vgain_scan_remote}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0")

Direct remote dark vgain scan.

Defaults:
  CHANNELS=12,13,14,15
  WAVEFORM_LEN=1024
  WAVEFORMS_PER_POINT=5000
  VGAIN_START=500
  VGAIN_STOP=2500
  VGAIN_STEP=100
  CH_OFFSET=2200
  BIASCTRL_DAC=0
  AFE_BIAS_OVERRIDES=0:0,1:0
  SOFTWARE_TRIGGER=0
  ALIGN_AFES=0
  SAVE_FE_STATE=1

Environment overrides:
  CONTROL_HOST=10.73.137.161
  CONTROL_PORT=40001
  ROUTE=mezz/0
  OUTPUT_BASE=$ROOT_DIR/client/dark_vgain_runs/<run_name>
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

write_scan_manifest() {
  env \
    OUTPUT_BASE="$OUTPUT_BASE" \
    CONTROL_HOST="$CONTROL_HOST" \
    CONTROL_PORT="$CONTROL_PORT" \
    ROUTE="$ROUTE" \
    CHANNELS="$CHANNELS" \
    WAVEFORM_LEN="$WAVEFORM_LEN" \
    WAVEFORMS_PER_POINT="$WAVEFORMS_PER_POINT" \
    VGAIN_START="$VGAIN_START" \
    VGAIN_STOP="$VGAIN_STOP" \
    VGAIN_STEP="$VGAIN_STEP" \
    CH_OFFSET="$CH_OFFSET" \
    BIASCTRL_DAC="$BIASCTRL_DAC" \
    AFE_BIAS_OVERRIDES="$AFE_BIAS_OVERRIDES" \
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

start = int(os.environ["VGAIN_START"])
stop = int(os.environ["VGAIN_STOP"])
step = int(os.environ["VGAIN_STEP"])
vgain_values = []
if step > 0:
    value = start
    while value <= stop:
        vgain_values.append(value)
        value += step
else:
    value = start
    while value >= stop:
        vgain_values.append(value)
        value += step

afe_bias = {}
for item in os.environ["AFE_BIAS_OVERRIDES"].split(","):
    item = item.strip()
    if not item:
        continue
    afe_s, value_s = item.split(":", 1)
    afe_bias[afe_s.strip()] = int(value_s.strip(), 0)

payload = {
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "type": "dark_vgain_scan_remote",
    "control_host": os.environ["CONTROL_HOST"],
    "control_port": int(os.environ["CONTROL_PORT"]),
    "route": os.environ["ROUTE"],
    "channels": [int(item) for item in os.environ["CHANNELS"].split(",") if item.strip()],
    "waveform_len": int(os.environ["WAVEFORM_LEN"]),
    "waveforms_per_point": int(os.environ["WAVEFORMS_PER_POINT"]),
    "vgain_values": vgain_values,
    "software_trigger": os.environ["SOFTWARE_TRIGGER"] == "1",
    "align_afes": os.environ["ALIGN_AFES"] == "1",
    "save_fe_state": os.environ["SAVE_FE_STATE"] == "1",
    "requested_config": {
        "ch_offset": int(os.environ["CH_OFFSET"]),
        "biasctrl_dac": int(os.environ["BIASCTRL_DAC"]),
        "adc_resolution": int(os.environ["ADC_RESOLUTION"]),
        "lpf_cutoff": int(os.environ["LPF_CUTOFF"]),
        "pga_clamp_level": os.environ["PGA_CLAMP_LEVEL"],
        "pga_gain_control": os.environ["PGA_GAIN_CONTROL"],
        "lna_gain_control": os.environ["LNA_GAIN_CONTROL"],
        "lna_input_clamp": os.environ["LNA_INPUT_CLAMP"],
        "afe_bias_dac": afe_bias,
    },
}

path = Path(os.environ["OUTPUT_BASE"]) / "scan_manifest.json"
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

write_point_metadata() {
  local point_dir="$1"
  local vgain="$2"
  env \
    POINT_DIR="$point_dir" \
    VGAIN="$vgain" \
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

afe_bias = {}
for item in os.environ["AFE_BIAS_OVERRIDES"].split(","):
    item = item.strip()
    if not item:
        continue
    afe_s, value_s = item.split(":", 1)
    afe_bias[afe_s.strip()] = int(value_s.strip(), 0)

point_dir = Path(os.environ["POINT_DIR"])
payload = {
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "status": "captured",
    "vgain": int(os.environ["VGAIN"]),
    "channels": [int(item) for item in os.environ["CHANNELS"].split(",") if item.strip()],
    "waveform_len": int(os.environ["WAVEFORM_LEN"]),
    "waveforms_per_point": int(os.environ["WAVEFORMS_PER_POINT"]),
    "route": os.environ["ROUTE"],
    "software_trigger": os.environ["SOFTWARE_TRIGGER"] == "1",
    "requested_config": {
        "vgain": int(os.environ["VGAIN"]),
        "ch_offset": int(os.environ["CH_OFFSET"]),
        "biasctrl_dac": int(os.environ["BIASCTRL_DAC"]),
        "adc_resolution": int(os.environ["ADC_RESOLUTION"]),
        "lpf_cutoff": int(os.environ["LPF_CUTOFF"]),
        "pga_clamp_level": os.environ["PGA_CLAMP_LEVEL"],
        "pga_gain_control": os.environ["PGA_GAIN_CONTROL"],
        "lna_gain_control": os.environ["LNA_GAIN_CONTROL"],
        "lna_input_clamp": os.environ["LNA_INPUT_CLAMP"],
        "afe_bias_dac": afe_bias,
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
  local logfile="$2"
  local cmd=(
    "$PYTHON"
    "$ROOT_DIR/client/configure_fe_min_v2.py"
    --ip "$CONTROL_HOST"
    --port "$CONTROL_PORT"
    --route "$ROUTE"
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
  )

  if [[ -n "$AFE_BIAS_OVERRIDES" ]]; then
    cmd+=(--afe-bias-dac "$AFE_BIAS_OVERRIDES")
  fi

  if [[ "$ALIGN_AFES" == "1" ]]; then
    cmd+=(-align_afes)
  fi

  run_logged "$logfile" "${cmd[@]}"
}

capture_fe_state() {
  local point_dir="$1"
  run_logged \
    "$point_dir/fe_state_readback.json" \
    "$PYTHON" \
    "$ROOT_DIR/client/read_fe_state_v2.py" \
    --host "$CONTROL_HOST" \
    --port "$CONTROL_PORT" \
    --route "$ROUTE" \
    --timeout "$TIMEOUT_MS" \
    --json
}

acquire_point() {
  local point_dir="$1"
  local logfile="$point_dir/acquire.log"
  local cmd=(
    "$PYTHON"
    "$ROOT_DIR/client/protobuf_acquire_list_channels.py"
    --osc_mode
    -ip "$CONTROL_HOST"
    -port "$CONTROL_PORT"
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

cat >"$OUTPUT_BASE/scan_metadata.txt" <<EOF
control_host=$CONTROL_HOST
control_port=$CONTROL_PORT
route=$ROUTE
channels=$CHANNELS
waveform_len=$WAVEFORM_LEN
waveforms_per_point=$WAVEFORMS_PER_POINT
vgain_start=$VGAIN_START
vgain_stop=$VGAIN_STOP
vgain_step=$VGAIN_STEP
ch_offset=$CH_OFFSET
biasctrl_dac=$BIASCTRL_DAC
afe_bias_overrides=$AFE_BIAS_OVERRIDES
software_trigger=$SOFTWARE_TRIGGER
align_afes=$ALIGN_AFES
save_fe_state=$SAVE_FE_STATE
output_base=$OUTPUT_BASE
EOF
write_scan_manifest

echo "Output base: $OUTPUT_BASE"

for ((vgain = VGAIN_START; ; vgain += VGAIN_STEP)); do
  point_dir="$OUTPUT_BASE/vgain_$(printf '%04d' "$vgain")"
  mkdir -p "$point_dir"

  echo
  echo "==> vgain=$vgain"
  configure_point "$vgain" "$point_dir/configure.log"
  if [[ "$SAVE_FE_STATE" == "1" ]]; then
    capture_fe_state "$point_dir"
  fi
  acquire_point "$point_dir"
  write_point_metadata "$point_dir" "$vgain"

  if (( VGAIN_STEP > 0 )); then
    (( vgain + VGAIN_STEP > VGAIN_STOP )) && break
  else
    (( vgain + VGAIN_STEP < VGAIN_STOP )) && break
  fi
done

echo
echo "Dark vgain scan completed."
echo "Data saved under: $OUTPUT_BASE"
