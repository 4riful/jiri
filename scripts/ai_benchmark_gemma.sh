#!/usr/bin/env bash
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/ai_common.sh"

BASE_URL=${JIRI_AI_BASE_URL:-http://127.0.0.1:8080}
REWRITE_LIMIT=${JIRI_AI_REWRITE_LIMIT_SECONDS:-8}
SUMMARY_LIMIT=${JIRI_AI_SUMMARY_LIMIT_SECONDS:-15}
MIN_FREE_MB=${JIRI_AI_MIN_FREE_MB:-150}
MAX_SWAP_MB=${JIRI_AI_MAX_SWAP_MB:-100}
MAX_TEMP_C=${JIRI_AI_MAX_TEMP_C:-75}

print_host_mode
require_real_pi_or_local_dev

if ! command_exists curl; then
  echo "curl not found" >&2
  exit 1
fi

health_status=$(curl -fsS --max-time 3 "$BASE_URL/health" || true)
if test -z "$health_status"; then
  echo "health_check: failed" >&2
  exit 1
fi
echo "health_check: ok"

measure_prompt() {
  name=$1
  limit=$2
  prompt=$3
  start=$(date +%s)
  curl -fsS --max-time "$limit" \
    -H 'Content-Type: application/json' \
    -d "{\"prompt\":\"$prompt\",\"n_predict\":80}" \
    "$BASE_URL/completion" >/tmp/jiri-ai-$name.json
  end=$(date +%s)
  elapsed=$((end - start))
  echo "$name latency_seconds=$elapsed limit=$limit"
  test "$elapsed" -le "$limit"
}

measure_prompt rewrite "$REWRITE_LIMIT" "Rewrite: Time to focus for 25 minutes. Keep it short."
measure_prompt summary "$SUMMARY_LIMIT" "Summarize: three todos, one overdue, weather cloudy. Keep it short."

free_mb=$(mem_available_mb)
swap_mb=$(swap_used_mb)
temp_c=$(cpu_temp_c)
echo "free_ram_mb=$free_mb min=$MIN_FREE_MB"
echo "swap_used_mb=$swap_mb max=$MAX_SWAP_MB"
echo "cpu_temp_c=$temp_c max=$MAX_TEMP_C"

test "$free_mb" -ge "$MIN_FREE_MB"
test "$swap_mb" -le "$MAX_SWAP_MB"
if test "$temp_c" != "unknown"; then
  awk "BEGIN {exit !($temp_c <= $MAX_TEMP_C)}"
fi

if is_raspberry_pi; then
  echo "benchmark_gate: passed_on_real_pi_candidate"
  echo "Reminder: Gemma is accepted only after this passes on real Raspberry Pi 3B with SSH responsive."
else
  echo "local_dev_benchmark: passed_on_this_machine"
  echo "benchmark_gate: not_accepted_requires_real_pi_3b"
fi
