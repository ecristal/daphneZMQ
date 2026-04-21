#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Set per-channel thresholds via devmem on DAPHNE
# Channels default: 0..39 (stride 4 bytes)
# Threshold register: THRESH_BASE + 4*channel
# Optional masks: 32-bit low (0..31) and optional 32-bit high (32..63)
# -----------------------------------------------------------------------------
set -euo pipefail

# ---- Config (adjust if needed) ---------------------------------------------
THRESH_BASE=0xA0010000
STRIDE_BYTES=32
NUM_CH=40

# Default mask registers (can override with CLI)
MASK_REG_LOW=0x94000020   # bits 0..31
MASK_REG_HIGH=""          # pass via --mask2-reg if you have one

# ---- devmem / sudo ---------------------------------------------------------
if command -v devmem >/dev/null 2>&1; then DEVMEM="devmem"
elif [[ -x /usr/sbin/devmem ]]; then DEVMEM="/usr/sbin/devmem"
elif [[ -x /usr/bin/devmem ]]; then DEVMEM="/usr/bin/devmem"
else echo "ERROR: devmem not found" >&2; exit 2; fi
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"

# ---- Styling ---------------------------------------------------------------
BOLD='\033[1m'; DIM='\033[2m'; RED='\033[31m'; GRN='\033[32m'; YLW='\033[33m'; CYA='\033[36m'; RST='\033[0m'
info(){ echo -e "${CYA}ℹ${RST}  $*"; }
ok(){   echo -e "${GRN}✔${RST}  $*"; }
warn(){ echo -e "${YLW}▲${RST}  $*"; }
err(){  echo -e "${RED}✖${RST}  $*" 1>&2; }

usage() {
  cat <<EOF
Usage:
  $0 -c CHSEL -v VALUE [options]

Required:
  -c, --channels   Channel selection: "0", "0,2,5", "1-3", "0,3-5,7", "all"
  -v, --value      Threshold value (hex like 0xFFF or decimal like 4095)

Options:
      --readback            Read back each channel after write
      --dry-run             Show what would be written, do not modify registers
      --num-ch N            Total channels (default ${NUM_CH})
      --base 0xADDR         Override threshold base address (default ${THRESH_BASE})
      --stride BYTES        Override stride (default ${STRIDE_BYTES})

Mask options (32-bit words):
      --mask-auto           Compute mask(s) from selected channels and write them
      --mask-reg 0xADDR     Low 32-bit mask register for ch 0..31 (default ${MASK_REG_LOW})
      --mask2-reg 0xADDR    High 32-bit mask register for ch 32..63 (no default)
      --mask-low  0xM       Explicit low mask value to write at --mask-reg
      --mask-high 0xM       Explicit high mask value to write at --mask2-reg

Examples:
  sudo $0 -c 0 -v 0xA
  sudo $0 -c "0,1,7" -v 0xFFF --readback
  sudo $0 -c all -v 1024 --mask-auto
  sudo $0 -c 32-39 -v 0x200 --mask-auto --mask2-reg 0x94000024
EOF
}

# ---- Args ------------------------------------------------------------------
CHSEL=""
VALUE=""
DRYRUN=0
READBACK=0
MASK_AUTO=0
MASK_LOW_EXPL=""
MASK_HIGH_EXPL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -c|--channels) CHSEL="$2"; shift 2 ;;
    -v|--value)    VALUE="$2"; shift 2 ;;
    --dry-run)     DRYRUN=1; shift ;;
    --readback)    READBACK=1; shift ;;
    --num-ch)      NUM_CH="$2"; shift 2 ;;
    --base)        THRESH_BASE="$2"; shift 2 ;;
    --stride)      STRIDE_BYTES="$2"; shift 2 ;;
    --mask-auto)   MASK_AUTO=1; shift ;;
    --mask-reg)    MASK_REG_LOW="$2"; shift 2 ;;
    --mask2-reg)   MASK_REG_HIGH="$2"; shift 2 ;;
    --mask-low)    MASK_LOW_EXPL="$2"; shift 2 ;;
    --mask-high)   MASK_HIGH_EXPL="$2"; shift 2 ;;
    -h|--help)     usage; exit 0 ;;
    *) err "Unknown option: $1"; usage; exit 2 ;;
  esac
done
[[ -z "$CHSEL" || -z "$VALUE" ]] && { usage; exit 2; }

# ---- Helpers ---------------------------------------------------------------
to_dec(){ printf "%d" "$(( $1 ))"; }  # accepts 0x... or decimal

parse_channels() {
  local spec="$1"; local -n out_ref=$2
  out_ref=()
  if [[ "$spec" == "all" ]]; then
    for ((i=0;i<NUM_CH;i++)); do out_ref+=("$i"); done; return 0
  fi
  IFS=',' read -r -a parts <<< "$spec"
  for p in "${parts[@]}"; do
    if [[ "$p" =~ ^[0-9]+$ ]]; then
      out_ref+=("$p")
    elif [[ "$p" =~ ^([0-9]+)-([0-9]+)$ ]]; then
      local a=${BASH_REMATCH[1]} b=${BASH_REMATCH[2]}
      (( b < a )) && { err "Bad range: $p"; exit 2; }
      for ((i=a;i<=b;i++)); do out_ref+=("$i"); done
    else
      err "Bad channel token: $p"; exit 2
    fi
  done
}

unique_and_validate() {
  local -n arr=$1
  mapfile -t arr < <(printf "%s\n" "${arr[@]}" | awk '!seen[$0]++' | sort -n)
  for c in "${arr[@]}"; do
    if (( c < 0 || c >= NUM_CH )); then err "Channel out of range: $c (0..$((NUM_CH-1)))"; exit 2; fi
  done
}

addr_for_channel() { printf "0x%X" $(( THRESH_BASE + STRIDE_BYTES*$1 )); }

write32() { $SUDO "$DEVMEM" "$1" 32 "$2" >/dev/null; }
read32()  { $SUDO "$DEVMEM" "$1"; }

# ---- Main ------------------------------------------------------------------
CHANNELS=(); parse_channels "$CHSEL" CHANNELS; unique_and_validate CHANNELS
VAL_DEC=$(to_dec "$VALUE")

info "Threshold value: $VALUE ($VAL_DEC dec)"
info "Channels: ${CHANNELS[*]}"
info "Base/stride: $(printf '0x%X' $THRESH_BASE) / $STRIDE_BYTES bytes"

# Compute masks if requested
MASK_LOW_COMPUTED=""; MASK_HIGH_COMPUTED=""
if (( MASK_AUTO )); then
  local_low=0; local_high=0
  for c in "${CHANNELS[@]}"; do
    if   (( c < 32 )); then local_low=$(( local_low | (1<<c) ))
    else                    local_high=$(( local_high | (1<<(c-32)) ))
    fi
  done
  MASK_LOW_COMPUTED=$(printf "0x%X" "$local_low")
  MASK_HIGH_COMPUTED=$(printf "0x%X" "$local_high")
  info "Auto masks  low(0..31):  $MASK_LOW_COMPUTED"
  info "Auto masks high(32..63): $MASK_HIGH_COMPUTED"
fi

# Dry-run preview
if (( DRYRUN )); then
  warn "Dry-run mode: no registers will be modified"
  for c in "${CHANNELS[@]}"; do
    a=$(addr_for_channel "$c")
    echo "Would write: devmem $a 32 $VALUE   # ch $c"
  done
  # Mask preview
  if (( MASK_AUTO )) || [[ -n "$MASK_LOW_EXPL" || -n "$MASK_HIGH_EXPL" ]]; then
    [[ -n "$MASK_REG_LOW"  && ( -n "$MASK_LOW_EXPL"  || "$MASK_LOW_COMPUTED"  != "0x0" ) ]]  && \
      echo "Would write: devmem $(printf '0x%X' "$MASK_REG_LOW") 32  ${MASK_LOW_EXPL:-$MASK_LOW_COMPUTED}   # low mask"
    if [[ -n "$MASK_REG_HIGH" ]]; then
      [[ -n "$MASK_HIGH_EXPL" || "$MASK_HIGH_COMPUTED" != "0x0" ]] && \
        echo "Would write: devmem $(printf '0x%X' "$MASK_REG_HIGH") 32 ${MASK_HIGH_EXPL:-$MASK_HIGH_COMPUTED}   # high mask"
    elif (( MASK_AUTO )) && (( $(to_dec "$MASK_HIGH_COMPUTED") != 0 )); then
      warn "High channels selected but --mask2-reg not provided; high mask will NOT be written."
    fi
  fi
  exit 0
fi

# Writes
for c in "${CHANNELS[@]}"; do
  a=$(addr_for_channel "$c")
  info "Write ch $c @ $a = $VALUE"
  write32 "$a" "$VALUE"
done

# Mask writes (explicit overrides computed)
if [[ -n "$MASK_LOW_EXPL" || -n "$MASK_HIGH_EXPL" || $MASK_AUTO -eq 1 ]]; then
  if [[ -n "$MASK_REG_LOW" ]]; then
    mlow="${MASK_LOW_EXPL:-$MASK_LOW_COMPUTED}"
    if [[ -n "$mlow" && "$mlow" != "0x0" ]]; then
      info "Write low mask @ $(printf '0x%X' "$MASK_REG_LOW") = $mlow"
      write32 "$(printf '0x%X' "$MASK_REG_LOW")" "$mlow"
    fi
  fi
  if [[ -n "$MASK_REG_HIGH" ]]; then
    mhigh="${MASK_HIGH_EXPL:-$MASK_HIGH_COMPUTED}"
    if [[ -n "$mhigh" && "$mhigh" != "0x0" ]]; then
      info "Write high mask @ $(printf '0x%X' "$MASK_REG_HIGH") = $mhigh"
      write32 "$(printf '0x%X' "$MASK_REG_HIGH")" "$mhigh"
    fi
  elif (( MASK_AUTO )) && (( $(to_dec "${MASK_HIGH_COMPUTED:-0}") != 0 )); then
    warn "High channels selected but --mask2-reg not provided; skipping high mask write."
  fi
fi

# Optional readback
if (( READBACK )); then
  for c in "${CHANNELS[@]}"; do
    a=$(addr_for_channel "$c")
    v=$(read32 "$a")
    ok "Read ch $c @ $a -> $v"
  done
fi

ok "Done."
