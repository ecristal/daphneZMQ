#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/utils/run_client_via_tunnel.sh"

BOARD="${BOARD:-daphne-13}"
BIAS_AFE0_DAC="${BIAS_AFE0_DAC:-1201}"
BIAS_AFE1_DAC="${BIAS_AFE1_DAC:-857}"
NEW_367_TICKS="${NEW_367_TICKS:-4}"
CHARGE_WINDOWS_JSON="${CHARGE_WINDOWS_JSON:-$ROOT_DIR/client/dynamic_range_led/runs/calibration/charge_windows.json}"

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

repeat_367_hd() {
  configure_fe 2100 1450

  run_client client/dynamic_range_led/scan_led_intensity_charge.py \
    --output-dir client/dynamic_range_led/runs/led_intensity_mask1010_367nm_2000_4000_L1024_cfg2100_off1450_w"${NEW_367_TICKS}" \
    --channels "$HD_CHANNELS" \
    --scan-wavelength 367 \
    --intensity-start 2000 --intensity-stop 4000 --intensity-step 50 \
    --calibration-intensity 3000 \
    --waveforms 512 --calibration-waveforms 128 \
    --waveform-len 1024 \
    --led-channel-mask 1010 \
    --pulse-width-ticks "$NEW_367_TICKS" \
    --bias-monitor-board "$BOARD"
}

repeat_367_vd() {
  configure_fe 2600 800

  run_client client/dynamic_range_led/scan_led_intensity_charge.py \
    --output-dir client/dynamic_range_led/runs/led_intensity_mask1011_367nm_2000_4000_L1024_cfg2600_off0800_ch4567 \
    --channels "$VD_CHANNELS" \
    --scan-wavelength 367 \
    --intensity-start 2000 --intensity-stop 4000 --intensity-step 50 \
    --calibration-intensity 3000 \
    --waveforms 512 --calibration-waveforms 128 \
    --waveform-len 1024 \
    --led-channel-mask 1011 \
    --pulse-width-ticks 2 \
    --bias-monitor-board "$BOARD"
}

calib_270() {
  local vgain
  for vgain in 500 1200 2100 2600; do
    configure_fe "$vgain" 700

    run_client client/dynamic_range_led/scan_led_intensity_charge.py \
      --output-dir "client/dynamic_range_led/runs/led_intensity_charge_mask1_270nm_700_1750_L1024_5k_vgain${vgain}" \
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

scan_hd() {
  local vgain
  for vgain in 1200 2100; do
    configure_fe "$vgain" 2200

    run_client client/dynamic_range_led/scan_led_intensity_charge.py \
      --output-dir "client/dynamic_range_led/runs/led_intensity_mask1_270nm_3500_L1024_cfg${vgain}_off2200_hd" \
      --channels "$HD_CHANNELS" \
      --scan-wavelength 270 \
      --intensity-start 3500 --intensity-stop 3500 --intensity-step 50 \
      --calibration-intensity 3500 \
      --waveforms 512 --calibration-waveforms 128 \
      --waveform-len 1024 \
      --led-channel-mask 1 \
      --pulse-width-ticks 1 \
      --bias-monitor-board "$BOARD"
  done
}

scan_vd() {
  local vgain
  for vgain in 1200 2600; do
    configure_fe "$vgain" 2200

    run_client client/dynamic_range_led/scan_led_intensity_charge.py \
      --output-dir "client/dynamic_range_led/runs/led_intensity_mask1_270nm_3500_L1024_cfg${vgain}_off2200_vd" \
      --channels "$VD_CHANNELS" \
      --scan-wavelength 270 \
      --intensity-start 3500 --intensity-stop 3500 --intensity-step 50 \
      --calibration-intensity 3500 \
      --waveforms 512 --calibration-waveforms 128 \
      --waveform-len 1024 \
      --led-channel-mask 1 \
      --pulse-width-ticks 1 \
      --bias-monitor-board "$BOARD"
  done
}

scan_sof() {
  configure_fe 2500 2200

  run_client client/dynamic_range_led/scan_led_intensity_charge.py \
    --output-dir client/dynamic_range_led/runs/led_intensity_mask1_270nm_3500_L1024_cfg2500_off2200_sof \
    --channels "$SOF_CHANNELS" \
    --scan-wavelength 270 \
    --intensity-start 3500 --intensity-stop 3500 --intensity-step 50 \
    --calibration-intensity 3500 \
    --waveforms 512 --calibration-waveforms 128 \
    --waveform-len 1024 \
    --led-channel-mask 1 \
    --pulse-width-ticks 1 \
    --bias-monitor-board "$BOARD"
}

usage() {
  cat <<EOF
Usage:
  $(basename "$0") <target>

Targets:
  repeat_367_hd   Repeat mask1010 367 nm HD scan with 2000:4000:50 and increased ticks
  repeat_367_vd   Repeat mask1011 367 nm VD scan with 2000:4000:50 and original ticks
  calib_270       Repeat 270 nm calibration run at VGAIN 500,1200,2100,2600
  scan_hd         Run HD single-point scans at VGAIN 1200 and 2100
  scan_vd         Run VD single-point scans at VGAIN 1200 and 2600
  scan_sof        Run SoF saturation scan at VGAIN 2500
  all             Run everything above in sequence

Environment overrides:
  BOARD=daphne-13
  NEW_367_TICKS=4
  BIAS_AFE0_DAC=1201
  BIAS_AFE1_DAC=857
  CHARGE_WINDOWS_JSON=$ROOT_DIR/client/dynamic_range_led/runs/calibration/charge_windows.json
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
    repeat_367_hd) repeat_367_hd ;;
    repeat_367_vd) repeat_367_vd ;;
    calib_270) calib_270 ;;
    scan_hd) scan_hd ;;
    scan_vd) scan_vd ;;
    scan_sof) scan_sof ;;
    all)
      repeat_367_hd
      repeat_367_vd
      calib_270
      scan_hd
      scan_vd
      scan_sof
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
