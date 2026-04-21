#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATE_TAG="${DATE_TAG:-20260324}"
RUN_SUFFIX="${RUN_SUFFIX:-}"
MODE="${1:-}"
TECH="${2:-}"
DRY_RUN="${DRY_RUN:-0}"
PRINT_OUTPUTS="${PRINT_OUTPUTS:-0}"

CONTROL_HOST="${CONTROL_HOST:-10.73.137.161}"
CONTROL_PORT="${CONTROL_PORT:-40001}"
ROUTE="${ROUTE:-mezz/0}"
LED_HOST="${LED_HOST:-10.73.137.61}"
LED_TIMEOUT_S="${LED_TIMEOUT_S:-5}"

# Shared FE map from the current channel layout:
#   AFE0 -> VD  ch 0,1,2,3
#   AFE1 -> HD  ch 8,9,10,11
#   AFE2 -> SoF ch 18,19,20,21
#   AFE3 -> open
#   AFE4 -> open
GLOBAL_BIASCTRL_DAC="${GLOBAL_BIASCTRL_DAC:-4095}"
GLOBAL_AFE_BIAS_MAP="${GLOBAL_AFE_BIAS_MAP:-0:1195,1:810,2:0,3:0,4:0}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0") <mode> <tech>

Modes:
  saturation   Repeat the 367 nm saturation run for one technology
  vgain        Repeat the 270 nm vgain scan for one technology
  all          Run saturation then vgain for the selected technology

Tech:
  vd | hd | sof | all

Examples:
  DRY_RUN=1 $(basename "$0") saturation vd
  DRY_RUN=1 $(basename "$0") vgain hd
  $(basename "$0") all sof

Notes:
  - This script runs on np04-srv-017 and delegates to the existing remote
    wrappers in daphne-server/scripts.
  - Saturation presets use the shared AFE bias map:
      $GLOBAL_AFE_BIAS_MAP
  - Vgain presets keep the same shared AFE map, but scan only one technology's
    AFE bias value (single-point bias list) while sweeping vgain.
  - DRY_RUN=1 prints the wrapped command without executing it.
EOF
}

if [[ "$MODE" == "-h" || "$MODE" == "--help" || -z "$MODE" || -z "$TECH" ]]; then
  usage
  exit 0
fi

if [[ "$MODE" != "saturation" && "$MODE" != "vgain" && "$MODE" != "all" ]]; then
  echo "Invalid mode: $MODE" >&2
  usage
  exit 2
fi

if [[ "$TECH" != "vd" && "$TECH" != "hd" && "$TECH" != "sof" && "$TECH" != "all" ]]; then
  echo "Invalid tech: $TECH" >&2
  usage
  exit 2
fi

cd "$ROOT_DIR"

run_cmd() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  "$@"
}

run_saturation() {
  local tech="$1"
  local output_base led_port channels vgain ch_offset waveforms
  local intensity_start intensity_stop intensity_step fixed_bias_270 fixed_bias_367

  case "$tech" in
    vd)
      led_port=55002
      channels=0,1,2,3
      vgain=2500
      ch_offset=600
      waveforms=4000
      intensity_start=500
      intensity_stop=4095
      intensity_step=50
      fixed_bias_270=0
      fixed_bias_367=0
      output_base="$ROOT_DIR/client/dynamic_range_led/runs/${DATE_TAG}_vd_ch0to3_led367_0500_4095_step0050_vgain2500_off0600_biasmap_remote${RUN_SUFFIX}"
      ;;
    hd)
      led_port=55002
      channels=8,9,10,11
      vgain=2100
      ch_offset=1500
      waveforms=4000
      intensity_start=500
      intensity_stop=4095
      intensity_step=50
      fixed_bias_270=4095
      fixed_bias_367=0
      output_base="$ROOT_DIR/client/dynamic_range_led/runs/${DATE_TAG}_hd_ch8to11_led367_0500_4095_step0050_vgain2100_off1500_biasmap_remote${RUN_SUFFIX}"
      ;;
    sof)
      led_port=55001
      channels=18,19,20,21
      vgain=2200
      ch_offset=1400
      waveforms=4000
      intensity_start=500
      intensity_stop=4095
      intensity_step=50
      fixed_bias_270=0
      fixed_bias_367=0
      output_base="$ROOT_DIR/client/dynamic_range_led/runs/${DATE_TAG}_sof_ch18to21_led367_0500_4095_step0050_vgain2200_off1400_biasmap_remote${RUN_SUFFIX}"
      ;;
    *)
      echo "Unsupported saturation tech: $tech" >&2
      return 2
      ;;
  esac

  if [[ "$PRINT_OUTPUTS" == "1" ]]; then
    printf '%s\n' "$output_base"
    return 0
  fi

  run_cmd env \
    DRY_RUN="$DRY_RUN" \
    CONTROL_HOST="$CONTROL_HOST" \
    CONTROL_PORT="$CONTROL_PORT" \
    ROUTE="$ROUTE" \
    LED_HOST="$LED_HOST" \
    LED_PORT="$led_port" \
    LED_TIMEOUT_S="$LED_TIMEOUT_S" \
    LED_CONFIG="$ROOT_DIR/configs/led_run_defaults.json" \
    LED_CHANNEL_MASK=512 \
    LED_NUMBER_CHANNELS=12 \
    LED_PULSE_WIDTH_TICKS=4 \
    CHANNELS="$channels" \
    VGAIN="$vgain" \
    CH_OFFSET="$ch_offset" \
    WAVEFORMS="$waveforms" \
    WAVEFORM_LEN=1024 \
    TIMEOUT_MS=30000 \
    BIASCTRL_DAC="$GLOBAL_BIASCTRL_DAC" \
    AFE_BIAS_OVERRIDES="$GLOBAL_AFE_BIAS_MAP" \
    ADC_RESOLUTION=0 \
    LPF_CUTOFF=10 \
    PGA_CLAMP_LEVEL='0 dBFS' \
    PGA_GAIN_CONTROL='24 dB' \
    LNA_GAIN_CONTROL='12 dB' \
    LNA_INPUT_CLAMP=auto \
    ALIGN_AFES=1 \
    SCAN_WAVELENGTH=367 \
    INTENSITY_START="$intensity_start" \
    INTENSITY_STOP="$intensity_stop" \
    INTENSITY_STEP="$intensity_step" \
    FIXED_BIAS_270NM="$fixed_bias_270" \
    FIXED_BIAS_367NM="$fixed_bias_367" \
    CALIBRATION_INTENSITY=3000 \
    CALIBRATION_WAVEFORMS=128 \
    SETTLE_S=0.5 \
    OUTPUT_BASE="$output_base" \
    bash "$ROOT_DIR/scripts/run_367_led_scan_remote.sh"
}

run_vgain() {
  local tech="$1"
  local output_base led_port group_specs bias_afe bias_values fixed_overrides
  local ch_offset waveforms_per_point vgain_stop pulse_width_ticks

  case "$tech" in
    vd)
      led_port=55002
      group_specs='0:725;1:730;2:750;3:755'
      bias_afe=0
      bias_values=1195
      fixed_overrides='1:810,2:0,3:0,4:0'
      ch_offset=2275
      waveforms_per_point=20000
      vgain_stop=2800
      pulse_width_ticks=2
      output_base="$ROOT_DIR/client/dynamic_range_led/runs/${DATE_TAG}_vd_ch0to3_vgain_scan_led270_i725_730_750_755_biasmap_remote${RUN_SUFFIX}"
      ;;
    hd)
      led_port=55002
      group_specs='8:830;9:800;10:930;11:920'
      bias_afe=1
      bias_values=810
      fixed_overrides='0:1195,2:0,3:0,4:0'
      ch_offset=2200
      waveforms_per_point=20000
      vgain_stop=2500
      pulse_width_ticks=1
      output_base="$ROOT_DIR/client/dynamic_range_led/runs/${DATE_TAG}_hd_ch8to11_vgain_scan_led270_i830_800_930_920_biasmap_remote${RUN_SUFFIX}"
      ;;
    sof)
      led_port=55001
      group_specs='18:830;19:800;20:930;21:920'
      bias_afe=2
      bias_values=0
      fixed_overrides='0:1195,1:810,3:0,4:0'
      ch_offset=2275
      waveforms_per_point=20000
      vgain_stop=2800
      pulse_width_ticks=2
      output_base="$ROOT_DIR/client/dynamic_range_led/runs/${DATE_TAG}_sof_ch18to21_vgain_scan_led270_i830_800_930_920_biasmap_remote${RUN_SUFFIX}"
      ;;
    *)
      echo "Unsupported vgain tech: $tech" >&2
      return 2
      ;;
  esac

  if [[ "$PRINT_OUTPUTS" == "1" ]]; then
    printf '%s\n' "$output_base"
    return 0
  fi

  run_cmd env \
    DRY_RUN="$DRY_RUN" \
    CONTROL_HOST="$CONTROL_HOST" \
    CONTROL_PORT="$CONTROL_PORT" \
    ROUTE="$ROUTE" \
    LED_HOST="$LED_HOST" \
    LED_PORT="$led_port" \
    LED_TIMEOUT_S="$LED_TIMEOUT_S" \
    LED_CONFIG="$ROOT_DIR/configs/led_run_defaults.json" \
    SCAN_WAVELENGTH=270 \
    LED_FIXED_INTENSITY_270NM=0 \
    LED_FIXED_INTENSITY_367NM=0 \
    LED_CHANNEL_MASK=1 \
    LED_NUMBER_CHANNELS=12 \
    LED_PULSE_WIDTH_TICKS="$pulse_width_ticks" \
    GROUP_SPECS="$group_specs" \
    BIAS_AFE="$bias_afe" \
    BIAS_VALUES="$bias_values" \
    FIXED_AFE_BIAS_OVERRIDES="$fixed_overrides" \
    VGAIN_START=500 \
    VGAIN_STOP="$vgain_stop" \
    VGAIN_STEP=100 \
    CH_OFFSET="$ch_offset" \
    BIASCTRL_DAC="$GLOBAL_BIASCTRL_DAC" \
    WAVEFORM_LEN=1024 \
    WAVEFORMS_PER_POINT="$waveforms_per_point" \
    TIMEOUT_MS=30000 \
    SETTLE_S=0.5 \
    SAVE_FE_STATE=1 \
    SOFTWARE_TRIGGER=0 \
    ALIGN_AFES=1 \
    CONFIGURE_RETRIES=2 \
    LED_START_RETRIES=3 \
    ACQUIRE_RETRIES=2 \
    LED_STOP_RETRIES=3 \
    RETRY_SLEEP_S=2 \
    STOP_FAILURE_IS_FATAL=0 \
    ADC_RESOLUTION=0 \
    LPF_CUTOFF=10 \
    PGA_CLAMP_LEVEL='0 dBFS' \
    PGA_GAIN_CONTROL='24 dB' \
    LNA_GAIN_CONTROL='12 dB' \
    LNA_INPUT_CLAMP=auto \
    OUTPUT_BASE="$output_base" \
    bash "$ROOT_DIR/scripts/run_led_vgain_bias_scan_remote.sh"
}

run_mode_for_tech() {
  local mode="$1"
  local tech="$2"
  case "$mode" in
    saturation) run_saturation "$tech" ;;
    vgain) run_vgain "$tech" ;;
    all)
      run_saturation "$tech"
      run_vgain "$tech"
      ;;
  esac
}

if [[ "$TECH" == "all" ]]; then
  for tech in vd hd sof; do
    run_mode_for_tech "$MODE" "$tech"
  done
else
  run_mode_for_tech "$MODE" "$TECH"
fi
