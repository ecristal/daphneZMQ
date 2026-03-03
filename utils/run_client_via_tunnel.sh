#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./utils/run_client_via_tunnel.sh <board> <client_script.py> [client args...]

Boards and local tunnel ports:
  daphne-13 -> 40113
  daphne-14 -> 40114
  daphne-15 -> 40115

Examples:
  ./utils/run_client_via_tunnel.sh daphne-13 client/protobuf_client_test.py
  ./utils/run_client_via_tunnel.sh daphne-14 client/configure_fe_min_v2.py
  ./utils/run_client_via_tunnel.sh daphne-15 client/vbias_monitor_once.py --timeout 3000
EOF
}

if [[ $# -lt 2 ]]; then
  usage
  exit 2
fi

BOARD="$1"
shift
CLIENT="$1"
shift

case "$BOARD" in
  daphne-13) LOCAL_PORT=40113 ;;
  daphne-14) LOCAL_PORT=40114 ;;
  daphne-15) LOCAL_PORT=40115 ;;
  *)
    echo "Unsupported board: $BOARD" >&2
    usage >&2
    exit 2
    ;;
esac

if [[ ! -f "$CLIENT" && -f "client/$CLIENT" ]]; then
  CLIENT="client/$CLIENT"
fi
if [[ ! -f "$CLIENT" ]]; then
  echo "Client script not found: $CLIENT" >&2
  exit 2
fi

# Ensure tunnel is active. LocalForward is configured in ~/.ssh/config.
if ! nc -z 127.0.0.1 "$LOCAL_PORT" >/dev/null 2>&1; then
  echo "Opening SSH tunnel for $BOARD on localhost:$LOCAL_PORT ..."
  ssh -fN "$BOARD"
  sleep 0.5
fi

if ! nc -z 127.0.0.1 "$LOCAL_PORT" >/dev/null 2>&1; then
  echo "Tunnel check failed on localhost:$LOCAL_PORT for $BOARD" >&2
  echo "Check ~/.ssh/config LocalForward and SSH auth for $BOARD." >&2
  exit 3
fi

PASSTHRU_ARGS=()
ARGS=("$@")
i=0
while [[ $i -lt ${#ARGS[@]} ]]; do
  arg="${ARGS[$i]}"
  case "$arg" in
    --ip|--host|-ip|--port|-port)
      # Drop user-supplied endpoint and replace with tunnel values.
      i=$((i + 2))
      ;;
    --ip=*|--host=*|-ip=*|--port=*|-port=*)
      # Drop user-supplied endpoint and replace with tunnel values.
      i=$((i + 1))
      ;;
    *)
      PASSTHRU_ARGS+=("$arg")
      i=$((i + 1))
      ;;
  esac
done

EXTRA_ARGS=()
if grep -Eq -- '--ip' "$CLIENT"; then
  EXTRA_ARGS+=(--ip 127.0.0.1)
elif grep -Eq -- '-ip' "$CLIENT"; then
  EXTRA_ARGS+=(-ip 127.0.0.1)
elif grep -Eq -- '--host' "$CLIENT"; then
  EXTRA_ARGS+=(--host 127.0.0.1)
fi

if grep -Eq -- '--port' "$CLIENT"; then
  EXTRA_ARGS+=(--port "$LOCAL_PORT")
elif grep -Eq -- '-port' "$CLIENT"; then
  EXTRA_ARGS+=(-port "$LOCAL_PORT")
fi

# configure_fe_min.py and endpoint.py use positional host/ip and port.
if [[ "$(basename "$CLIENT")" == "configure_fe_min.py" || "$(basename "$CLIENT")" == "endpoint.py" ]]; then
  EXTRA_ARGS+=(127.0.0.1 "$LOCAL_PORT")
fi

echo "Running $CLIENT against $BOARD through tcp://127.0.0.1:$LOCAL_PORT"
FINAL_ARGS=()
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  FINAL_ARGS+=("${EXTRA_ARGS[@]}")
fi
if [[ ${#PASSTHRU_ARGS[@]} -gt 0 ]]; then
  FINAL_ARGS+=("${PASSTHRU_ARGS[@]}")
fi

exec python3 "$CLIENT" "${FINAL_ARGS[@]}"
