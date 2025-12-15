#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BUILD_DIR="${1:-$ROOT_DIR/build-petalinux}"

if ! command -v cmake >/dev/null 2>&1; then
  echo "ERROR: cmake not found on this machine." >&2
  exit 2
fi

echo "ROOT_DIR=$ROOT_DIR"
echo "BUILD_DIR=$BUILD_DIR"

cmake -S "$ROOT_DIR" -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DDAPHNE_BUNDLE_ZEROMQ=ON \
  -DDAPHNE_BUILD_PY_PROTO=OFF

cmake --build "$BUILD_DIR" --parallel

echo "Built:"
ls -la "$BUILD_DIR/daphneServer" "$BUILD_DIR/daphne_zmq_server" 2>/dev/null || true
