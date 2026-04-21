#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

BUILD_DIR="${1:-$ROOT_DIR/build-petalinux}"
OUT_DIR="${2:-$ROOT_DIR/deploy}"
EXTRA_LIB_ROOTS="${3:-}"
LIB_ROOTS="$ROOT_DIR"
if [ -n "$EXTRA_LIB_ROOTS" ]; then
  LIB_ROOTS="$LIB_ROOTS:$EXTRA_LIB_ROOTS"
fi

BIN_SERVER="$BUILD_DIR/daphneServer"
BIN_REG="$BUILD_DIR/daphne_zmq_server"

if [ ! -x "$BIN_SERVER" ]; then
  echo "ERROR: missing executable: $BIN_SERVER" >&2
  echo "Run: $ROOT_DIR/scripts/petalinux_build.sh $BUILD_DIR" >&2
  exit 2
fi

mkdir -p "$OUT_DIR/bin" "$OUT_DIR/lib"
cp -f "$BIN_SERVER" "$OUT_DIR/bin/"
if [ -x "$BIN_REG" ]; then
  cp -f "$BIN_REG" "$OUT_DIR/bin/"
fi

copy_deps() {
  bin="$1"
  root_match() {
    dep_path="$1"
    old_ifs="$IFS"
    IFS=':'
    for r in $LIB_ROOTS; do
      [ -n "$r" ] || continue
      case "$dep_path" in
        "$r"/*)
          IFS="$old_ifs"
          return 0
          ;;
      esac
    done
    IFS="$old_ifs"
    return 1
  }

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
        if root_match "$dep"; then
          base="$(basename "$dep")"
          if [ ! -f "$OUT_DIR/lib/$base" ]; then
            cp -f "$dep" "$OUT_DIR/lib/$base"
          fi
        fi
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
