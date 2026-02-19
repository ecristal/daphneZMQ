#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root (use sudo)." >&2
  exit 1
fi

umask 022

install -d /etc/systemd/system /usr/local/bin /etc/default

REPO_ROOT_DEFAULT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
DAPHNE_ROOT="${DAPHNE_ROOT:-$REPO_ROOT_DEFAULT}"
DAPHNE_BUILD_DIR="${DAPHNE_BUILD_DIR:-$DAPHNE_ROOT/build-petalinux}"
DAPHNE_BIN="${DAPHNE_BIN:-$DAPHNE_BUILD_DIR/daphneServer}"
DAPHNE_BIND="${DAPHNE_BIND:-tcp://*:40001}"
DAPHNE_UTILS_DIR="${DAPHNE_UTILS_DIR:-$DAPHNE_ROOT/utils}"

if [ ! -f "$DAPHNE_UTILS_DIR/clk_conf.sh" ] || [ ! -f "$DAPHNE_UTILS_DIR/endpoint.sh" ]; then
  echo "ERROR: missing required utility scripts in $DAPHNE_UTILS_DIR" >&2
  exit 2
fi

cat <<'SERVICE_EOF' > /etc/systemd/system/firmware.service
[Unit]
Description=Program DAPHNE firmware (xmutil)
After=local-fs.target dfx-mgrd.service
Wants=dfx-mgrd.service
Before=hermes.service daphne.service endpoint.service

[Service]
Type=oneshot
EnvironmentFile=/etc/default/firmware
Environment=ACCEL_CONFIG_PATH=/lib/firmware/xilinx
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
XMUTIL="$(command -v xmutil || echo /usr/sbin/xmutil)"

# Make sure dfx-mgrd is available before loading the app.
if systemctl list-unit-files dfx-mgrd.service >/dev/null 2>&1; then
  systemctl is-active --quiet dfx-mgrd || systemctl start dfx-mgrd
fi

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

cat <<'HERMES_EOF' > /etc/systemd/system/hermes.service
[Unit]
Description=Hermes IPBus UDP server (DAPHNE mode)
After=firmware.service
Requires=firmware.service

[Service]
Type=simple
WorkingDirectory=/
ExecStartPre=/bin/echo Starting Hermes IPBus UDP server \(daphne mode\)
ExecStart=/bin/sh -c '/bin/hermes_udp_srv -d daphne -c true \
  2>/var/log/hermes_udp_srv.err >/var/log/hermes_udp_srv.log'
Restart=on-failure
RestartSec=1
TimeoutStopSec=5s

[Install]
WantedBy=multi-user.target
HERMES_EOF

cat <<DAPHNE_SVC_EOF > /etc/systemd/system/daphne.service
[Unit]
Description=DAPHNE Slow Controller
After=hermes.service firmware.service
Requires=firmware.service

[Service]
Type=simple
WorkingDirectory=${DAPHNE_BUILD_DIR}
ExecStart=${DAPHNE_BIN} --bind ${DAPHNE_BIND}
Restart=on-failure
RestartSec=1
TimeoutStopSec=5s

[Install]
WantedBy=multi-user.target
DAPHNE_SVC_EOF

cat <<ENDPOINT_SVC_EOF > /etc/systemd/system/endpoint.service
[Unit]
Description=Configure DAPHNE clock chip and timing endpoint
# ensure Daphne is fully up before running
After=daphne.service
Requires=daphne.service

[Service]
Type=oneshot
# wait a bit to ensure DaphneSlowController is accepting connections
ExecStartPre=/bin/sleep 5
WorkingDirectory=${DAPHNE_UTILS_DIR}
ExecStart=/bin/bash -c '${DAPHNE_UTILS_DIR}/clk_conf.sh && ${DAPHNE_UTILS_DIR}/endpoint.sh --configure --clock endpoint'
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
ENDPOINT_SVC_EOF

# Remove deprecated services/scripts from older flows.
systemctl disable --now spidev-restore.service 2>/dev/null || true
rm -f /etc/systemd/system/spidev-restore.service /usr/local/bin/spidev-restore.sh /usr/local/bin/fpga-quiesce.sh

chmod 0644 /etc/systemd/system/firmware.service /etc/systemd/system/dfx-mgrd.service /etc/systemd/system/hermes.service /etc/systemd/system/daphne.service /etc/systemd/system/endpoint.service /etc/default/firmware
chmod 0755 /usr/local/bin/daphne-fw.sh

systemctl daemon-reload
systemctl enable firmware.service hermes.service daphne.service endpoint.service

echo "Created /etc/systemd/system/firmware.service"
echo "Created /usr/local/bin/daphne-fw.sh"
echo "Created /etc/default/firmware"
echo "Created /etc/systemd/system/dfx-mgrd.service"
echo "Created /etc/systemd/system/hermes.service"
echo "Created /etc/systemd/system/daphne.service"
echo "Created /etc/systemd/system/endpoint.service"
echo "Configured DAPHNE_ROOT=${DAPHNE_ROOT}"
echo "Configured DAPHNE_BIN=${DAPHNE_BIN}"
echo "Configured DAPHNE_UTILS_DIR=${DAPHNE_UTILS_DIR}"
echo "Disabled and removed legacy spidev/I2C overlay helper units"
echo "Enabled: firmware.service hermes.service daphne.service endpoint.service"
