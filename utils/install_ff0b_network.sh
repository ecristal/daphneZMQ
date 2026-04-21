#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root (use sudo)." >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INVENTORY="${INVENTORY:-$SCRIPT_DIR/ff0b_board_inventory.csv}"
BOARD_ID_RAW="${1:-$(hostname -s 2>/dev/null || hostname)}"

normalize_board_id() {
  v=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  case "$v" in
    daphne-[0-9]*)
      printf '%s\n' "$v"
      return 0
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
      return 0
      ;;
  esac
}

BOARD_ID="$(normalize_board_id "$BOARD_ID_RAW")"

usage() {
  cat <<'USAGE_EOF'
Usage:
  sudo ./install_ff0b_network.sh [board_id]

Examples:
  sudo ./install_ff0b_network.sh daphne-13
  sudo INVENTORY=/path/to/ff0b_board_inventory.csv ./install_ff0b_network.sh daphne-15

What this installs:
  - Deterministic ff0b/ff0c MAC + IP routing at every boot
  - DNS resolver file (/etc/resolv.conf) refresh at every boot
  - CERN NTP config + timesync bootstrap (no hardcoded date)
  - Board-specific endpoint address in /etc/default/ff0b-net.conf
  - Default proxy env + git proxy config
  - Colored interactive shell prompt
USAGE_EOF
}

if [ "${BOARD_ID:-}" = "-h" ] || [ "${BOARD_ID:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ ! -r "$INVENTORY" ]; then
  echo "ERROR: inventory not found: $INVENTORY" >&2
  exit 2
fi

ROW=$(awk -F',' -v b="$BOARD_ID" '
  function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
  /^[ \t]*#/ { next }
  NF < 8 { next }
  {
    id = tolower(trim($1))
    if (id == tolower(b)) {
      printf "%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n",
        trim($1), trim($2), trim($3), trim($4), trim($5),
        trim($6), tolower(trim($7)), tolower(trim($8)),
        trim($9), trim($10), trim($11)
      exit
    }
  }
' "$INVENTORY")

if [ -z "$ROW" ]; then
  echo "ERROR: board '$BOARD_ID' not found in $INVENTORY" >&2
  echo "Known boards:" >&2
  awk -F',' '
    /^[ \t]*#/ { next }
    NF > 0 { gsub(/^[ \t]+|[ \t]+$/, "", $1); if ($1 != "") print "  - " $1 }
  ' "$INVENTORY" >&2
  exit 3
fi

IFS='|' read -r BOARD_ID HOST_FQDN IPV4_CIDR GW4 DNS1 DNS2 MAC_FF0B MAC_FF0C IPV6_CIDR GW6 ENDPOINT_ADDR_HEX <<EOF
$ROW
EOF

if [ -z "$BOARD_ID" ] || [ -z "$IPV4_CIDR" ] || [ -z "$GW4" ] || [ -z "$MAC_FF0B" ]; then
  echo "ERROR: incomplete row for board '$BOARD_ID' in $INVENTORY" >&2
  exit 4
fi

ENDPOINT_ADDR_HEX="${ENDPOINT_ADDR_HEX:-0x20}"

PROXY_URL="${PROXY_URL:-http://np04-web-proxy.cern.ch:3128}"
NO_PROXY_VALUE="${NO_PROXY_VALUE:-.cern.ch}"
NTP1="${NTP1:-137.138.16.69}"
NTP2="${NTP2:-137.138.17.69}"
NTP3="${NTP3:-137.138.18.69}"

first_netdev_from_dir() {
  p="$1"
  for n in "$p"/net/*; do
    [ -e "$n" ] || continue
    basename "$n"
    return 0
  done
  return 1
}

resolve_platform_path() {
  token="$1"
  for p in \
    "/sys/bus/platform/devices/$token" \
    /sys/bus/platform/devices/*"$token" \
    "/sys/devices/platform/$token" \
    "/sys/devices/platform/axi/$token"
  do
    [ -e "$p" ] || continue
    readlink -f "$p" 2>/dev/null || printf '%s\n' "$p"
    return 0
  done

  for n in /sys/class/net/*; do
    [ -e "$n" ] || continue
    dev_path=$(readlink -f "$n/device" 2>/dev/null || true)
    case "$dev_path" in
      *"/$token")
        printf '%s\n' "$dev_path"
        return 0
        ;;
    esac
  done

  return 1
}

first_netdev_for_token() {
  token="$1"
  p=$(resolve_platform_path "$token" 2>/dev/null || true)
  [ -n "$p" ] || return 1
  first_netdev_from_dir "$p"
}

match_path_for_if() {
  iface="$1"
  command -v udevadm >/dev/null 2>&1 || return 1

  dev_path=$(udevadm info -q path -n "$iface" 2>/dev/null || true)
  [ -n "$dev_path" ] || return 1

  udevadm info -q property -p "$dev_path" 2>/dev/null | awk -F= '
    $1 == "ID_PATH" { print $2; exit }
  '
}

emit_match_block() {
  match_path="$1"
  match_name="$2"
  fallback_token="$3"

  echo "[Match]"
  if [ -n "$match_path" ]; then
    echo "Path=$match_path"
  elif [ -n "$match_name" ]; then
    echo "Name=$match_name"
  else
    echo "Path=platform-$fallback_token"
  fi
}

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
NETWORKD_BACKUP="/etc/systemd/network/backup-pre-ff0b-${TIMESTAMP}"
install -d /etc/systemd/network /etc/default /usr/local/sbin /etc/systemd/system /etc/profile.d /etc/systemd/timesyncd.conf.d "$NETWORKD_BACKUP"

for f in /etc/systemd/network/*.link /etc/systemd/network/*.network; do
  [ -e "$f" ] || continue
  mv "$f" "$NETWORKD_BACKUP/"
done

FF0B_IF_CURRENT="$(first_netdev_for_token "ff0b0000.ethernet" 2>/dev/null || true)"
FF0C_IF_CURRENT="$(first_netdev_for_token "ff0c0000.ethernet" 2>/dev/null || true)"
FF0B_MATCH_PATH=""
FF0C_MATCH_PATH=""

if [ -n "$FF0B_IF_CURRENT" ]; then
  FF0B_MATCH_PATH="$(match_path_for_if "$FF0B_IF_CURRENT" 2>/dev/null || true)"
else
  echo "WARNING: ff0b interface not detected during install; boot-time service will retry." >&2
fi
if [ -n "$FF0C_IF_CURRENT" ]; then
  FF0C_MATCH_PATH="$(match_path_for_if "$FF0C_IF_CURRENT" 2>/dev/null || true)"
fi

cat <<EOF > /etc/default/ff0b-net.conf
BOARD_ID=${BOARD_ID}
HOST_FQDN=${HOST_FQDN}
IPV4_CIDR=${IPV4_CIDR}
GW4=${GW4}
DNS1=${DNS1}
DNS2=${DNS2}
MAC_FF0B=${MAC_FF0B}
MAC_FF0C=${MAC_FF0C}
IPV6_CIDR=${IPV6_CIDR}
GW6=${GW6}
ENDPOINT_ADDR_HEX=${ENDPOINT_ADDR_HEX}
NTP1=${NTP1}
NTP2=${NTP2}
NTP3=${NTP3}
PROXY_URL=${PROXY_URL}
NO_PROXY_VALUE=${NO_PROXY_VALUE}
EOF

cat <<'APPLY_EOF' > /usr/local/sbin/ff0b-net-apply.sh
#!/bin/sh
set -eu

CONF="/etc/default/ff0b-net.conf"
[ -r "$CONF" ] || { echo "missing $CONF" >&2; exit 1; }
. "$CONF"

first_netdev_from_dir() {
  p="$1"
  for n in "$p"/net/*; do
    [ -e "$n" ] || continue
    basename "$n"
    return 0
  done
  return 1
}

resolve_platform_path() {
  token="$1"
  for p in \
    "/sys/bus/platform/devices/$token" \
    /sys/bus/platform/devices/*"$token" \
    "/sys/devices/platform/$token" \
    "/sys/devices/platform/axi/$token"
  do
    [ -e "$p" ] || continue
    readlink -f "$p" 2>/dev/null || printf '%s\n' "$p"
    return 0
  done

  for n in /sys/class/net/*; do
    [ -e "$n" ] || continue
    dev_path=$(readlink -f "$n/device" 2>/dev/null || true)
    case "$dev_path" in
      *"/$token")
        printf '%s\n' "$dev_path"
        return 0
        ;;
    esac
  done

  return 1
}

first_netdev_for_token() {
  token="$1"
  p=$(resolve_platform_path "$token" 2>/dev/null || true)
  [ -n "$p" ] || return 1
  first_netdev_from_dir "$p"
}

wait_for_netdev_token() {
  token="$1"
  timeout="${2:-60}"
  i=0
  while [ "$i" -lt "$timeout" ]; do
    if first_netdev_for_token "$token" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}

print_detected_netdevs() {
  echo "Detected netdevs:" >&2
  for n in /sys/class/net/*; do
    [ -e "$n" ] || continue
    d=$(basename "$n")
    dev_path=$(readlink -f "$n/device" 2>/dev/null || echo "no-device")
    echo "  - $d -> $dev_path" >&2
  done
}

FF0B_TOKEN="ff0b0000.ethernet"
FF0C_TOKEN="ff0c0000.ethernet"

wait_for_netdev_token "$FF0B_TOKEN" 60 || {
  echo "ff0b netdev not found for token $FF0B_TOKEN" >&2
  print_detected_netdevs
  exit 2
}

FF0B_IF=$(first_netdev_for_token "$FF0B_TOKEN")
FF0C_IF=$(first_netdev_for_token "$FF0C_TOKEN" 2>/dev/null || true)

# Prevent split-brain routing from stale configs.
ip addr flush dev "$FF0B_IF" || true
[ -n "$FF0C_IF" ] && ip addr flush dev "$FF0C_IF" || true
while ip route del default 2>/dev/null; do :; done

ip link set "$FF0B_IF" down || true
[ -n "${MAC_FF0B:-}" ] && ip link set "$FF0B_IF" address "$MAC_FF0B" || true
ip link set "$FF0B_IF" up

if [ -n "$FF0C_IF" ]; then
  ip link set "$FF0C_IF" down || true
  [ -n "${MAC_FF0C:-}" ] && ip link set "$FF0C_IF" address "$MAC_FF0C" || true
  ip link set "$FF0C_IF" up || true
fi

ip addr replace "$IPV4_CIDR" dev "$FF0B_IF"
ip route replace default via "$GW4" dev "$FF0B_IF"

# Keep resolver deterministic (some images lose DNS after boot).
if [ -n "${DNS1:-}" ]; then
  {
    echo "nameserver $DNS1"
    [ -n "${DNS2:-}" ] && echo "nameserver $DNS2"
    echo "options timeout:1 attempts:2"
  } > /etc/resolv.conf
fi

if [ -n "${IPV6_CIDR:-}" ]; then
  ip -6 addr replace "$IPV6_CIDR" dev "$FF0B_IF" 2>/dev/null || true
fi
if [ -n "${GW6:-}" ]; then
  ip -6 route replace default via "$GW6" dev "$FF0B_IF" 2>/dev/null || true
fi

# Restart timesync after network+DNS are in place.
systemctl enable systemd-timesyncd >/dev/null 2>&1 || true
systemctl restart systemd-timesyncd >/dev/null 2>&1 || true
timedatectl set-ntp true >/dev/null 2>&1 || true

# Give NTP a short settle window; keep boot non-fatal if unreachable.
if command -v timedatectl >/dev/null 2>&1; then
  i=0
  while [ $i -lt 45 ]; do
    sync_state=$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo "no")
    [ "$sync_state" = "yes" ] && break
    sleep 1
    i=$((i + 1))
  done
fi
APPLY_EOF

chmod 0755 /usr/local/sbin/ff0b-net-apply.sh

cat <<EOF > /etc/systemd/timesyncd.conf.d/cern.conf
[Time]
NTP=${NTP1} ${NTP2} ${NTP3}
FallbackNTP=
EOF

cat <<EOF > /etc/profile.d/np04-proxy.sh
export HTTP_PROXY=${PROXY_URL}
export HTTPS_PROXY=${PROXY_URL}
export NO_PROXY=${NO_PROXY_VALUE}
export http_proxy=${PROXY_URL}
export https_proxy=${PROXY_URL}
export no_proxy=${NO_PROXY_VALUE}
EOF
chmod 0644 /etc/profile.d/np04-proxy.sh

cat <<'EOF' > /etc/profile.d/np04-prompt.sh
# Interactive shell prompt colors for DAPHNE boards.
case "$-" in
  *i*) ;;
  *) return 0 2>/dev/null || exit 0 ;;
esac

if [ -n "${BASH_VERSION:-}" ]; then
  PS1='\[\033[1;36m\]\u@\h\[\033[0m\]:\[\033[1;33m\]\w\[\033[0m\]\$ '
else
  PS1='\033[1;36m\u@\h\033[0m:\033[1;33m\w\033[0m\$ '
fi
export PS1
EOF
chmod 0644 /etc/profile.d/np04-prompt.sh

# Some Petalinux images reset PS1 after /etc/profile.d is sourced.
# Install a user-level fallback so login shells keep the colored prompt.
PETALINUX_HOME="/home/petalinux"
if [ -d "$PETALINUX_HOME" ]; then
  PETALINUX_PROFILE="$PETALINUX_HOME/.profile"
  touch "$PETALINUX_PROFILE"
  if ! grep -q 'NP04_PROMPT_BEGIN' "$PETALINUX_PROFILE"; then
    cat <<'EOF' >> "$PETALINUX_PROFILE"

# NP04_PROMPT_BEGIN
case "$-" in
  *i*)
    PS1='\033[1;36m\u@\h\033[0m:\033[1;33m\w\033[0m\$ '
    export PS1
    ;;
esac
# NP04_PROMPT_END
EOF
  fi
  chown petalinux:petalinux "$PETALINUX_PROFILE" 2>/dev/null || true
fi

{
  emit_match_block "$FF0B_MATCH_PATH" "$FF0B_IF_CURRENT" "ff0b0000.ethernet"
  echo
  echo "[Link]"
  echo "MACAddress=${MAC_FF0B}"
  echo "MACAddressPolicy=none"
} > /etc/systemd/network/10-ff0b.link

{
  emit_match_block "$FF0C_MATCH_PATH" "$FF0C_IF_CURRENT" "ff0c0000.ethernet"
  echo
  echo "[Link]"
  echo "MACAddress=${MAC_FF0C}"
  echo "MACAddressPolicy=none"
} > /etc/systemd/network/11-ff0c.link

{
  emit_match_block "$FF0B_MATCH_PATH" "$FF0B_IF_CURRENT" "ff0b0000.ethernet"
  echo
  echo "[Network]"
  echo "Address=${IPV4_CIDR}"
  echo "Gateway=${GW4}"
  echo "DNS=${DNS1}"
  echo "DNS=${DNS2}"
} > /etc/systemd/network/20-ff0b.network

{
  emit_match_block "$FF0C_MATCH_PATH" "$FF0C_IF_CURRENT" "ff0c0000.ethernet"
  echo
  echo "[Network]"
  echo "DHCP=no"
  echo "LinkLocalAddressing=no"
  echo "IPv6AcceptRA=no"
} > /etc/systemd/network/21-ff0c.network

cat <<'SERVICE_EOF' > /etc/systemd/system/force-ff0b-net.service
[Unit]
Description=Force deterministic ff0b uplink network
After=local-fs.target systemd-udevd.service systemd-networkd.service
Wants=systemd-udevd.service systemd-networkd.service
Before=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/ff0b-net-apply.sh
RemainAfterExit=yes
TimeoutStartSec=90
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
SERVICE_EOF

chmod 0644 /etc/systemd/system/force-ff0b-net.service /etc/systemd/network/10-ff0b.link /etc/systemd/network/11-ff0c.link /etc/systemd/network/20-ff0b.network /etc/systemd/network/21-ff0c.network /etc/default/ff0b-net.conf

if [ "${SET_HOSTNAME:-1}" = "1" ] && command -v hostnamectl >/dev/null 2>&1 && [ -n "$HOST_FQDN" ]; then
  hostnamectl set-hostname "$HOST_FQDN" || true
fi

if command -v git >/dev/null 2>&1; then
  git config --system http.proxy "$PROXY_URL" || true
  git config --system https.proxy "$PROXY_URL" || true
  git config --system http.noProxy "$NO_PROXY_VALUE" || true
fi

systemctl daemon-reload
systemctl enable systemd-timesyncd || true
systemctl enable systemd-time-wait-sync.service >/dev/null 2>&1 || true
systemctl enable force-ff0b-net.service
systemctl restart systemd-networkd || true
systemctl start force-ff0b-net.service

echo "Installed ff0b network profile for board: $BOARD_ID"
echo "Inventory file: $INVENTORY"
echo "Backup of previous /etc/systemd/network files: $NETWORKD_BACKUP"
echo "Active service: force-ff0b-net.service"
echo
echo "Verify with:"
echo "  systemctl status force-ff0b-net.service --no-pager"
echo "  journalctl -b -u force-ff0b-net.service --no-pager"
echo "  timedatectl status"
echo "  ip -br link"
echo "  ip -4 addr"
echo "  ip route"
