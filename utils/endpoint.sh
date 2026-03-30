#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# DAPHNE v3 – Timing Endpoint status (default) or bring-up (with --configure)
# - Default: read-only status (no writes), decodes clock + endpoint state
# - --configure: set clock source, pulse resets, set endpoint addr, optional trigger
# - Optional timestamp probe in both modes
# -----------------------------------------------------------------------------
set -euo pipefail

# ---- Styling ---------------------------------------------------------------
BOLD='\033[1m'; DIM='\033[2m'; RED='\033[31m'; GRN='\033[32m'; YLW='\033[33m'; CYA='\033[36m'; RST='\033[0m'
info()  { echo -e "${CYA}ℹ${RST}  $*"; }
ok()    { echo -e "${GRN}✔${RST}  $*"; }
warn()  { echo -e "${YLW}▲${RST}  $*"; }
err()   { echo -e "${RED}✖${RST}  $*" 1>&2; }
head1() { echo -e "\n${BOLD}$*${RST}"; }

# ---- Defaults --------------------------------------------------------------
DO_CONFIG=0                 # <-- new: default is status-only
DO_TRIGGER=0                # trigger is opt-in now
EP_ADDR_HEX="0x20"          # used only in --configure path
CLOCK_MODE="endpoint"       # endpoint|local (used if --configure)
TS_PROBE_N=0                # number of timestamp samples (0 = disabled)
TS_INTERVAL_MS=10           # ms between timestamp samples
WAIT_MS=1000                # wait for READY (configure path)
POLL_MS=100                 # poll interval

usage() {
  cat <<EOF
Usage: sudo bash $0 [--configure] [--trigger] [--addr 0x20] [--clock endpoint|local]
                   [-t N] [--ts-interval-ms MS] [--wait-ms MS] [--poll-ms MS]
Modes:
  (default)   Status-only (read-only): prints clock+endpoint state and exits
  --configure Bring-up: select clock, pulse resets, set endpoint addr, optional trigger

Options:
  --configure           Perform configuration writes (otherwise read-only)
  --trigger             Send single 0xBABA trigger (only meaningful with --configure)
  -a, --addr 0xHEX      Endpoint address (16-bit, default ${EP_ADDR_HEX})
  --clock MODE          'endpoint' or 'local' (configure path)
  -t, --ts N            Timestamp probe samples (works in either mode)
  --ts-interval-ms MS   Interval between ts samples (default ${TS_INTERVAL_MS})
  --wait-ms MS          Wait budget for lock/READY (default ${WAIT_MS})
  --poll-ms MS          Poll interval (default ${POLL_MS})
  -h, --help            Show this help
EOF
}

# ---- Args ------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --configure)         DO_CONFIG=1; shift ;;
    --trigger)           DO_TRIGGER=1; shift ;;
    -a|--addr)           EP_ADDR_HEX="$2"; shift 2 ;;
    --clock)             CLOCK_MODE="$2"; shift 2 ;;
    -t|--ts)             TS_PROBE_N="$2"; shift 2 ;;
    --ts-interval-ms)    TS_INTERVAL_MS="$2"; shift 2 ;;
    --wait-ms)           WAIT_MS="$2"; shift 2 ;;
    --poll-ms)           POLL_MS="$2"; shift 2 ;;
    -h|--help)           usage; exit 0 ;;
    *) err "Unknown option: $1"; usage; exit 2 ;;
  esac
done

# ---- devmem / sudo ---------------------------------------------------------
if command -v devmem >/dev/null 2>&1; then DEVMEM="devmem"
elif [[ -x /usr/sbin/devmem ]]; then DEVMEM="/usr/sbin/devmem"
elif [[ -x /usr/bin/devmem ]]; then DEVMEM="/usr/bin/devmem"
else err "devmem not found"; exit 2; fi
SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"
FPGA_STATE_PATH="/sys/class/fpga_manager/fpga0/state"

wr32(){ $SUDO "$DEVMEM" "$1" 32 "$2" >/dev/null; }
rd32(){ $SUDO "$DEVMEM" "$1"; }

require_fpga_operating(){
  if [[ ! -r "$FPGA_STATE_PATH" ]]; then
    err "FPGA manager state file not readable: $FPGA_STATE_PATH"
    return 2
  fi
  local st
  st=$(cat "$FPGA_STATE_PATH" 2>/dev/null || echo unknown)
  if [[ "$st" != "operating" ]]; then
    err "FPGA is not in 'operating' state (state=$st). Load the PL before touching endpoint registers."
    return 2
  fi
}

# ---- Address Map -----------------------------------------------------------
EP_BASE=0x84000000
EP_CLK_CTRL=$((EP_BASE + 0x0))   # bit2: clk src (0=local,1=endpoint), bit1: MMCM1 rst, bit0: soft rst
EP_CLK_STAT=$((EP_BASE + 0x4))   # bit1: MMCM1 lock, bit0: MMCM0 lock
EP_CTRL=$((EP_BASE + 0x8))       # bit16: EP rst, bits15..0: EP addr (WO on some builds)
EP_STAT=$((EP_BASE + 0xC))       # bit4: timestamp ok, bits3..0: state

FRONTEND_BASE=0x88000000
FRONTEND_TRIGGER=$((FRONTEND_BASE + 0x8))    # 0xBABA

# TE timestamps (RO)
TE_TS0=0x9002D000
TE_TS1=0x9002E000
TE_TS2=0x9002F000
TE_TS3=0x90030000

# ---- Helpers ---------------------------------------------------------------
bit_set(){ (( ($1 & (1<<$2)) != 0  )); }

decode_clk_status(){
  local v=$1
  local m0; bit_set "$v" 0 && m0="LOCKED" || m0="UNLOCKED"
  local m1; bit_set "$v" 1 && m1="LOCKED" || m1="UNLOCKED"
  echo "MMCM0: $m0 | MMCM1: $m1"
}

ep_state_name(){
  case "$1" in
    0x0|0)  echo "ST_RESET (held in reset)";;
    0x1|1)  echo "ST_W_CLK (wait PLL lock)";;
    0x2|2)  echo "ST_W_FREQ (measure RX clock freq)";;
    0x3|3)  echo "ST_W_CDR (wait CDR lock)";;
    0x4|4)  echo "ST_W_RX (wait comma align)";;
    0x5|5)  echo "ST_W_ADDR (wait address set)";;
    0x6|6)  echo "ST_W_SETUP (wait register setup)";;
    0x7|7)  echo "ST_W_TS (wait timestamp broadcast)";;
    0x8|8)  echo "ST_READY (operational)";;
    0xC|12) echo "ST_ERR_P (physical layer error)";;
    0xD|13) echo "ST_ERR_R (receiver/protocol error)";;
    0xE|14) echo "ST_ERR_T (timestamp misalignment)";;
    0xF|15) echo "ST_ERR_X (control packet error)";;
    *)      printf "UNKNOWN (0x%X)" "$1";;
  esac
}

decode_ep_status(){
  local v=$1
  local ts_ok="NO"; bit_set "$v" 4 && ts_ok="YES"
  local st_hex=$(( v & 0xF ))
  local st_name; st_name=$(ep_state_name "$st_hex")
  printf "timestamp_ok=%s | state=0x%X (%s)" "$ts_ok" "$st_hex" "$st_name"
}

# Millisecond sleep: prefer usleep; fallback to fractional sleep
msleep(){
  local ms="$1"
  if command -v usleep >/dev/null 2>&1; then
    usleep $(( ms * 1000 ))
  else
    local s; s=$(awk -v ms="$ms" 'BEGIN{printf "%.3f", ms/1000}')
    sleep "$s"
  fi
}

wait_for_lock(){
  local t_ms="$WAIT_MS" step_ms="$POLL_MS" waited=0 v_hex v
  while (( waited < t_ms )); do
    v_hex=$(rd32 "$(printf '0x%X' "$EP_CLK_STAT")"); v=$(( v_hex ))
    if bit_set "$v" 0 && bit_set "$v" 1; then
      ok "Clocks locked: $(decode_clk_status "$v") (raw=$(printf '0x%X' "$v"))"; return 0
    fi
    msleep "$step_ms"; (( waited += step_ms ))
  done
  err "Clocks NOT locked after ${t_ms} ms: $(decode_clk_status $((v))) (raw=$v_hex)"; return 1
}

wait_for_endpoint_ready(){
  local t_ms="$WAIT_MS" step_ms="$POLL_MS" waited=0 v_hex v st ts_ok
  while (( waited < t_ms )); do
    v_hex=$(rd32 "$(printf '0x%X' "$EP_STAT")"); v=$(( v_hex )); st=$(( v & 0xF ))
    ts_ok=0; bit_set "$v" 4 && ts_ok=1
    case "$st" in
      0x8|8)
        if (( ts_ok == 1 )); then
          ok "Endpoint READY: $(decode_ep_status "$v") (raw=$(printf '0x%X' "$v"))"; return 0
        fi
        ;;
      0xC|12|0xD|13|0xE|14|0xF|15)
        err "Endpoint ERROR state: $(decode_ep_status "$v") (raw=$v_hex)"; return 2;;
      *) ;;
    esac
    msleep "$step_ms"; (( waited += step_ms ))
  done
  warn "Endpoint not READY after ${t_ms} ms: $(decode_ep_status $((v))) (raw=$v_hex)"; return 1
}

read_ts_regs(){
  local v0 v1 v2 v3
  v0=$(rd32 "$TE_TS0"); v1=$(rd32 "$TE_TS1"); v2=$(rd32 "$TE_TS2"); v3=$(rd32 "$TE_TS3")
  echo "$v0 $v1 $v2 $v3"
}
hex_to_dec(){ printf "%d" "$(( $1 ))"; }
pack_u64_le(){ printf "%u" $(( ( ($2) << 32 ) | ( ($1) & 0xFFFFFFFF ) )); }

probe_timestamps(){
  (( TS_PROBE_N > 0 )) || return 0
  head1 "Timestamp Probe ($TS_PROBE_N samples, every ${TS_INTERVAL_MS} ms)"
  printf "%-6s  %-12s %-12s %-12s %-12s  |  %-14s %-18s\n" \
    "idx" "TS0(hex)" "TS1(hex)" "TS2(hex)" "TS3(hex)" "TS0(dec)" "TS01_u64(dec)"
  local prev0=""
  local i
  for ((i=0;i<TS_PROBE_N;i++)); do
    read v0 v1 v2 v3 < <(read_ts_regs)
    local ts0_dec; ts0_dec=$(hex_to_dec "$v0")
    local ts01_u64; ts01_u64=$(pack_u64_le "$v0" "$v1")
    printf "%-6d  %-12s %-12s %-12s %-12s  |  %-14s %-18s\n" \
      "$i" "$v0" "$v1" "$v2" "$v3" "$ts0_dec" "$ts01_u64"
    if [[ -n "$prev0" ]]; then
      local delta=$(( ts0_dec - prev0 ))
      echo -e "       ${DIM}ΔTS0=${delta}${RST}"
    fi
    prev0="$ts0_dec"
    (( i+1 < TS_PROBE_N )) && msleep "$TS_INTERVAL_MS"
  done
}

set_clock(){
  local mode="$1"
  head1 "Clock Select ($mode)"
  case "$mode" in
    endpoint)
      info "Select endpoint clock + pulse MMCM1 reset"
      wr32 "$(printf '0x%X' "$EP_CLK_CTRL")" 0x6    # bit2=1 (endpoint), bit1=1 (rst)
      wr32 "$(printf '0x%X' "$EP_CLK_CTRL")" 0x4    # release reset, keep endpoint clock
      ;;
    local)
      info "Select local clock + pulse MMCM1 reset"
      wr32 "$(printf '0x%X' "$EP_CLK_CTRL")" 0x2    # bit2=0 (local), bit1=1 (rst)
      wr32 "$(printf '0x%X' "$EP_CLK_CTRL")" 0x0    # release reset, keep local clock
      ;;
    *) err "Unknown clock mode: $mode"; exit 2 ;;
  esac
  local cs_hex; cs_hex=$(rd32 "$(printf '0x%X' "$EP_CLK_STAT")")
  info "Clock status: $(decode_clk_status $((cs_hex))) (raw=$cs_hex)"
  wait_for_lock
}

set_endpoint_addr(){
  head1 "Endpoint Address & Reset"
  local addr16=$(( EP_ADDR_HEX & 0xFFFF ))
  info "Set EP addr=0x$(printf '%X' "$addr16") with reset pulse"
  wr32 "$(printf '0x%X' "$EP_CTRL")" $(( 0x10000 | addr16 ))  # assert EP reset with addr
  wr32 "$(printf '0x%X' "$EP_CTRL")" $(( addr16 ))            # release reset, keep addr
  local es_hex; es_hex=$(rd32 "$(printf '0x%X' "$EP_STAT")")
  info "Endpoint status: $(decode_ep_status $((es_hex))) (raw=$es_hex)"
  wait_for_endpoint_ready
}

do_trigger_once(){
  head1 "Front-end: Single Trigger"
  info "Write 0xBABA @ $(printf '0x%X' "$FRONTEND_TRIGGER")"
  wr32 "$(printf '0x%X' "$FRONTEND_TRIGGER")" 0xBABA
  ok "Trigger sent."
}

print_status(){
  head1 "Timing Endpoint Status"
  local clk_hex ep_hex
  clk_hex=$(rd32 "$(printf '0x%X' "$EP_CLK_STAT")")
  ep_hex=$(rd32 "$(printf '0x%X' "$EP_STAT")")
  echo -e "  Clock status : $(decode_clk_status $((clk_hex))) (raw=$clk_hex)"
  echo -e "  EP status    : $(decode_ep_status $((ep_hex))) (raw=$ep_hex)"
  echo -e "  EP addr (arg): 0x$(printf '%X' $((EP_ADDR_HEX & 0xFFFF)))"
  # Exit codes for quick scripting:
  local st=$(( ep_hex & 0xF ))
  local ts_ok=0; bit_set "$((ep_hex))" 4 && ts_ok=1
  case "$st" in
    0x8|8)   (( ts_ok == 1 )) && return 0 || return 1 ;;  # READY only if timestamp valid
    0xC|12|0xD|13|0xE|14|0xF|15) return 2 ;;  # error states
    *)       return 1 ;;             # not ready yet
  esac
}

# ---- Run -------------------------------------------------------------------
require_fpga_operating

if (( DO_CONFIG )); then
  head1 "Configuring Timing Endpoint"
  set_clock "$CLOCK_MODE"
  set_endpoint_addr
  (( DO_TRIGGER )) && do_trigger_once
  head1 "Summary"
  print_status
else
  # Status-only, no writes
  print_status
fi

probe_timestamps
ok "Done."
