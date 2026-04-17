#!/bin/sh
set -eu

usage() {
  cat <<'EOF'
Usage:
  serve_d15_golden.sh rootfs [golden_dir]
  serve_d15_golden.sh boot [golden_dir]
  serve_d15_golden.sh file <relpath> <port> [golden_dir]

Defaults:
  golden_dir=/nfs/home/marroyav/golden/daphne14-2026-03-12

Examples:
  ./serve_d15_golden.sh rootfs
  ./serve_d15_golden.sh boot
  ./serve_d15_golden.sh file boot/system.dtb 9007
EOF
}

cmd="${1:-}"
default_golden="/nfs/home/marroyav/golden/daphne14-2026-03-12"

serve_once() {
  src="$1"
  port="$2"
  if [ ! -f "$src" ]; then
    echo "ERROR: missing file: $src" >&2
    exit 2
  fi
  echo "Serving $src on TCP port $port"
  nc -l "$port" < "$src"
}

case "$cmd" in
  rootfs)
    golden_dir="${2:-$default_golden}"
    img="$golden_dir/mmcblk0p2.ext4"
    gz="$golden_dir/mmcblk0p2.ext4.img.gz"
    if [ ! -f "$img" ]; then
      if [ ! -f "$gz" ]; then
        echo "ERROR: missing rootfs image: $img or $gz" >&2
        exit 2
      fi
      echo "Preparing uncompressed rootfs image at $img"
      gzip -dc "$gz" > "$img"
    fi
    echo "Serving rootfs with progress on TCP port 9002"
    dd if="$img" bs=1M status=progress | nc -l 9002
    ;;
  boot)
    golden_dir="${2:-$default_golden}"
    serve_once "$golden_dir/boot/BOOT.BIN" 9003
    serve_once "$golden_dir/boot/Image" 9004
    serve_once "$golden_dir/boot/boot.scr" 9005
    serve_once "$golden_dir/boot/ramdisk.cpio.gz.u-boot" 9006
    ;;
  file)
    relpath="${2:-}"
    port="${3:-}"
    golden_dir="${4:-$default_golden}"
    if [ -z "$relpath" ] || [ -z "$port" ]; then
      usage >&2
      exit 2
    fi
    serve_once "$golden_dir/$relpath" "$port"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
