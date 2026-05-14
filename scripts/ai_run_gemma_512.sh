#!/usr/bin/env bash
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/ai_common.sh"

MODEL_PATH=${JIRI_GEMMA_MODEL:-$HOME/models/gemma-3-270m-q4_k_m.gguf}
PORT=${JIRI_AI_PORT:-8080}

print_host_mode
require_real_pi_or_local_dev

if ! command_exists llama-server; then
  echo "llama-server not found in PATH" >&2
  exit 1
fi
if ! test -f "$MODEL_PATH"; then
  echo "model not found: $MODEL_PATH" >&2
  exit 1
fi
if command_exists ss && ss -ltn | grep -q ":$PORT "; then
  echo "port already in use: $PORT" >&2
  exit 1
fi

exec llama-server \
  -m "$MODEL_PATH" \
  -c 512 \
  -t 4 \
  --host 0.0.0.0 \
  --port "$PORT"
