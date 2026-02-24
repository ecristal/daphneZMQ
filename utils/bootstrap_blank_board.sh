#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root (use sudo)." >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INVENTORY="${INVENTORY:-$SCRIPT_DIR/ff0b_board_inventory.csv}"
BOARD_ID_RAW="${1:-$(hostname -s 2>/dev/null || hostname)}"
NO_FIRMWARE=0
BOOTSTRAP_ONLY=0
WAIT_NTP=1

usage() {
  cat <<'USAGE_EOF'
Usage:
  sudo ./bootstrap_blank_board.sh [board_id] [options]

Options:
  --no-firmware      Skip setup_firmware_service.sh
  --bootstrap-only   Do only emergency network + DNS + NTP bootstrap
  --no-wait-ntp      Do not wait for NTPSynchronized=yes
  -h, --help         Show this help

Examples:
  sudo ./bootstrap_blank_board.sh daphne-15
  sudo FW_APP=MEZ_SELF_TRIG_V15_OL_UPGRADED ./bootstrap_blank_board.sh daphne-13
  sudo ./bootstrap_blank_board.sh daphne-14 --bootstrap-only
USAGE_EOF
}

normalize_board_id() {
  v=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  case "$v" in
    daphne-[0-9]*)
      printf '%s\n' "$v"
      ;;
    *)
      n=$(printf '%s' "$v" | sed -n 's/.*daphne-\([0-9][0-9]*\).*/\1/p')
      if [ -n "$n" ]; then
        n=$(printf '%s' "$n" | sed 's/^0*//')
        [ -n "$n" ] || n=0
        printf 'daphne-%s\n' "$n"
      else
        printf '%s\n' "$v"
      fi
      ;;
  esac
}

BOARD_ID="$(normalize_board_id "$BOARD_ID_RAW")"

for arg in "$@"; do
  case "$arg" in
    --no-firmware) NO_FIRMWARE=1 ;;
    --bootstrap-only) BOOTSTRAP_ONLY=1 ;;
    --no-wait-ntp) WAIT_NTP=0 ;;
    -h|--help)
      usage
      exit 0
      ;;
    daphne-*)
      ;;
    *)
      if [ "$arg" != "$1" ]; then
        echo "Unknown option: $arg" >&2
        usage >&2
        exit 2
      fi
      ;;
  esac
done

if [ ! -r "$INVENTORY" ]; then
  echo "ERROR: inventory not found: $INVENTORY" >&2
  exit 2
fi

ROW=$(
  awk -F',' -v b="$BOARD_ID" '
    function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
    /^[ \t]*#/ { next }
    NF < 8 { next }
    {
      id = tolower(trim($1))
      if (id == tolower(b)) {
        printf "%s|%s|%s|%s|%s|%s|%s|%s\n",
          trim($1), trim($3), trim($4), trim($5), trim($6),
          tolower(trim($7)), tolower(trim($8)), trim($2)
        exit
      }
    }
  ' "$INVENTORY"
)

if [ -z "$ROW" ]; then
  echo "ERROR: board '$BOARD_ID' not found in $INVENTORY" >&2
  exit 3
fi

IFS='|' read -r BOARD_ID IPV4_CIDR GW4 DNS1 DNS2 MAC_FF0B MAC_FF0C HOST_FQDN <<EOF
$ROW
EOF

if [ -z "$IPV4_CIDR" ] || [ -z "$GW4" ] || [ -z "$MAC_FF0B" ]; then
  echo "ERROR: incomplete network row for '$BOARD_ID'" >&2
  exit 4
fi

first_netdev_from_path() {
  p="$1"
  for n in "$p"/net/*; do
    [ -e "$n" ] || continue
    basename "$n"
    return 0
  done
  return 1
}

wait_for_netdev() {
  p="$1"
  timeout="${2:-60}"
  i=0
  while [ "$i" -lt "$timeout" ]; do
    if first_netdev_from_path "$p" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}

FF0B_PATH="/sys/devices/platform/axi/ff0b0000.ethernet"
FF0C_PATH="/sys/devices/platform/axi/ff0c0000.ethernet"

echo "[1/4] Bringing emergency network up on ff0b..."
wait_for_netdev "$FF0B_PATH" 60 || {
  echo "ERROR: ff0b netdev not found under $FF0B_PATH/net" >&2
  exit 5
}
FF0B_IF="$(first_netdev_from_path "$FF0B_PATH")"
FF0C_IF=""
if wait_for_netdev "$FF0C_PATH" 5; then
  FF0C_IF="$(first_netdev_from_path "$FF0C_PATH" || true)"
fi

for n in /sys/class/net/eth*; do
  [ -e "$n" ] || continue
  d=$(basename "$n")
  ip link set "$d" down || true
  ip addr flush dev "$d" || true
done
while ip route del default 2>/dev/null; do :; done

ip link set "$FF0B_IF" address "$MAC_FF0B" || true
ip link set "$FF0B_IF" up

if [ -n "$FF0C_IF" ] && [ -n "$MAC_FF0C" ]; then
  ip link set "$FF0C_IF" address "$MAC_FF0C" || true
  ip link set "$FF0C_IF" up || true
fi

ip addr replace "$IPV4_CIDR" dev "$FF0B_IF"
ip route replace default via "$GW4" dev "$FF0B_IF"

{
  echo "nameserver $DNS1"
  [ -n "$DNS2" ] && echo "nameserver $DNS2"
  echo "options timeout:1 attempts:2"
} > /etc/resolv.conf

echo "[2/4] Configuring NTP sync..."
install -d /etc/systemd/timesyncd.conf.d
cat <<EOF > /etc/systemd/timesyncd.conf.d/cern.conf
[Time]
NTP=137.138.16.69 137.138.17.69 137.138.18.69
FallbackNTP=
EOF
systemctl enable --now systemd-timesyncd >/dev/null 2>&1 || true
timedatectl set-ntp true >/dev/null 2>&1 || true

if [ "$WAIT_NTP" -eq 1 ] && command -v timedatectl >/dev/null 2>&1; then
  i=0
  while [ $i -lt 45 ]; do
    sync_state=$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo "no")
    [ "$sync_state" = "yes" ] && break
    sleep 1
    i=$((i + 1))
  done
fi

if [ "$BOOTSTRAP_ONLY" -eq 1 ]; then
  echo
  echo "Bootstrap-only mode complete."
  echo "ff0b interface: $FF0B_IF"
  ip -4 addr show dev "$FF0B_IF" || true
  ip route || true
  timedatectl status || true
  exit 0
fi

echo "[3/4] Installing persistent network baseline..."
if [ ! -r "$SCRIPT_DIR/install_ff0b_network.sh" ]; then
  echo "ERROR: missing $SCRIPT_DIR/install_ff0b_network.sh" >&2
  exit 6
fi
sh "$SCRIPT_DIR/install_ff0b_network.sh" "$BOARD_ID"

if [ "$NO_FIRMWARE" -eq 0 ]; then
  echo "[4/4] Installing firmware boot service..."
  if [ ! -r "$SCRIPT_DIR/setup_firmware_service.sh" ]; then
    echo "ERROR: missing $SCRIPT_DIR/setup_firmware_service.sh" >&2
    exit 7
  fi
  sh "$SCRIPT_DIR/setup_firmware_service.sh"
  systemctl restart firmware.service || true
else
  echo "[4/4] Skipping firmware setup (--no-firmware)."
fi

echo
echo "Bootstrap completed for $BOARD_ID"
echo "Host target: ${HOST_FQDN}"
echo "ff0b interface: $FF0B_IF"
echo
echo "Verify:"
echo "  timedatectl status"
echo "  ip -br link"
echo "  ip -4 addr"
echo "  ip route"
echo "  systemctl status force-ff0b-net.service --no-pager"
echo "  systemctl status firmware.service --no-pager"
