#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

PREFIX_DIR="${1:-$HOME/zmq}"
BUILD_DIR="${2:-$ROOT_DIR/build-petalinux}"

if [ ! -d "$PREFIX_DIR" ]; then
  echo "ERROR: prefix dir not found: $PREFIX_DIR" >&2
  echo "Usage: $0 [prefix_dir(default: \$HOME/zmq)] [build_dir(default: ./build-petalinux)]" >&2
  exit 2
fi

if ! command -v cmake >/dev/null 2>&1; then
  echo "ERROR: cmake not found on this machine." >&2
  exit 2
fi

echo "ROOT_DIR=$ROOT_DIR"
echo "PREFIX_DIR=$PREFIX_DIR"
echo "BUILD_DIR=$BUILD_DIR"

cmake -S "$ROOT_DIR" -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="$PREFIX_DIR" \
  -DProtobuf_PROTOC_EXECUTABLE="$PREFIX_DIR/bin/protoc"

cmake --build "$BUILD_DIR" --parallel

echo "Built:"
ls -la "$BUILD_DIR/daphneServer" "$BUILD_DIR/daphne_zmq_server" 2>/dev/null || true
