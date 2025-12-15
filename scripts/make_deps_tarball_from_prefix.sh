#!/bin/sh
set -eu

if [ $# -lt 2 ]; then
  echo "Usage: $0 <prefix_dir> <out_dir> [tarball_name]" >&2
  exit 2
fi

PREFIX_DIR="$1"
OUT_DIR="$2"
NAME="${3:-}"

if [ ! -d "$PREFIX_DIR" ]; then
  echo "ERROR: prefix dir not found: $PREFIX_DIR" >&2
  exit 2
fi

mkdir -p "$OUT_DIR"

if [ -z "$NAME" ]; then
  # You can override this when you know exact versions.
  NAME="daphne-deps-$(uname -s | tr '[:upper:]' '[:lower:]')-$(uname -m)-$(date +%Y%m%d).tar.gz"
fi

STAGE="$(mktemp -d)"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

mkdir -p "$STAGE/prefix/bin" "$STAGE/prefix/include" "$STAGE/prefix/lib" "$STAGE/prefix/share"

# Minimal bin
if [ -x "$PREFIX_DIR/bin/protoc" ]; then
  cp -f "$PREFIX_DIR/bin/protoc" "$STAGE/prefix/bin/"
fi

# Headers
for d in google absl; do
  if [ -d "$PREFIX_DIR/include/$d" ]; then
    mkdir -p "$STAGE/prefix/include/$d"
    cp -R "$PREFIX_DIR/include/$d" "$STAGE/prefix/include/"
  fi
done
for f in zmq.h zmq_utils.h; do
  if [ -f "$PREFIX_DIR/include/$f" ]; then
    cp -f "$PREFIX_DIR/include/$f" "$STAGE/prefix/include/"
  fi
done

# Libraries (copy common names; plus any abseil libs present in the prefix).
copy_glob() {
  pattern="$1"
  # shellcheck disable=SC2086
  for p in $pattern; do
    if [ -f "$p" ]; then
      cp -f "$p" "$STAGE/prefix/lib/"
    fi
  done
}

copy_glob "$PREFIX_DIR/lib/libzmq.so*"
copy_glob "$PREFIX_DIR/lib/libzmq.a"
copy_glob "$PREFIX_DIR/lib/libprotobuf.so*"
copy_glob "$PREFIX_DIR/lib/libprotobuf.a"
copy_glob "$PREFIX_DIR/lib/libprotoc.so*"
copy_glob "$PREFIX_DIR/lib/libprotoc.a"
copy_glob "$PREFIX_DIR/lib/libabsl_*.so*"
copy_glob "$PREFIX_DIR/lib/libabsl_*.a"

# pkg-config metadata (helps builds that use pkg-config).
if [ -d "$PREFIX_DIR/lib/pkgconfig" ]; then
  mkdir -p "$STAGE/prefix/lib/pkgconfig"
  cp -R "$PREFIX_DIR/lib/pkgconfig/." "$STAGE/prefix/lib/pkgconfig/"
fi
if [ -d "$PREFIX_DIR/share/pkgconfig" ]; then
  mkdir -p "$STAGE/prefix/share/pkgconfig"
  cp -R "$PREFIX_DIR/share/pkgconfig/." "$STAGE/prefix/share/pkgconfig/"
fi

TARBALL_PATH="$OUT_DIR/$NAME"
(cd "$STAGE" && tar -czf "$TARBALL_PATH" prefix)

SHA256="$(sha256sum "$TARBALL_PATH" | awk '{print $1}')"

echo "Created: $TARBALL_PATH"
echo ""
echo "Paste into daphne-server/deps/deps.lock.cmake:"
echo "set(DAPHNE_DEPS_TARBALL_NAME \"$NAME\")"
echo "set(DAPHNE_DEPS_TARBALL_SHA256 \"$SHA256\")"
