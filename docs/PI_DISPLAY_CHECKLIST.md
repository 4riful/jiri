# Pi display confirmation checklist (3.5" SPI panel on the GPIO header)

The display code (`src/jiri/ui/output.py`) renders offscreen and writes the
panel's framebuffer directly, writing only 16-row bands that changed. Nothing
below has been confirmed on the real panel yet. Fill in each item on the Pi.

Run on the Pi:

| # | Check | Command | Result |
|---|---|---|---|
| 1 | Panel controller (ILI9486 / ILI9488 / other) and the overlay that binds it | `grep -i dtoverlay /boot/firmware/config.txt`, `dmesg \| grep -iE 'fb_\|ili\|mipi\|panel'` | |
| 2 | Which framebuffer is the panel | `cat /sys/class/graphics/fb*/name`, `cat /sys/class/graphics/fb*/virtual_size` | |
| 3 | Panel is 480x320 landscape (else fix `rotate=` in the overlay) | `cat /sys/class/graphics/fbN/virtual_size` should print `480,320` | |
| 4 | Bits per pixel (16 or 32 are supported) | `cat /sys/class/graphics/fbN/bits_per_pixel` | |
| 5 | Console not drawing over JIRI | `con2fbmap 1 0`, or remove `fbcon=map:` from cmdline.txt | |
| 6 | Colour order right (mint eyes, not purple) | `JIRI_DISPLAY_OUTPUT=fb ./scripts/run_ui.sh` and look | |
| 7 | Highest stable SPI speed without tearing or corruption | overlay `speed=` param | |
| 8 | Measured redraw rate: blink (eye band) and full frame | watch a blink; `top` for CPU | |
| 9 | Touch device found | `grep -A5 -iE 'ads7846\|touch' /proc/bus/input/devices` | |
| 10 | Touch axes and raw range | `evtest /dev/input/eventN`, tap all 4 corners | |
| 11 | Touch calibration works | set `JIRI_TOUCH_CAL="xmin,xmax,ymin,ymax[,swap]"` in `.env` and tap left/right | |
| 12 | Backlight controllable? (usually not; then sleep = dark UI) | `ls /sys/class/backlight` | |

Starting points, all unconfirmed:

- Waveshare-style ILI9486 on Bookworm/Trixie: `dtoverlay=piscreen,drm,speed=24000000,rotate=90`, or the vendor's `waveshare35a` overlay.
- Touch: `dtoverlay=ads7846,penirq=17,speed=2000000,xohms=100` if it is not bundled in the panel overlay.

Run the UI on the panel:

```sh
JIRI_DISPLAY_OUTPUT=fb JIRI_FB_DEVICE=/dev/fb1 PYTHONPATH=src .venv/bin/python -m jiri.ui.pygame_app
```

You can check the image without the panel: open `http://<pi-ip>:5000/screen` on
your laptop. It shows the same renderer as the panel, as a PNG.

## Confirmed on the real device (2026-11-24)

Pi 3 Model B, Debian 13 "trixie" 64-bit, kernel 6.18.50+rpt-rpi-v8, generic GPIO 3.5" 320x480 panel.

| Check | Result |
|---|---|
| Working display config | `dtparam=spi=on` + `dtoverlay=piscreen,speed=16000000,rotate=90` (NO `drm`). Loads `fb_ili9486` (fbtft, regwidth=16, buswidth=8) as a native 480x320 landscape framebuffer. |
| Did NOT work (plain white) | `piscreen,drm` at 24 MHz and 16 MHz (DRM `ili9486`, waveshare init). |
| Framebuffer number | Varies by boot (`fb0` or `fb1`); JIRI picks the non-HDMI one by name automatically. |
| Console | Must be kept off the panel: `fbcon=map:9` appended to `/boot/firmware/cmdline.txt` (backup `cmdline.txt.jiri-backup`). |
| Measured render cost | ~28 ms/frame on the face screen (budget 83 ms at 12 FPS); `jiri-ui` ~25-70% of one core. |
| Touch (ADS7846 on spi0.1, PENIRQ GPIO17) | Driver binds, but GPIO17 is held LOW permanently (even with `gpio=17=ip,pu`) and no interrupts fire. Likely constant pressure on the panel or a touch-layer/wiring fault. Unresolved. |
| Backups | `/boot/firmware/config.txt.jiri-backup` (original config). |
