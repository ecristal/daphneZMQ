#!/usr/bin/env bash
# diag_trigger.sh — DAPHNE threshold/counter diagnostic
# Requires: devmem

set -euo pipefail

# ---------- Defaults ----------
BASE=0xA0010000
STRIDE=0x20        # 32 bytes per channel block
NUM_CH=40
THRESH_MASK=0x0FFFFFFF

# Offsets within each 0x20 block
OFF_THR=0x00
OFF_REC_LO=0x04; OFF_REC_HI=0x08
OFF_BSY_LO=0x0C; OFF_BSY_HI=0x10
OFF_FUL_LO=0x14; OFF_FUL_HI=0x18

# ---------- devmem wrapper ----------
if command -v devmem >/dev/null 2>&1; then DEVMEM="devmem"
elif [[ -x /usr/sbin/devmem ]]; then DEVMEM="/usr/sbin/devmem"
elif [[ -x /usr/bin/devmem ]]; then DEVMEM="/usr/bin/devmem"
else echo "ERROR: devmem not found" >&2; exit 2; fi
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"

rd32() { $SUDO "$DEVMEM" "$1"; }                 # returns 0xXXXXXXXX
wr32() { $SUDO "$DEVMEM" "$1" 32 "$2" >/dev/null; }

# ---------- utils ----------
to_dec(){ printf "%d" "$(( $1 ))"; }             # 0x.. or decimal
addr(){ printf "0x%X" $(( BASE + STRIDE*$1 + $2 )); }

parse_channels() {
  local spec="$1"; local -n out_ref=$2
  out_ref=()
  if [[ "$spec" == "all" ]]; then
    for ((i=0;i<NUM_CH;i++)); do out_ref+=("$i"); done; return 0
  fi
  IFS=',' read -r -a parts <<< "$spec"
  for p in "${parts[@]}"; do
    if [[ "$p" =~ ^[0-9]+$ ]]; then out_ref+=("$p")
    elif [[ "$p" =~ ^([0-9]+)-([0-9]+)$ ]]; then
      a=${BASH_REMATCH[1]}; b=${BASH_REMATCH[2]}
      (( b < a )) && { echo "Bad range: $p" >&2; exit 2; }
      for ((i=a;i<=b;i++)); do out_ref+=("$i"); done
    else
      echo "Bad channel token: $p" >&2; exit 2
    fi
  done
  # uniq + sort
  mapfile -t out_ref < <(printf "%s\n" "${out_ref[@]}" | awk '!seen[$0]++' | sort -n)
  for c in "${out_ref[@]}"; do
    (( c<0 || c>=NUM_CH )) && { echo "Channel out of range: $c" >&2; exit 2; }
  done
}

read64() { # args: ch off_lo off_hi -> echo decimal
  local ch=$1 off_lo=$2 off_hi=$3
  local a_lo=$(addr "$ch" "$off_lo")
  local a_hi=$(addr "$ch" "$off_hi")
  local lo_hex=$(rd32 "$a_lo"); local hi_hex=$(rd32 "$a_hi")
  local lo=${lo_hex#0x}; local hi=${hi_hex#0x}
  lo=$((16#$lo)); hi=$((16#$hi))
  echo $(( (hi<<32) | lo ))
}

read_thr() { # ch -> dec (masked to threshold_xc field)
  local ch=$1 a=$(addr "$ch" "$OFF_THR")
  local v_hex=$(rd32 "$a"); v=${v_hex#0x}; v=$((16#$v))
  echo $(( v & THRESH_MASK ))
}

write_thr() { # ch value(0..0x0FFFFFFF)
  local ch=$1 val=$2 a=$(addr "$ch" "$OFF_THR")
  wr32 "$a" "$(printf "0x%X" "$val")"
}

fmt_h() { printf "0x%08X" "$1"; }

# ---------- commands ----------
usage() {
  cat <<EOF
Usage:
  $0 dump        [-c CHSPEC] [--base 0xADDR]
  $0 get-thr     [-c CHSPEC] [--base 0xADDR]
  $0 set-thr     -c CHSPEC -v VALUE [--base 0xADDR]
  $0 rate        [-c CHSPEC] [-i SEC] [-n N] [--base 0xADDR]

Where CHSPEC is: "0", "0-7", "0,4,7", or "all" (default: all)
VALUE accepts decimal or hex (e.g. 512 or 0x200). The writable threshold field is bits 27:0.
rate: samples counters every SEC seconds (default 1) for N iterations (default 1).

Examples:
  sudo $0 dump
  sudo $0 set-thr -c 0-3 -v 0x1F0
  sudo $0 get-thr -c 0,5,12
  sudo $0 rate -c 0-7 -i 2 -n 5
EOF
  exit 1
}

cmd="${1:-}"; shift || true
CHSPEC="all"; VAL=""; I=1; N=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    -c|--channels) CHSPEC="$2"; shift 2 ;;
    -v|--value)    VAL="$2";    shift 2 ;;
    --base)        BASE="$2";   shift 2 ;;
    -i|--interval) I="$2";      shift 2 ;;
    -n|--num)      N="$2";      shift 2 ;;
    -h|--help)     usage ;;
    *) echo "Unknown arg: $1" >&2; usage ;;
  esac
done

CHANNELS=(); parse_channels "$CHSPEC" CHANNELS

case "$cmd" in
  dump)
    printf "%-3s %-10s %-10s %-20s %-20s %-20s\n" "ch" "thr(hex)" "thr(dec)" "record_count" "busy_count" "full_count"
    for ch in "${CHANNELS[@]}"; do
      thr_dec=$(read_thr "$ch")
      rec=$(read64 "$ch" "$OFF_REC_LO" "$OFF_REC_HI")
      bsy=$(read64 "$ch" "$OFF_BSY_LO" "$OFF_BSY_HI")
      ful=$(read64 "$ch" "$OFF_FUL_LO" "$OFF_FUL_HI")
      printf "%-3d %-10s %-10d %-20d %-20d %-20d\n" \
        "$ch" "$(printf '0x%08X' "$thr_dec")" "$thr_dec" "$rec" "$bsy" "$ful"
    done
    ;;

  get-thr)
    printf "%-3s %-10s %-10s\n" "ch" "thr(hex)" "thr(dec)"
    for ch in "${CHANNELS[@]}"; do
      thr_dec=$(read_thr "$ch")
      printf "%-3d %-10s %-10d\n" "$ch" "$(printf '0x%08X' "$thr_dec")" "$thr_dec"
    done
    ;;

  set-thr)
    [[ -z "$VAL" ]] && { echo "set-thr requires -v VALUE" >&2; exit 2; }
    VAL_DEC=$(to_dec "$VAL")
    (( VAL_DEC < 0 || VAL_DEC > 0x0FFFFFFF )) && {
      echo "VALUE out of range (0..0x0FFFFFFF): $VAL" >&2
      exit 2
    }
    echo "Writing threshold $(printf '0x%08X' "$VAL_DEC") ($VAL_DEC) to channels: ${CHANNELS[*]}"
    for ch in "${CHANNELS[@]}"; do
      a=$(addr "$ch" "$OFF_THR")
      write_thr "$ch" "$VAL_DEC"
      rb=$(read_thr "$ch")
      printf "  ch %2d @ %s <- %s  [readback: 0x%08X (%d)]\n" \
        "$ch" "$a" "$(printf '0x%08X' "$VAL_DEC")" "$rb" "$rb"
    done
    ;;

  rate)
    printf "Sampling counters every %s s (%s iter)\n" "$I" "$N"
    # snapshot arrays: rec0[..], rec1[..] etc. (we’ll just keep prev and curr)
    declare -A rec_prev bsy_prev ful_prev
    for ch in "${CHANNELS[@]}"; do
      rec_prev[$ch]=$(read64 "$ch" "$OFF_REC_LO" "$OFF_REC_HI")
      bsy_prev[$ch]=$(read64 "$ch" "$OFF_BSY_LO" "$OFF_BSY_HI")
      ful_prev[$ch]=$(read64 "$ch" "$OFF_FUL_LO" "$OFF_FUL_HI")
    done
    for ((iter=1; iter<=N; iter++)); do
      sleep "$I"
      printf "\n# Iteration %d\n" "$iter"
      printf "%-3s %-12s %-12s %-12s\n" "ch" "record/s" "busy/s" "full/s"
      for ch in "${CHANNELS[@]}"; do
        rec_now=$(read64 "$ch" "$OFF_REC_LO" "$OFF_REC_HI")
        bsy_now=$(read64 "$ch" "$OFF_BSY_LO" "$OFF_BSY_HI")
        ful_now=$(read64 "$ch" "$OFF_FUL_LO" "$OFF_FUL_HI")
        rec_rate=$(( (rec_now - rec_prev[$ch]) / I ))
        bsy_rate=$(( (bsy_now - bsy_prev[$ch]) / I ))
        ful_rate=$(( (ful_now - ful_prev[$ch]) / I ))
        printf "%-3d %-12d %-12d %-12d\n" "$ch" "$rec_rate" "$bsy_rate" "$ful_rate"
        rec_prev[$ch]=$rec_now; bsy_prev[$ch]=$bsy_now; ful_prev[$ch]=$ful_now
      done
    done
    ;;

  *)
    usage ;;
esac
