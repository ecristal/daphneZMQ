#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INVENTORY="${INVENTORY:-$SCRIPT_DIR/ff0b_board_inventory.csv}"
INSTALLER="$SCRIPT_DIR/install_ff0b_network.sh"
SSH_USER="${SSH_USER:-petalinux}"

usage() {
  cat <<'USAGE_EOF'
Usage:
  ./deploy_ff0b_network.sh [board_id ...]

Examples:
  ./deploy_ff0b_network.sh daphne-13 daphne-14 daphne-15
  SSH_USER=petalinux ./deploy_ff0b_network.sh daphne-15

Notes:
  - This script copies installer + inventory to /tmp on each target.
  - It then runs: sudo sh /tmp/install_ff0b_network.sh <board_id>
  - If no board list is provided, all boards in the inventory are deployed.
USAGE_EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ ! -r "$INVENTORY" ]; then
  echo "ERROR: inventory not found: $INVENTORY" >&2
  exit 2
fi
if [ ! -r "$INSTALLER" ]; then
  echo "ERROR: installer not found: $INSTALLER" >&2
  exit 2
fi

if [ "$#" -eq 0 ]; then
  set -- $(
    awk -F',' '
      /^[ \t]*#/ { next }
      NF > 0 {
        gsub(/^[ \t]+|[ \t]+$/, "", $1)
        if ($1 != "") print $1
      }
    ' "$INVENTORY"
  )
fi

for board in "$@"; do
  host_fqdn=$(
    awk -F',' -v b="$board" '
      function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
      /^[ \t]*#/ { next }
      NF < 2 { next }
      {
        id = tolower(trim($1))
        if (id == tolower(b)) {
          print tolower(trim($2))
          exit
        }
      }
    ' "$INVENTORY"
  )
  target_host="${host_fqdn:-$board}"
  target="${SSH_USER}@${target_host}"
  echo "==> Deploying ff0b network config to ${target}"

  scp -O "$INSTALLER" "$INVENTORY" "${target}:/tmp/"
  ssh "$target" "sudo sh /tmp/install_ff0b_network.sh '${board}'"
done

echo
echo "Deployment completed."
