#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/utils/run_client_via_tunnel.sh"

BOARD="${BOARD:-daphne-13}"
VGAIN="${VGAIN:-500}"
OFFSET="${OFFSET:-2200}"
WAVEFORMS="${WAVEFORMS:-15000}"
WAVEFORM_LEN="${WAVEFORM_LEN:-1024}"
CHARGE_WINDOWS_JSON="${CHARGE_WINDOWS_JSON:-$ROOT_DIR/client/dynamic_range_led/runs/calibration/charge_windows.json}"

HD_BIAS_AFE0_DAC="${HD_BIAS_AFE0_DAC:-1201}"
HD_BIAS_AFE1_DAC="${HD_BIAS_AFE1_DAC:-857}"

SSP_TUNNEL="${SSP_TUNNEL:-np04-srv-017}"
SSP_TUNNEL_REMOTE_HOST="${SSP_TUNNEL_REMOTE_HOST:-10.73.137.61}"
SSP_TUNNEL_REMOTE_PORT="${SSP_TUNNEL_REMOTE_PORT:-55002}"
SSP_LED_HOST="${SSP_LED_HOST:-127.0.0.1}"
SSP_LED_PORT="${SSP_LED_PORT:-55001}"

SCAN_DRY_RUN="${SCAN_DRY_RUN:-0}"

run_client() {
  "$RUNNER" "$BOARD" "$@"
}

configure_fe() {
  local vgain="$1"
  local offset="$2"
  local afe0_bias_dac="$3"
  local afe1_bias_dac="$4"

  run_client client/configure_fe_min_v2.py \
    -vgain "$vgain" -ch_offset "$offset" -lpf_cutoff 10 \
    -pga_clamp_level '0 dBFS' -pga_gain_control '24 dB' \
    -lna_gain_control '12 dB' -lna_input_clamp auto \
    --full -align_afes --adc_resolution 0 \
    --timeout 30000 --cfg-timeout-ms 30000 \
    --afe-bias-dac "0:${afe0_bias_dac}" \
    --afe-bias-dac "1:${afe1_bias_dac}"
}

run_scan() {
  local output_dir="$1"
  local channels="$2"
  local intensity_start="$3"
  local intensity_stop="$4"
  local intensity_step="$5"

  local cmd=(
    client/dynamic_range_led/scan_led_intensity_charge.py
    --output-dir "$output_dir"
    --channels "$channels"
    --scan-wavelength 270
    --intensity-start "$intensity_start"
    --intensity-stop "$intensity_stop"
    --intensity-step "$intensity_step"
    --waveforms "$WAVEFORMS"
    --waveform-len "$WAVEFORM_LEN"
    --charge-windows-json "$CHARGE_WINDOWS_JSON"
    --led-channel-mask 1
    --pulse-width-ticks 1
    --bias-monitor-board "$BOARD"
    --led-host "$SSP_LED_HOST"
    --led-port "$SSP_LED_PORT"
    --led-ssh-tunnel "$SSP_TUNNEL"
    --led-ssh-tunnel-remote-host "$SSP_TUNNEL_REMOTE_HOST"
    --led-ssh-tunnel-remote-port "$SSP_TUNNEL_REMOTE_PORT"
  )
  if [[ "$SCAN_DRY_RUN" == "1" ]]; then
    cmd+=(--dry-run)
  fi

  run_client "${cmd[@]}"
}

mar17_hd_ch12() {
  configure_fe "$VGAIN" "$OFFSET" "$HD_BIAS_AFE0_DAC" "$HD_BIAS_AFE1_DAC"
  run_scan \
    client/dynamic_range_led/runs/led_intensity_mask1_270nm_1100_1150_L1024_15k_vgain500_off2200_ch12_mar17 \
    12 \
    1100 \
    1150 \
    20
}

mar17_hd_ch13() {
  configure_fe "$VGAIN" "$OFFSET" "$HD_BIAS_AFE0_DAC" "$HD_BIAS_AFE1_DAC"
  run_scan \
    client/dynamic_range_led/runs/led_intensity_mask1_270nm_1150_1250_L1024_15k_vgain500_off2200_ch13_mar17 \
    13 \
    1150 \
    1250 \
    20
}

mar17_hd_ch14() {
  configure_fe "$VGAIN" "$OFFSET" "$HD_BIAS_AFE0_DAC" "$HD_BIAS_AFE1_DAC"
  run_scan \
    client/dynamic_range_led/runs/led_intensity_mask1_270nm_1200_1250_L1024_15k_vgain500_off2200_ch14_mar17 \
    14 \
    1200 \
    1250 \
    20
}

mar17_hd_ch15() {
  configure_fe "$VGAIN" "$OFFSET" "$HD_BIAS_AFE0_DAC" "$HD_BIAS_AFE1_DAC"
  run_scan \
    client/dynamic_range_led/runs/led_intensity_mask1_270nm_1200_1250_L1024_15k_vgain500_off2200_ch15_mar17 \
    15 \
    1200 \
    1250 \
    20
}

all_hd() {
  mar17_hd_ch12
  mar17_hd_ch13
  mar17_hd_ch14
  mar17_hd_ch15
}

usage() {
  cat <<EOF
Usage:
  $(basename "$0") <target>

Targets:
  mar17_hd_ch12
  mar17_hd_ch13
  mar17_hd_ch14
  mar17_hd_ch15
  all_hd
  all

Environment overrides:
  BOARD=daphne-13
  VGAIN=500
  OFFSET=2200
  WAVEFORMS=15000
  WAVEFORM_LEN=1024
  CHARGE_WINDOWS_JSON=$ROOT_DIR/client/dynamic_range_led/runs/calibration/charge_windows.json
  HD_BIAS_AFE0_DAC=1201
  HD_BIAS_AFE1_DAC=857
  SSP_TUNNEL=np04-srv-017
  SSP_TUNNEL_REMOTE_HOST=10.73.137.61
  SSP_TUNNEL_REMOTE_PORT=55002
  SSP_LED_HOST=127.0.0.1
  SSP_LED_PORT=55001
  SCAN_DRY_RUN=1
EOF
}

main() {
  local target="${1:-}"
  if [[ -z "$target" ]]; then
    usage
    exit 2
  fi

  cd "$ROOT_DIR"

  case "$target" in
    mar17_hd_ch12) mar17_hd_ch12 ;;
    mar17_hd_ch13) mar17_hd_ch13 ;;
    mar17_hd_ch14) mar17_hd_ch14 ;;
    mar17_hd_ch15) mar17_hd_ch15 ;;
    all_hd|all) all_hd ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
