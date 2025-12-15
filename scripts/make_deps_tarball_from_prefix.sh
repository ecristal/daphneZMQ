#!/bin/sh
set -eu

if [ $# -lt 2 ]; then
  echo "Usage: $0 <prefix_dir> <out_dir> [tarball_name]" >&2
  exit 2
fi

PREFIX_DIR="$1"
OUT_DIR="$2"
NAME_IN="${3-}"

if [ ! -d "$PREFIX_DIR" ]; then
  echo "ERROR: prefix dir not found: $PREFIX_DIR" >&2
  exit 2
fi

mkdir -p "$OUT_DIR"

if [ -n "${NAME_IN}" ]; then
  case "$NAME_IN" in
    */*)
      TARBALL_PATH="$NAME_IN"
      ;;
    *)
      TARBALL_PATH="$OUT_DIR/$NAME_IN"
      ;;
  esac
else
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m)"
  stamp="$(date +%Y%m%d)"
  NAME_IN="daphne-deps-${os}-${arch}-${stamp}.tar.gz"
  TARBALL_PATH="$OUT_DIR/$NAME_IN"
fi

if [ -z "${TARBALL_PATH}" ] || [ "${TARBALL_PATH}" = "/" ] || [ -d "${TARBALL_PATH}" ]; then
  echo "ERROR: invalid tarball output path: '${TARBALL_PATH}'" >&2
  exit 2
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
copy_glob "$PREFIX_DIR/lib/libprotobuf-lite.so*"
copy_glob "$PREFIX_DIR/lib/libprotobuf-lite.a"
copy_glob "$PREFIX_DIR/lib/libprotoc.so*"
copy_glob "$PREFIX_DIR/lib/libprotoc.a"
copy_glob "$PREFIX_DIR/lib/libutf8_validity.so*"
copy_glob "$PREFIX_DIR/lib/libutf8_validity.a"
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

tar -C "$STAGE" -czf "$TARBALL_PATH" prefix

if command -v sha256sum >/dev/null 2>&1; then
  SHA256="$(sha256sum "$TARBALL_PATH" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  SHA256="$(shasum -a 256 "$TARBALL_PATH" | awk '{print $1}')"
else
  echo "ERROR: sha256sum/shasum not found; cannot compute SHA256." >&2
  exit 2
fi

echo "Created: $TARBALL_PATH"
echo ""
echo "Paste into daphne-server/deps/deps.lock.cmake:"
echo "set(DAPHNE_DEPS_TARBALL_NAME \"$(basename "$TARBALL_PATH")\")"
echo "set(DAPHNE_DEPS_TARBALL_SHA256 \"$SHA256\")"
