#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DYN_DIR="$ROOT_DIR/client/dynamic_range_led"
RUNS_DIR="$DYN_DIR/runs"
BUILD_SCRIPT="$DYN_DIR/build_analyze_led_snr_scan.sh"

RUN_DIRS=(
  "$RUNS_DIR/led_intensity_mask1_270nm_1100_1150_L1024_15k_vgain500_off2200_ch12_mar17"
  "$RUNS_DIR/led_intensity_mask1_270nm_1150_1250_L1024_15k_vgain500_off2200_ch13_mar17"
  "$RUNS_DIR/led_intensity_mask1_270nm_1200_1250_L1024_15k_vgain500_off2200_ch14_mar17"
  "$RUNS_DIR/led_intensity_mask1_270nm_1200_1250_L1024_15k_vgain500_off2200_ch15_mar17"
)

for run_dir in "${RUN_DIRS[@]}"; do
  if [[ ! -d "$run_dir" ]]; then
    echo "Missing run directory: $run_dir" >&2
    exit 2
  fi
done

ANALYZER="$("$BUILD_SCRIPT")"

for run_dir in "${RUN_DIRS[@]}"; do
  analysis_dir="$run_dir/cpp_snr_scan_p30"
  "$ANALYZER" "$run_dir" --output-dir "$analysis_dir"
  python3 "$DYN_DIR/plot_best_led_snr_publication.py" "$analysis_dir"
done

python3 "$DYN_DIR/make_best_group_sheet.py" \
  "$RUNS_DIR/mar17_best_hd_p30" \
  "${RUN_DIRS[0]}/cpp_snr_scan_p30" \
  "${RUN_DIRS[1]}/cpp_snr_scan_p30" \
  "${RUN_DIRS[2]}/cpp_snr_scan_p30" \
  "${RUN_DIRS[3]}/cpp_snr_scan_p30" \
  --title "Mar 17 HD best-point summary" \
  --columns 2
