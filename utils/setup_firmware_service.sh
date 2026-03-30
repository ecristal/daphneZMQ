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
FW_APP="${FW_APP:-}"
ENDPOINT_ADDR_HEX="${ENDPOINT_ADDR_HEX:-}"

if [ -z "$ENDPOINT_ADDR_HEX" ] && [ -r /etc/default/ff0b-net.conf ]; then
  # shellcheck disable=SC1091
  . /etc/default/ff0b-net.conf
fi
ENDPOINT_ADDR_HEX="${ENDPOINT_ADDR_HEX:-0x20}"

if [ -z "$FW_APP" ] && command -v xmutil >/dev/null 2>&1; then
  FW_APP=$(
    xmutil listapps 2>/dev/null | awk '
      tolower($0) ~ /accelerator/ { next }
      NF == 0 { next }
      $NF ~ /,$/ {
        app = $1
        gsub(/,/, "", app)
        if (app != "" && app != "_k26-starter-kits.disabled") {
          print app
          exit
        }
      }
    '
  )
fi

FW_APP="${FW_APP:-MEZ_SELF_TRIG_V15_OL_UPGRADED}"

if [ ! -f "$DAPHNE_UTILS_DIR/clk_conf.sh" ] || [ ! -f "$DAPHNE_UTILS_DIR/endpoint.sh" ]; then
  echo "ERROR: missing required utility scripts in $DAPHNE_UTILS_DIR" >&2
  exit 2
fi

cat <<'SERVICE_EOF' > /etc/systemd/system/firmware.service
[Unit]
Description=Program DAPHNE firmware (xmutil)
After=local-fs.target dfx-mgrd.service clockchip.service
Wants=dfx-mgrd.service clockchip.service
Before=hermes.service daphne.service endpoint.service

[Service]
Type=oneshot
EnvironmentFile=/etc/default/firmware
Environment=ACCEL_CONFIG_PATH=/lib/firmware/xilinx
ExecStart=/usr/local/bin/daphne-fw.sh
ExecStop=/usr/local/bin/daphne-fw-stop.sh
TimeoutStartSec=20
TimeoutStopSec=20
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SERVICE_EOF

cat <<'DAPHNE_FW_EOF' > /usr/local/bin/daphne-fw.sh
#!/bin/sh
set -eu
APP="${APP:-MEZ_SELF_TRIG_V15_OL_UPGRADED}"
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

cat <<'DAPHNE_FW_STOP_EOF' > /usr/local/bin/daphne-fw-stop.sh
#!/bin/sh
set -eu
XMUTIL="$(command -v xmutil || echo /usr/sbin/xmutil)"

if [ ! -x "$XMUTIL" ]; then
  echo "xmutil not found, skipping unloadapp." >&2
  exit 0
fi

echo "Unloading active firmware app via ${XMUTIL} ..."
"$XMUTIL" unloadapp || true
echo "FPGA state after stop: $(cat /sys/class/fpga_manager/fpga0/state 2>/dev/null || echo unknown)"
DAPHNE_FW_STOP_EOF

cat <<DEFAULT_EOF > /etc/default/firmware
APP=${FW_APP}
ENDPOINT_ADDR_HEX=${ENDPOINT_ADDR_HEX}
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

cat <<'CLOCKCHIP_EOF' > /etc/systemd/system/clockchip.service
[Unit]
Description=Configure DAPHNE external clock chip
After=local-fs.target
Wants=local-fs.target
Before=firmware.service endpoint.service hermes.service daphne.service

[Service]
Type=oneshot
WorkingDirectory=${DAPHNE_UTILS_DIR}
ExecStart=/bin/bash -c '${DAPHNE_UTILS_DIR}/clk_conf.sh'
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
CLOCKCHIP_EOF

cat <<'HERMES_EOF' > /etc/systemd/system/hermes.service
[Unit]
Description=Hermes IPBus UDP server (DAPHNE mode)
After=clockchip.service endpoint.service firmware.service
Requires=clockchip.service endpoint.service firmware.service
PartOf=clockchip.service firmware.service

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
After=clockchip.service endpoint.service hermes.service firmware.service
Requires=clockchip.service endpoint.service firmware.service
PartOf=clockchip.service firmware.service

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
Description=Configure DAPHNE timing endpoint
After=clockchip.service firmware.service
Requires=clockchip.service firmware.service
Before=hermes.service daphne.service
PartOf=clockchip.service firmware.service

[Service]
Type=oneshot
WorkingDirectory=${DAPHNE_UTILS_DIR}
ExecStart=/bin/bash -c '${DAPHNE_UTILS_DIR}/endpoint.sh --configure --clock endpoint --addr ${ENDPOINT_ADDR_HEX}'
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
ENDPOINT_SVC_EOF

# Remove deprecated services/scripts from older flows.
systemctl disable --now spidev-restore.service 2>/dev/null || true
rm -f /etc/systemd/system/spidev-restore.service /usr/local/bin/spidev-restore.sh /usr/local/bin/fpga-quiesce.sh

chmod 0644 /etc/systemd/system/firmware.service /etc/systemd/system/clockchip.service /etc/systemd/system/dfx-mgrd.service /etc/systemd/system/hermes.service /etc/systemd/system/daphne.service /etc/systemd/system/endpoint.service /etc/default/firmware
chmod 0755 /usr/local/bin/daphne-fw.sh /usr/local/bin/daphne-fw-stop.sh

systemctl daemon-reload
systemctl enable clockchip.service firmware.service hermes.service daphne.service endpoint.service

echo "Created /etc/systemd/system/firmware.service"
echo "Created /etc/systemd/system/clockchip.service"
echo "Created /usr/local/bin/daphne-fw.sh"
echo "Created /usr/local/bin/daphne-fw-stop.sh"
echo "Created /etc/default/firmware"
echo "Created /etc/systemd/system/dfx-mgrd.service"
echo "Created /etc/systemd/system/hermes.service"
echo "Created /etc/systemd/system/daphne.service"
echo "Created /etc/systemd/system/endpoint.service"
echo "Configured DAPHNE_ROOT=${DAPHNE_ROOT}"
echo "Configured DAPHNE_BIN=${DAPHNE_BIN}"
echo "Configured DAPHNE_UTILS_DIR=${DAPHNE_UTILS_DIR}"
echo "Configured FW_APP=${FW_APP}"
echo "Configured ENDPOINT_ADDR_HEX=${ENDPOINT_ADDR_HEX}"
echo "Disabled and removed legacy spidev/I2C overlay helper units"
echo "Enabled: clockchip.service firmware.service endpoint.service hermes.service daphne.service"
