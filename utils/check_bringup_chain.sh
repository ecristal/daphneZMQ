#!/usr/bin/env bash
set -euo pipefail

RESTART=0
TS_SAMPLES=4
JOURNAL_LINES=20

usage() {
  cat <<'EOF'
Usage: sudo bash utils/check_bringup_chain.sh [--restart] [--ts N] [--journal-lines N]

Checks the DAPHNE target-side bring-up chain:
  clockchip.service -> firmware.service -> endpoint.service -> hermes.service -> daphne.service

Options:
  --restart           Restart the full chain in dependency order before checking
  --ts N              Timestamp samples to request from endpoint.sh (default: 4)
  --journal-lines N   Number of journal lines per unit to show (default: 20)
  -h, --help          Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart) RESTART=1; shift ;;
    --ts) TS_SAMPLES="$2"; shift 2 ;;
    --journal-lines) JOURNAL_LINES="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "This script must be run as root (use sudo)." >&2
  exit 1
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ENDPOINT_SH="${SCRIPT_DIR}/endpoint.sh"
FPGA_STATE_PATH="/sys/class/fpga_manager/fpga0/state"
ENDPOINT_SUCCESS_STATES=0x8
SERVICES=(
  clockchip.service
  firmware.service
  endpoint.service
  hermes.service
  daphne.service
)

if [[ ! -x "$ENDPOINT_SH" ]]; then
  echo "ERROR: missing endpoint helper at $ENDPOINT_SH" >&2
  exit 2
fi

if [[ -r /etc/default/firmware ]]; then
  # shellcheck disable=SC1091
  . /etc/default/firmware
fi
ENDPOINT_SUCCESS_STATES="${ENDPOINT_SUCCESS_STATES:-0x8}"

show_service_state() {
  local unit="$1"
  local enabled active substate
  enabled=$(systemctl is-enabled "$unit" 2>/dev/null || true)
  active=$(systemctl is-active "$unit" 2>/dev/null || true)
  substate=$(systemctl show -p SubState --value "$unit" 2>/dev/null || true)
  printf "%-18s enabled=%-10s active=%-10s substate=%s\n" "$unit" "${enabled:-unknown}" "${active:-unknown}" "${substate:-unknown}"
}

restart_chain() {
  echo "Restarting DAPHNE bring-up chain..."
  systemctl restart clockchip.service
  systemctl restart firmware.service
  systemctl restart endpoint.service
  systemctl restart hermes.service
  systemctl restart daphne.service
}

show_journal_tail() {
  local unit="$1"
  echo
  echo "=== journal: ${unit} (last ${JOURNAL_LINES} lines) ==="
  journalctl -u "$unit" -n "$JOURNAL_LINES" --no-pager || true
}

if (( RESTART )); then
  restart_chain
fi

echo
echo "DAPHNE bring-up chain status"
echo "============================"
for unit in "${SERVICES[@]}"; do
  show_service_state "$unit"
done

echo
if [[ -r "$FPGA_STATE_PATH" ]]; then
  echo "FPGA state: $(cat "$FPGA_STATE_PATH")"
else
  echo "FPGA state: unavailable ($FPGA_STATE_PATH not readable)"
fi

echo
echo "Endpoint status probe"
echo "====================="
"$ENDPOINT_SH" --success-states "$ENDPOINT_SUCCESS_STATES" -t "$TS_SAMPLES"

for unit in "${SERVICES[@]}"; do
  show_journal_tail "$unit"
done
