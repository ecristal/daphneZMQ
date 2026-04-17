#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/utils/run_client_via_tunnel.sh"

BOARD="${BOARD:-daphne-13}"
BIAS_AFE0_DAC="${BIAS_AFE0_DAC:-1201}"
BIAS_AFE1_DAC="${BIAS_AFE1_DAC:-857}"
NEW_367_TICKS="${NEW_367_TICKS:-3}"
CHARGE_WINDOWS_JSON="${CHARGE_WINDOWS_JSON:-$ROOT_DIR/client/dynamic_range_led/runs/calibration/charge_windows.json}"
HD_367_CHARGE_WINDOWS_JSON="${HD_367_CHARGE_WINDOWS_JSON:-}"
VD_367_CHARGE_WINDOWS_JSON="${VD_367_CHARGE_WINDOWS_JSON:-}"

HD_CHANNELS="${HD_CHANNELS:-12,13,14,15}"
VD_CHANNELS="${VD_CHANNELS:-4,5,6,7}"
SOF_CHANNELS="${SOF_CHANNELS:-18,19,20,21}"
ALL_LED_CHANNELS="${ALL_LED_CHANNELS:-4,5,6,7,12,13,14,15,18,19,20,21}"

run_client() {
  "$RUNNER" "$BOARD" "$@"
}

configure_fe() {
  local vgain="$1"
  local offset="$2"

  run_client client/configure_fe_min_v2.py \
    -vgain "$vgain" -ch_offset "$offset" -lpf_cutoff 10 \
    -pga_clamp_level '0 dBFS' -pga_gain_control '24 dB' \
    -lna_gain_control '12 dB' -lna_input_clamp auto \
    --full -align_afes --adc_resolution 0 \
    --timeout 30000 --cfg-timeout-ms 30000 \
    --afe-bias-dac "0:${BIAS_AFE0_DAC}" \
    --afe-bias-dac "1:${BIAS_AFE1_DAC}"
}

mar13_367_hd() {
  configure_fe 2100 1450
  if [[ -n "$HD_367_CHARGE_WINDOWS_JSON" ]]; then
    run_client client/dynamic_range_led/scan_led_intensity_charge.py \
      --output-dir client/dynamic_range_led/runs/led_intensity_mask1010_367nm_2000_4000_L1024_cfg2100_off1450_w"${NEW_367_TICKS}"_mar13 \
      --channels "$HD_CHANNELS" \
      --scan-wavelength 367 \
      --intensity-start 2000 --intensity-stop 4000 --intensity-step 50 \
      --calibration-intensity 3000 \
      --waveforms 512 --calibration-waveforms 128 \
      --waveform-len 1024 \
      --led-channel-mask 1010 \
      --pulse-width-ticks "$NEW_367_TICKS" \
      --bias-monitor-board "$BOARD" \
      --charge-windows-json "$HD_367_CHARGE_WINDOWS_JSON"
  else
    run_client client/dynamic_range_led/scan_led_intensity_charge.py \
      --output-dir client/dynamic_range_led/runs/led_intensity_mask1010_367nm_2000_4000_L1024_cfg2100_off1450_w"${NEW_367_TICKS}"_mar13 \
      --channels "$HD_CHANNELS" \
      --scan-wavelength 367 \
      --intensity-start 2000 --intensity-stop 4000 --intensity-step 50 \
      --calibration-intensity 3000 \
      --waveforms 512 --calibration-waveforms 128 \
      --waveform-len 1024 \
      --led-channel-mask 1010 \
      --pulse-width-ticks "$NEW_367_TICKS" \
      --bias-monitor-board "$BOARD"
  fi
}

mar13_367_vd() {
  configure_fe 2600 800
  if [[ -n "$VD_367_CHARGE_WINDOWS_JSON" ]]; then
    run_client client/dynamic_range_led/scan_led_intensity_charge.py \
      --output-dir client/dynamic_range_led/runs/led_intensity_mask1011_367nm_0000_4000_L1024_cfg2600_off0800_ch4567_mar13 \
      --channels "$VD_CHANNELS" \
      --scan-wavelength 367 \
      --intensity-start 0 --intensity-stop 4000 --intensity-step 50 \
      --calibration-intensity 3000 \
      --waveforms 512 --calibration-waveforms 128 \
      --waveform-len 1024 \
      --led-channel-mask 1011 \
      --pulse-width-ticks 2 \
      --bias-monitor-board "$BOARD" \
      --charge-windows-json "$VD_367_CHARGE_WINDOWS_JSON"
  else
    run_client client/dynamic_range_led/scan_led_intensity_charge.py \
      --output-dir client/dynamic_range_led/runs/led_intensity_mask1011_367nm_0000_4000_L1024_cfg2600_off0800_ch4567_mar13 \
      --channels "$VD_CHANNELS" \
      --scan-wavelength 367 \
      --intensity-start 0 --intensity-stop 4000 --intensity-step 50 \
      --calibration-intensity 3000 \
      --waveforms 512 --calibration-waveforms 128 \
      --waveform-len 1024 \
      --led-channel-mask 1011 \
      --pulse-width-ticks 2 \
      --bias-monitor-board "$BOARD"
  fi
}

mar13_270() {
  local vgain
  for vgain in 500 1200 2100; do
    configure_fe "$vgain" 2200

    run_client client/dynamic_range_led/scan_led_intensity_charge.py \
      --output-dir "client/dynamic_range_led/runs/led_intensity_charge_mask1_270nm_700_1750_L1024_5k_vgain${vgain}_off2200_mar13" \
      --channels "$ALL_LED_CHANNELS" \
      --scan-wavelength 270 \
      --intensity-start 700 --intensity-stop 1750 --intensity-step 50 \
      --calibration-intensity 1500 \
      --waveforms 5000 --calibration-waveforms 1000 \
      --waveform-len 1024 \
      --charge-windows-json "$CHARGE_WINDOWS_JSON" \
      --led-channel-mask 1 \
      --pulse-width-ticks 1 \
      --bias-monitor-board "$BOARD"
  done
}

usage() {
  cat <<EOF
Usage:
  $(basename "$0") <target>

Targets:
  mar13_367_hd    Retake mask1010 367 nm HD scan
  mar13_367_vd    Retake mask1011 367 nm VD scan
  mar13_270       Retake VGAIN 500,1200,2100 270 nm runs with offset 2200
  all             Run everything above in sequence

Environment overrides:
  BOARD=daphne-13
  NEW_367_TICKS=3
  BIAS_AFE0_DAC=1201
  BIAS_AFE1_DAC=857
  CHARGE_WINDOWS_JSON=$ROOT_DIR/client/dynamic_range_led/runs/calibration/charge_windows.json
  HD_367_CHARGE_WINDOWS_JSON=/path/to/charge_windows.json
  VD_367_CHARGE_WINDOWS_JSON=/path/to/charge_windows.json
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
    mar13_367_hd) mar13_367_hd ;;
    mar13_367_vd) mar13_367_vd ;;
    mar13_270) mar13_270 ;;
    all)
      mar13_367_hd
      mar13_367_vd
      mar13_270
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
