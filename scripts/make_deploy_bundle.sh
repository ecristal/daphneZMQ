#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

PREFIX_DIR="${1:-$HOME/zmq}"
BUILD_DIR="${2:-$ROOT_DIR/build-petalinux}"
OUT_DIR="${3:-$ROOT_DIR/deploy}"

BIN_SERVER="$BUILD_DIR/daphneServer"
BIN_REG="$BUILD_DIR/daphne_zmq_server"

if [ ! -x "$BIN_SERVER" ]; then
  echo "ERROR: missing executable: $BIN_SERVER" >&2
  echo "Run: $ROOT_DIR/scripts/petalinux_build.sh $PREFIX_DIR $BUILD_DIR" >&2
  exit 2
fi

mkdir -p "$OUT_DIR/bin" "$OUT_DIR/lib"
cp -f "$BIN_SERVER" "$OUT_DIR/bin/"
if [ -x "$BIN_REG" ]; then
  cp -f "$BIN_REG" "$OUT_DIR/bin/"
fi

copy_deps() {
  bin="$1"
  ldd "$bin" | while read -r a b c d; do
    # Typical forms:
    #   libfoo.so => /path/to/libfoo.so (0x...)
    #   /lib/ld-linux-aarch64.so.1 (0x...)
    #   libbar.so => not found
    if [ "${b:-}" = "=>" ] && [ "${c:-}" != "not" ] && [ -n "${c:-}" ]; then
      dep="$c"
    else
      dep="$a"
    fi

    case "$dep" in
      /*)
        case "$dep" in
          "$PREFIX_DIR"/*)
            base="$(basename "$dep")"
            if [ ! -f "$OUT_DIR/lib/$base" ]; then
              cp -f "$dep" "$OUT_DIR/lib/$base"
            fi
            ;;
        esac
        ;;
    esac
  done
}

copy_deps "$OUT_DIR/bin/$(basename "$BIN_SERVER")"
if [ -x "$OUT_DIR/bin/$(basename "$BIN_REG")" ]; then
  copy_deps "$OUT_DIR/bin/$(basename "$BIN_REG")"
fi

cat >"$OUT_DIR/run_daphneServer.sh" <<'EOF'
#!/bin/sh
set -eu
DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export LD_LIBRARY_PATH="$DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$DIR/bin/daphneServer" "$@"
EOF
chmod +x "$OUT_DIR/run_daphneServer.sh"

echo "Bundle ready: $OUT_DIR"
echo "Run: $OUT_DIR/run_daphneServer.sh --bind tcp://*:9876"
