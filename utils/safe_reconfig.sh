#!/usr/bin/env bash
set -euo pipefail

APP="${1:-MEZ_STREAMING_V9_OL}"

# 1) stop anything in userland that pokes PL
sudo systemctl stop daphne-slowctrl daphne_slowctrl daphne-pl-setup hermes_udp_srv_daphne 2>/dev/null || true

unbind_dev() {
  local dev="$1"
  [ -e "$dev/driver/unbind" ] || return 0
  local name; name="$(basename "$dev")"
  echo "Unbinding $name"
  echo "$name" | sudo tee "$dev"/driver/unbind >/dev/null
}

bind_dev() {
  local dev="$1"
  # Rebind by echoing the device name to the driver's bind file
  [ -e "$dev/driver_override" ] && sudo sh -c "echo > '$dev/driver_override'" || true
  local drv;
  drv="$(basename "$(readlink -f "$dev/driver")" 2>/dev/null || true)"
  if [ -z "$drv" ]; then
    # Try common drivers if driver symlink isn't restored yet
    for d in /sys/bus/platform/drivers/xiic-i2c /sys/bus/platform/drivers/spi-xilinx; do
      [ -d "$d" ] || continue
      echo "Rebinding $(basename "$dev") to $(basename "$d")"
      echo "$(basename "$dev")" | sudo tee "$d/bind" >/dev/null || true
    done
  else
    echo "Rebinding $(basename "$dev") to $drv"
    echo "$(basename "$dev")" | sudo tee "/sys/bus/platform/drivers/$drv/bind" >/dev/null || true
  fi
}

# 2) enumerate PL I2C/SPI controllers (ONLY under amba_pl)
PL_BUS=/sys/devices/platform/amba_pl
mapfile -t PL_I2C < <(find "$PL_BUS" -maxdepth 2 -type d -regex '.*/[^/]*\(i2c\|xiic\)[^/]*' 2>/dev/null)
mapfile -t PL_SPI < <(find "$PL_BUS" -maxdepth 2 -type d -regex '.*/[^/]*spi[^/]*' 2>/dev/null)

echo "PL I2C: ${PL_I2C[*]:-none}"
echo "PL SPI: ${PL_SPI[*]:-none}"

# 3) unbind PL controllers
for d in "${PL_I2C[@]:-}"; do unbind_dev "$d"; done
for d in "${PL_SPI[@]:-}"; do unbind_dev "$d"; done

# 4) clean reconfig: unload, restart manager, load
sudo xmutil unloadapp || true
sudo systemctl restart dfx-mgr
sleep 1
sudo xmutil loadapp "$APP"

# 5) wait for PL to be back
for _ in {1..30}; do
  state="$(cat /sys/class/fpga_manager/fpga0/state 2>/dev/null || echo "unknown")"
  [ "$state" = "operating" ] && break
  sleep 0.2
done
echo "FPGA manager state: $state"

# 6) rebind PL controllers (only those that still exist)
for d in "${PL_I2C[@]:-}"; do [ -d "$d" ] && bind_dev "$d"; done
for d in "${PL_SPI[@]:-}"; do [ -d "$d" ] && bind_dev "$d"; done

# 7) bring your services back
sudo systemctl start daphne-slowctrl hermes_udp_srv_daphne 2>/dev/null || true
echo "Reconfig complete."
