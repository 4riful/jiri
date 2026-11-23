#!/usr/bin/env bash
# The pygame display. In WSL this opens a 480x320 SDL window; on the Pi set
# JIRI_DISPLAY_OUTPUT=fb to write straight to the SPI framebuffer.
set -eu
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

exec "$PYTHON_BIN" -m jiri.ui.pygame_app
