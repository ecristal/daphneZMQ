#!/usr/bin/env bash
# Read consecutive threshold registers with devmem and print a table.
# New map: step=32 (0x20), threshold_xc uses bits 27:0 by default.
# Usage: ./read_thresholds.sh [BASE] [CHANNELS] [STEP] [WIDTH] [MASK]

set -euo pipefail

BASE="${1:-0xA0010000}"
CHANNELS="${2:-40}"
STEP="${3:-32}"       # 0x20 bytes per channel
WIDTH="${4:-32}"      # devmem access width: 8/16/32
MASK="${5:-0x0FFFFFFF}"    # THRESH_S_AXI threshold_xc field

printf "%-7s %-12s %-10s %-10s %-10s\n" "ch" "address" "hex" "dec" "dec&mask"
printf "%-7s %-12s %-10s %-10s %-10s\n" "------" "------------" "----------" "----------" "----------"

base_dec=$(( BASE ))
step_dec=$(( STEP ))
mask_dec=$(( MASK ))

for (( ch=0; ch<CHANNELS; ch++ )); do
  addr_dec=$(( base_dec + ch*step_dec ))      # threshold @ +0x00 in each block
  addr_hex=$(printf "0x%08X" "$addr_dec")

  raw_hex=$(sudo devmem "$addr_hex" "$WIDTH") # e.g. 0x000003E8
  raw_hex_str=${raw_hex#0x}
  raw_dec=$(( 16#$raw_hex_str ))

  if [[ "$mask_dec" -ne 0 ]]; then
    masked=$(( raw_dec & mask_dec ))
  else
    masked=-
  fi

  printf "%-7d %-12s %-10s %-10d %-10s\n" "$ch" "$addr_hex" "$raw_hex" "$raw_dec" "$masked"
done
