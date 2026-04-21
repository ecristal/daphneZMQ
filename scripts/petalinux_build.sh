#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

BUILD_DIR="${1:-$ROOT_DIR/build-petalinux}"
DEPS_TARBALL_DIR="${2:-${DAPHNE_DEPS_TARBALL_DIR:-$ROOT_DIR/deps_tarballs}}"
LOCK_FILE="$ROOT_DIR/deps/deps.lock.cmake"

if [ ! -r "$LOCK_FILE" ]; then
  echo "ERROR: lock file not found: $LOCK_FILE" >&2
  exit 2
fi

if ! command -v cmake >/dev/null 2>&1; then
  echo "ERROR: cmake not found on this machine." >&2
  exit 2
fi

if [ ! -d "$DEPS_TARBALL_DIR" ]; then
  echo "ERROR: deps tarball dir not found: $DEPS_TARBALL_DIR" >&2
  echo "Usage: $0 [build_dir(default: ./build-petalinux)] [deps_tarball_dir(default: ./deps_tarballs)]" >&2
  exit 2
fi

TARBALL_NAME=$(
  sed -n 's/^set(DAPHNE_DEPS_TARBALL_NAME \"\(.*\)\")/\1/p' "$LOCK_FILE" | head -n 1
)
if [ -z "$TARBALL_NAME" ]; then
  echo "ERROR: could not parse DAPHNE_DEPS_TARBALL_NAME from $LOCK_FILE" >&2
  exit 2
fi

if [ ! -f "$DEPS_TARBALL_DIR/$TARBALL_NAME" ]; then
  echo "ERROR: required deps tarball not found: $DEPS_TARBALL_DIR/$TARBALL_NAME" >&2
  echo "Copy the pinned tarball into $DEPS_TARBALL_DIR and retry." >&2
  exit 2
fi

echo "ROOT_DIR=$ROOT_DIR"
echo "BUILD_DIR=$BUILD_DIR"
echo "DEPS_TARBALL_DIR=$DEPS_TARBALL_DIR"
echo "DEPS_TARBALL_NAME=$TARBALL_NAME"

cmake -S "$ROOT_DIR" -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DDAPHNE_DEPS_TARBALL_DIR="$DEPS_TARBALL_DIR"

cmake --build "$BUILD_DIR" --parallel

echo "Built:"
ls -la "$BUILD_DIR/daphneServer" "$BUILD_DIR/daphne_zmq_server" 2>/dev/null || true
