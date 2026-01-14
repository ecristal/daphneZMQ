#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root (use sudo)." >&2
  exit 1
fi

umask 022

install -d /etc/systemd/system /usr/local/bin /etc/default

cat <<'SERVICE_EOF' > /etc/systemd/system/firmware.service
[Unit]
Description=Program DAPHNE firmware (xmutil)
After=local-fs.target dfx-mgrd.service
Wants=dfx-mgrd.service
Before=hermes.service daphne.service

[Service]
Type=oneshot
EnvironmentFile=/etc/default/firmware
Environment=ACCEL_CONFIG_PATH=/lib/firmware/xilinx
ExecStartPre=/usr/local/bin/fpga-quiesce.sh
ExecStart=/usr/local/bin/daphne-fw.sh
TimeoutStartSec=20
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SERVICE_EOF

cat <<'DAPHNE_FW_EOF' > /usr/local/bin/daphne-fw.sh
#!/bin/sh
set -eu
APP="${APP:-MEZ_SELF_TRIG_V15_OL}"
# Make sure dfx-mgrd is up (no restart to avoid deadlocks)
systemctl is-active --quiet dfx-mgrd || systemctl start dfx-mgrd
XMUTIL="$(command -v xmutil || echo /usr/sbin/xmutil)"
echo "Loading ${APP} via ${XMUTIL} ..."
"${XMUTIL}" loadapp "${APP}"
# Wait up to ~10s for 'operating' state (non-blocking beyond that)
for i in $(seq 1 50); do
  st=$(cat /sys/class/fpga_manager/fpga0/state 2>/dev/null || echo unknown)
  [ "$st" = "operating" ] && break
  sleep 0.2
done
echo "FPGA state: $(cat /sys/class/fpga_manager/fpga0/state 2>/dev/null || echo unknown)"
DAPHNE_FW_EOF

cat <<'QUIESCE_EOF' > /usr/local/bin/fpga-quiesce.sh
#!/bin/sh
set -eu
# Mount configfs if not mounted
mountpoint -q /sys/kernel/config || mount -t configfs configfs /sys/kernel/config || true
# Drop any configfs DT overlays (fast, idempotent)
for d in /sys/kernel/config/device-tree/overlays/*; do
  [ -d "$d" ] && rmdir "$d" || true
done
# Try to unload any app cleanly; ignore errors
if command -v xmutil >/dev/null 2>&1; then xmutil unloadapp >/dev/null 2>&1 || true; fi
# Unbind common bus clients that collide with overlays (safe to ignore if absent)
echo spi2.0  > /sys/bus/spi/drivers/tpm_tis_spi/unbind  2>/dev/null || true
echo 1-0050  > /sys/bus/i2c/drivers/at24/unbind         2>/dev/null || true
echo 1-0011  > /sys/bus/i2c/drivers/pca9570/unbind      2>/dev/null || true
# If flags is present, clear any partial-program flags
[ -e /sys/class/fpga_manager/fpga0/flags ] && echo 0 > /sys/class/fpga_manager/fpga0/flags || true
QUIESCE_EOF

cat <<'DEFAULT_EOF' > /etc/default/firmware
APP=MEZ_SELF_TRIG_V15_OL 
DEFAULT_EOF

cat <<'DFX_MGRD_EOF' > /etc/systemd/system/dfx-mgrd.service
[Unit]
Description=Dynamic Function eXchange Manager (DFX)
After=local-fs.target
Wants=local-fs.target

[Service]
Type=simple
ExecStart=/usr/bin/dfx-mgrd
Restart=on-failure

[Install]
WantedBy=multi-user.target
DFX_MGRD_EOF

chmod 0644 /etc/systemd/system/firmware.service /etc/systemd/system/dfx-mgrd.service /etc/default/firmware
chmod 0755 /usr/local/bin/daphne-fw.sh /usr/local/bin/fpga-quiesce.sh

echo "Created /etc/systemd/system/firmware.service"
echo "Created /usr/local/bin/daphne-fw.sh"
echo "Created /usr/local/bin/fpga-quiesce.sh"
echo "Created /etc/default/firmware"
echo "Created /etc/systemd/system/dfx-mgrd.service"
