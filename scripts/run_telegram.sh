#!/usr/bin/env bash
# Telegram admin bot: long-polls the Bot API, whitelisted chat IDs only.
set -eu
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

exec "$PYTHON_BIN" -m jiri.telegram poll
