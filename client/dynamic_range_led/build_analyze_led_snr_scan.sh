#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SCRIPT_DIR}/analyze_led_snr_scan.cpp"
OUT_DIR="${SCRIPT_DIR}/.build"
OUT="${OUT_DIR}/analyze_led_snr_scan"
SDKROOT="$(xcrun --show-sdk-path)"

mkdir -p "${OUT_DIR}"
g++ -std=c++17 -O3 -Wall -Wextra \
  -isysroot "${SDKROOT}" \
  -isystem "${SDKROOT}/usr/include/c++/v1" \
  "${SRC}" -o "${OUT}"
echo "${OUT}"
