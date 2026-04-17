#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/utils/run_client_via_tunnel.sh"

BOARD="${BOARD:-daphne-13}"
CHANNELS="${CHANNELS:-0,1,2,3,4,5,6,7,8,9,10,11,12,13,14}"
WAVEFORM_LEN="${WAVEFORM_LEN:-2048}"
WAVEFORMS_PER_POINT="${WAVEFORMS_PER_POINT:-1000}"
VGAIN_START="${VGAIN_START:-0}"
VGAIN_STOP="${VGAIN_STOP:-3000}"
VGAIN_STEP="${VGAIN_STEP:-100}"
CH_OFFSET="${CH_OFFSET:-2275}"
TIMEOUT_MS="${TIMEOUT_MS:-30000}"
ROUTE="${ROUTE:-mezz/0}"

BIASCTRL_DAC="${BIASCTRL_DAC:-0}"
AFE_BIAS_OVERRIDES="${AFE_BIAS_OVERRIDES:-0:0,1:0,2:0,3:0,4:0}"
ADC_RESOLUTION="${ADC_RESOLUTION:-0}"
LPF_CUTOFF="${LPF_CUTOFF:-10}"
PGA_CLAMP_LEVEL="${PGA_CLAMP_LEVEL:-0 dBFS}"
PGA_GAIN_CONTROL="${PGA_GAIN_CONTROL:-24 dB}"
LNA_GAIN_CONTROL="${LNA_GAIN_CONTROL:-12 dB}"
LNA_INPUT_CLAMP="${LNA_INPUT_CLAMP:-auto}"

SOFTWARE_TRIGGER="${SOFTWARE_TRIGGER:-0}"
ALIGN_AFES="${ALIGN_AFES:-0}"
SAVE_FE_STATE="${SAVE_FE_STATE:-1}"
RUN_FFT_ANALYSIS="${RUN_FFT_ANALYSIS:-0}"
FFT_ANALYSIS_MAX_WAVES="${FFT_ANALYSIS_MAX_WAVES:-0}"
FFT_ANALYSIS_AVG_WAVES="${FFT_ANALYSIS_AVG_WAVES:-2000}"
FFT_ANALYSIS_PREFIX="${FFT_ANALYSIS_PREFIX:-fft_metrics_}"
FFT_ANALYSIS_LOG_X="${FFT_ANALYSIS_LOG_X:-1}"
DRY_RUN="${DRY_RUN:-0}"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_BASE="${OUTPUT_BASE:-$ROOT_DIR/client/dark_vgain_runs/${STAMP}_${BOARD}_dark_vgain_scan}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0")

Environment overrides:
  BOARD=daphne-13
  CHANNELS=4,5,6,7,12,13,14,15,16,17,18,19,20,21,22,23
  WAVEFORM_LEN=2048
  WAVEFORMS_PER_POINT=1000
  VGAIN_START=0
  VGAIN_STOP=3000
  VGAIN_STEP=100
  CH_OFFSET=2275
  BIASCTRL_DAC=0
  AFE_BIAS_OVERRIDES=0:0,1:0,2:0,3:0,4:0
  TIMEOUT_MS=30000
  ROUTE=mezz/0
  SOFTWARE_TRIGGER=0
  ALIGN_AFES=0
  SAVE_FE_STATE=1
  RUN_FFT_ANALYSIS=0
  FFT_ANALYSIS_MAX_WAVES=0
  FFT_ANALYSIS_AVG_WAVES=2000
  FFT_ANALYSIS_PREFIX=fft_metrics_
  FFT_ANALYSIS_LOG_X=1
  DRY_RUN=0
  OUTPUT_BASE=$ROOT_DIR/client/dark_vgain_runs/<run_name>

This configures all AFEs at each point with:
  - vgain = current scan point
  - channel offset = CH_OFFSET for all channels
  - bias control DAC = BIASCTRL_DAC
  - per-AFE bias DAC = AFE_BIAS_OVERRIDES

Acquisition uses:
  client/protobuf_acquire_list_channels.py --osc_mode
which performs one waveform per request and repeats WAVEFORMS_PER_POINT times.

Artifacts written per point:
  - configure.log
  - acquire.log
  - fe_state_readback.json (if SAVE_FE_STATE=1)
  - metadata.json
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

run_or_echo() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
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
    CH_OFFSET="$CH_OFFSET" \
    BIASCTRL_DAC="$BIASCTRL_DAC" \
    AFE_BIAS_OVERRIDES="$AFE_BIAS_OVERRIDES" \
    ROUTE="$ROUTE" \
    TIMEOUT_MS="$TIMEOUT_MS" \
    SOFTWARE_TRIGGER="$SOFTWARE_TRIGGER" \
    ALIGN_AFES="$ALIGN_AFES" \
    SAVE_FE_STATE="$SAVE_FE_STATE" \
    RUN_FFT_ANALYSIS="$RUN_FFT_ANALYSIS" \
    FFT_ANALYSIS_MAX_WAVES="$FFT_ANALYSIS_MAX_WAVES" \
    FFT_ANALYSIS_AVG_WAVES="$FFT_ANALYSIS_AVG_WAVES" \
    FFT_ANALYSIS_PREFIX="$FFT_ANALYSIS_PREFIX" \
    FFT_ANALYSIS_LOG_X="$FFT_ANALYSIS_LOG_X" \
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
    v = start
    while v <= stop:
        vgain_values.append(v)
        v += step
else:
    v = start
    while v >= stop:
        vgain_values.append(v)
        v += step

afe_bias = {}
for item in os.environ["AFE_BIAS_OVERRIDES"].split(","):
    item = item.strip()
    if not item:
        continue
    afe_s, value_s = item.split(":", 1)
    afe_bias[afe_s.strip()] = int(value_s.strip(), 0)

payload = {
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "type": "dark_vgain_scan",
    "board": os.environ["BOARD"],
    "channels": [int(item) for item in os.environ["CHANNELS"].split(",") if item.strip()],
    "waveform_len": int(os.environ["WAVEFORM_LEN"]),
    "waveforms_per_point": int(os.environ["WAVEFORMS_PER_POINT"]),
    "vgain_values": vgain_values,
    "route": os.environ["ROUTE"],
    "timeout_ms": int(os.environ["TIMEOUT_MS"]),
    "software_trigger": os.environ["SOFTWARE_TRIGGER"] == "1",
    "align_afes": os.environ["ALIGN_AFES"] == "1",
    "save_fe_state": os.environ["SAVE_FE_STATE"] == "1",
    "run_fft_analysis": os.environ["RUN_FFT_ANALYSIS"] == "1",
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
    "analysis": {
        "max_waves": int(os.environ["FFT_ANALYSIS_MAX_WAVES"]),
        "fft_avg_waves": int(os.environ["FFT_ANALYSIS_AVG_WAVES"]),
        "prefix": os.environ["FFT_ANALYSIS_PREFIX"],
        "fft_log_x": os.environ["FFT_ANALYSIS_LOG_X"] == "1",
    },
}

path = Path(os.environ["OUTPUT_BASE"]) / "scan_manifest.json"
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

write_point_metadata() {
  local point_dir="$1"
  local vgain="$2"
  local status="$3"
  env \
    POINT_DIR="$point_dir" \
    VGAIN="$vgain" \
    STATUS="$status" \
    CHANNELS="$CHANNELS" \
    WAVEFORM_LEN="$WAVEFORM_LEN" \
    WAVEFORMS_PER_POINT="$WAVEFORMS_PER_POINT" \
    ROUTE="$ROUTE" \
    SOFTWARE_TRIGGER="$SOFTWARE_TRIGGER" \
    SAVE_FE_STATE="$SAVE_FE_STATE" \
    RUN_FFT_ANALYSIS="$RUN_FFT_ANALYSIS" \
    CH_OFFSET="$CH_OFFSET" \
    BIASCTRL_DAC="$BIASCTRL_DAC" \
    AFE_BIAS_OVERRIDES="$AFE_BIAS_OVERRIDES" \
    ADC_RESOLUTION="$ADC_RESOLUTION" \
    LPF_CUTOFF="$LPF_CUTOFF" \
    PGA_CLAMP_LEVEL="$PGA_CLAMP_LEVEL" \
    PGA_GAIN_CONTROL="$PGA_GAIN_CONTROL" \
    LNA_GAIN_CONTROL="$LNA_GAIN_CONTROL" \
    LNA_INPUT_CLAMP="$LNA_INPUT_CLAMP" \
    FFT_ANALYSIS_PREFIX="$FFT_ANALYSIS_PREFIX" \
    python3 - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

point_dir = Path(os.environ["POINT_DIR"])
afe_bias = {}
for item in os.environ["AFE_BIAS_OVERRIDES"].split(","):
    item = item.strip()
    if not item:
        continue
    afe_s, value_s = item.split(":", 1)
    afe_bias[afe_s.strip()] = int(value_s.strip(), 0)

payload = {
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "status": os.environ["STATUS"],
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
        "fft_metrics_csv": str(point_dir / f"{os.environ['FFT_ANALYSIS_PREFIX']}noise_metrics.csv") if os.environ["RUN_FFT_ANALYSIS"] == "1" else "",
        "fft_metrics_json": str(point_dir / f"{os.environ['FFT_ANALYSIS_PREFIX']}noise_metrics.json") if os.environ["RUN_FFT_ANALYSIS"] == "1" else "",
    },
}

(point_dir / "metadata.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

configure_point() {
  local vgain="$1"
  local logfile="$2"
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
  local vgain="$1"
  local point_dir="$OUTPUT_BASE/vgain_$(printf '%04d' "$vgain")"
  local logfile="$point_dir/acquire.log"
  mkdir -p "$point_dir"

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

mkdir -p "$OUTPUT_BASE"
cat >"$OUTPUT_BASE/scan_metadata.txt" <<EOF
board=$BOARD
channels=$CHANNELS
waveform_len=$WAVEFORM_LEN
waveforms_per_point=$WAVEFORMS_PER_POINT
vgain_start=$VGAIN_START
vgain_stop=$VGAIN_STOP
vgain_step=$VGAIN_STEP
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
  acquire_point "$vgain"
  write_point_metadata "$point_dir" "$vgain" "captured"

  if (( VGAIN_STEP > 0 )); then
    (( vgain + VGAIN_STEP > VGAIN_STOP )) && break
  else
    (( vgain + VGAIN_STEP < VGAIN_STOP )) && break
  fi
done

if [[ "$RUN_FFT_ANALYSIS" == "1" ]]; then
  analysis_cmd=(
    "$ROOT_DIR/scripts/analyze_dark_vgain_scan.py"
    "$OUTPUT_BASE"
    --fft_avg_waves "$FFT_ANALYSIS_AVG_WAVES"
    --max_waves "$FFT_ANALYSIS_MAX_WAVES"
    --prefix "$FFT_ANALYSIS_PREFIX"
  )
  if [[ "$FFT_ANALYSIS_LOG_X" == "1" ]]; then
    analysis_cmd+=(--fft_log_x)
  fi
  run_or_echo "${analysis_cmd[@]}"
fi

echo
echo "Dark vgain scan completed."
echo "Data saved under: $OUTPUT_BASE"
