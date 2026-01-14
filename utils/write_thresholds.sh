#!/usr/bin/env bash
# Write a value to a list/range of channels using the new 0x20-per-channel map.
# Threshold is at +0x00 in each channel block, 10-bit R/W (mask 0x3FF by default).
#
# Examples:
#   ./write_thresholds.sh 0xA0010000 0x000003E8 0,3,7,10-15 --verify
#   ./write_thresholds.sh 0xA0010000 800   0-39 --verify         # decimal value
#   ./write_thresholds.sh 0xA0010000 0x2AA 5,6 --no-mask         # skip 10-bit mask
#   ./write_thresholds.sh 0xA0010000 0x1   0-7  --offset 0x04    # (advanced) write record_lo

set -euo pipefail

usage() {
  echo "Usage: $0 <base_hex> <value> <channels> [--width 32] [--step 32] [--offset 0x00] [--mask 0x3FF|--no-mask] [--verify]"
  echo "  channels: comma-separated list; ranges allowed, e.g. 0,3,7-10"
  exit 1
}

[[ $# -lt 3 ]] && usage

BASE_HEX="$1"; shift
VALUE_IN="$1"; shift
CH_SPEC="$1"; shift

WIDTH=32
STEP=32             # 0x20 bytes per-channel block
OFFSET=0x00         # threshold lives at +0x00 within each block
MASK=0x3FF          # 10-bit threshold
APPLY_MASK=1
VERIFY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --width)   WIDTH="$2"; shift 2;;
    --step)    STEP="$2";  shift 2;;
    --offset)  OFFSET="$2"; shift 2;;     # advanced: write other fields (+0x04, +0x08, ...)
    --mask)    MASK="$2"; APPLY_MASK=1; shift 2;;
    --no-mask) APPLY_MASK=0; shift;;
    --verify)  VERIFY=1; shift;;
    *) echo "Unknown arg: $1"; usage;;
  esac
done

parse_channels() {
  local spec="$1" IFS=',' part
  for part in $spec; do
    if [[ "$part" == *-* ]]; then
      local lo=${part%-*} hi=${part#*-}
      for ((i=lo; i<=hi; i++)); do echo "$i"; done
    else
      echo "$part"
    fi
  done
}

# normalize numerics
base_dec=$(( BASE_HEX ))
step_dec=$(( STEP ))
off_dec=$(( OFFSET ))

# VALUE_IN may be hex or dec
if [[ "$VALUE_IN" == 0x* || "$VALUE_IN" == 0X* ]]; then
  value_dec=$(( VALUE_IN ))
else
  value_dec=$(( VALUE_IN + 0 ))
fi

if [[ $APPLY_MASK -eq 1 ]]; then
  mask_dec=$(( MASK ))
  value_dec=$(( value_dec & mask_dec ))
fi

printf "%-7s %-12s %-10s %-10s\n" "ch" "address" "write" "readback"
printf "%-7s %-12s %-10s %-10s\n" "------" "------------" "----------" "----------"

for ch in $(parse_channels "$CH_SPEC"); do
  addr_dec=$(( base_dec + ch*step_dec + off_dec ))
  addr_hex=$(printf "0x%08X" "$addr_dec")
  val_hex=$(printf "0x%08X" "$value_dec")

  sudo devmem "$addr_hex" "$WIDTH" "$val_hex" >/dev/null

  if [[ $VERIFY -eq 1 ]]; then
    rb=$(sudo devmem "$addr_hex" "$WIDTH")
    printf "%-7d %-12s %-10s %-10s\n" "$ch" "$addr_hex" "$val_hex" "$rb"
  else
    printf "%-7d %-12s %-10s %-10s\n" "$ch" "$addr_hex" "$val_hex" "-"
  fi
done
