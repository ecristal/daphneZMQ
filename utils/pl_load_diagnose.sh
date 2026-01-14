#!/usr/bin/env bash
# pl_load_diagnose.sh — Diagnose PL app load issues on Kria/PetaLinux
# Safe to run multiple times; collects everything under /tmp/pl_diag_<ts>/
# Usage: sudo bash pl_load_diagnose.sh <APP_NAME> [--test-reg 0xADDR]

set -o pipefail

APP_NAME="$1"
shift || true

TEST_REG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --test-reg)
      TEST_REG="$2"; shift 2;;
    *)
      echo "Unknown arg: $1"; exit 1;;
  esac
done

if [[ -z "$APP_NAME" ]]; then
  echo "Usage: sudo bash $0 <APP_NAME> [--test-reg 0xADDR]"
  exit 1
fi

# --- Prep workspace
TS="$(date +%Y-%m-%d_%H-%M-%S)"
ROOT="/tmp/pl_diag_${TS}"
LOG="${ROOT}/diag.log"
mkdir -p "$ROOT"
exec > >(tee -a "$LOG") 2>&1

echo "=== PL Load Diagnosis ==="
echo "Timestamp: $TS"
echo "App: $APP_NAME"
echo "Test register: ${TEST_REG:-<none>}"
echo "Output dir: $ROOT"
echo

# --- Helpers
cmd_exists(){ command -v "$1" >/dev/null 2>&1; }
section(){ echo; echo "----- $* -----"; }
maybe(){ "$@" || true; }

# --- System snapshot
section "System snapshot"
echo "uname -a:"; uname -a || true
echo; echo "/etc/os-release:"; cat /etc/os-release || true
echo; echo "Kernel cmdline:"; cat /proc/cmdline || true
echo; echo "Uptime:"; uptime || true
echo; echo "Filesystem mount state:"; findmnt -rno TARGET,OPTIONS / || true

# --- XRT / tools
section "XRT / tooling versions"
maybe xmutil --version
maybe xbutil --version
maybe xbmgmt --version
maybe fdtoverlay -h | head -n1
maybe dtc -v

# --- Services of interest
section "Service status (dfx-mgrd, xrt if present)"
maybe systemctl status dfx-mgrd --no-pager
maybe systemctl is-enabled dfx-mgrd
maybe systemctl status xrt --no-pager
maybe systemctl is-enabled xrt

# --- Network / time (since we see PHY/clock warnings sometimes)
section "Clocks & PHY warnings (recent dmesg)"
maybe dmesg -T | tail -n 400 | egrep -i 'psgtr|phy|pll|clock|clk|macb|unable to generate target frequency|timeout' || true

# --- Apps present
section "xmutil listapps"
maybe xmutil listapps

# --- App package inspection
APP_DIR="/lib/firmware/xilinx/${APP_NAME}"
section "App package at ${APP_DIR}"
if [[ -d "$APP_DIR" ]]; then
  (cd "$APP_DIR" && ls -l)
  if cmd_exists jq && [[ -f "${APP_DIR}/shell.json" ]]; then
    echo; echo "shell.json (pretty):"
    jq . "${APP_DIR}/shell.json" || true
  else
    echo "shell.json:"; cat "${APP_DIR}/shell.json" 2>/dev/null || true
  fi
else
  echo "ERROR: ${APP_DIR} not found. Aborting."
  exit 2
fi

# Guess DTBO in the app folder
DTBO_CAND="$(ls -1 "${APP_DIR}"/*.dtbo 2>/dev/null | head -n1 || true)"
if [[ -n "$DTBO_CAND" ]]; then
  echo; echo "Found DTBO: ${DTBO_CAND}"
else
  echo; echo "No .dtbo found in ${APP_DIR} (may be OK if shell.json references a firmware-only load)."
fi

# --- Overlay dry-run (no PL programming)
if cmd_exists fdtoverlay && [[ -n "$DTBO_CAND" ]]; then
  section "fdtoverlay dry-run (merging ${DTBO_CAND} with live FDT)"
  OUT_DTB="${ROOT}/merged_${APP_NAME}.dtb"
  if sudo fdtoverlay -i /sys/firmware/fdt -o "${OUT_DTB}" "${DTBO_CAND}"; then
    echo "fdtoverlay dry-run: OK -> ${OUT_DTB}"
  else
    echo "fdtoverlay dry-run: FAILED (unresolved phandles, IRQ, clocks or duplicate nodes likely)."
  fi
else
  section "fdtoverlay dry-run"
  echo "Skipped (fdtoverlay not present or no dtbo)."
fi

# --- Quiesce userland that may touch PL
section "Quiescing userland (known suspects)"
maybe pgrep -fa Daphne || true
maybe pkill -f Daphne || true
maybe systemctl stop hermes_udp_srv_daphne.service || true

# --- Ensure clean baseline
section "Unload current app (if any) and reset fpga manager flags"
maybe xmutil unloadapp
if [[ -e /sys/class/fpga_manager/fpga0/flags ]]; then
  echo 0 | sudo tee /sys/class/fpga_manager/fpga0/flags >/dev/null || true
fi

# --- Start live dmesg capture
section "Start live kernel capture"
DMESG_LOG="${ROOT}/dmesg_follow.log"
( sudo dmesg -wT >> "${DMESG_LOG}" 2>&1 ) &
DMESG_PID=$!
echo "dmesg tail pid: ${DMESG_PID}"

# --- Attempt load
section "Attempting xmutil loadapp ${APP_NAME}"
LOAD_LOG="${ROOT}/xmutil_load.log"
( time sudo xmutil loadapp "${APP_NAME}" ) &> "${LOAD_LOG}"
LOAD_RC=$?
echo "xmutil loadapp rc=${LOAD_RC}"
echo "Load log stored at: ${LOAD_LOG}"

# --- Stop live dmesg capture
section "Stop live kernel capture"
maybe kill "${DMESG_PID}"
sleep 0.5
echo "Recent kernel lines around load:"
tail -n 200 "${DMESG_LOG}" | sed -e 's/^/DMESG | /'

# --- Gather dfx-mgrd journal
section "dfx-mgrd journal (this boot)"
maybe journalctl -u dfx-mgrd -b --no-pager | tail -n 400 | sed -e 's/^/DFX  | /'

# --- Common pattern scans
section "Scan for common overlay/IRQ/clock issues"
echo "Overlay warnings:"; egrep -i 'OF: overlay|memory leak will occur|__symbols__' "${DMESG_LOG}" || true
echo; echo "IRQ/INTC issues:"; egrep -i 'irq|intc|kind-of-intr|xilinx.*irq|irqchip' "${DMESG_LOG}" || true
echo; echo "DMA/AXI probe issues:"; egrep -i 'axidma|xilinx.*dma|probe failed|platform .* failed' "${DMESG_LOG}" || true
echo; echo "PHY/PLL/clock timeouts:"; egrep -i 'pll lock timeout|phy poweron failed|unable to generate target frequency|clk|clock' "${DMESG_LOG}" || true

# --- Optional safe register probe
if [[ -n "$TEST_REG" ]]; then
  section "Optional register probe at ${TEST_REG}"
  # Validate 32-bit alignment
  if (( ( (16#${TEST_REG#0x}) & 0x3 ) == 0 )); then
    echo "Reading 32-bit at ${TEST_REG}:"
    maybe devmem "${TEST_REG}" 32
  else
    echo "WARN: ${TEST_REG} is not 32-bit aligned; skipping devmem read."
  fi
fi

# --- Post state
section "Post state checks"
maybe xmutil listapps
echo; echo "FPGA manager state:"
maybe ls -l /sys/class/fpga_manager/fpga0/
maybe cat /sys/class/fpga_manager/fpga0/name 2>/dev/null
maybe cat /sys/class/fpga_manager/fpga0/state 2>/dev/null

# --- Summarise key findings
section "Summary (quick hints)"
if [[ $LOAD_RC -ne 0 ]]; then
  echo "- xmutil loadapp returned rc=${LOAD_RC} (see ${LOAD_LOG})."
else
  echo "- xmutil loadapp returned rc=0 (success status) — if the board later hangs, check for kernel oops in ${DMESG_LOG}."
fi

if egrep -qi 'kind-of-intr|irq.*mismatch|irq .* invalid' "${DMESG_LOG}"; then
  echo "- Detected IRQ controller/line mismatch in overlay (see 'kind-of-intr' lines). Re-check interrupt parent and flags in DTBO."
fi
if egrep -qi 'pll lock timeout|phy poweron failed' "${DMESG_LOG}"; then
  echo "- PHY/PLL power/lock timeouts seen — check GT/PSGTR lane assignments, refclks, and lane protocol in the overlay vs platform."
fi
if egrep -qi 'OF: overlay: WARNING: memory leak will occur' "${DMESG_LOG}"; then
  echo "- Overlay remove would leak props — typical when overlay symbols/properties conflict with base FDT; ensure DTBO matches kernel/base DTS."
fi
if egrep -qi 'probe failed|failed with error' "${DMESG_LOG}"; then
  echo "- Driver probe failures detected — inspect those device nodes in the DTBO (clocks/resets/compatible)."
fi

# --- Package artifacts
section "Pack results"
ART_TGZ="${ROOT}.tar.gz"
( cd /tmp && tar czf "${ART_TGZ##/tmp/}" "$(basename "$ROOT")" )
echo "Artifacts packed: ${ART_TGZ}"

echo
echo "Done."
