# Hardware

One board does everything. There is no second worker Pi.

| Part | Target | Notes |
| --- | --- | --- |
| Board | Raspberry Pi 3B+ (3B also supported) | 4x Cortex-A53, 1 GB RAM. Everything is tuned for this. |
| Display | 3.5" SPI LCD on the GPIO header, 480x320 | Driven straight through `/dev/fbN`; no desktop needed. |
| Touch | Resistive (ads7846 / XPT2046 class) | Read from evdev, calibrated in software (`JIRI_TOUCH_CAL`). |
| Storage | microSD | A good one. JIRI keeps writes rare for this reason. |
| Power | 5 V 2.5 A | Under-voltage shows up in `vcgencmd get_throttled`. |
| Audio | none | JIRI is silent. |
| Control | Phone/laptop browser, SSH, optional Telegram | |

No model runs on the board; AI wording comes from hosted APIs
(`docs/AI_STRATEGY.md`).

## Unconfirmed

The exact panel controller, framebuffer number, rotation, touch axes and
usable SPI speed are unknown until measured. They are tracked as a checklist in
`docs/PI_DISPLAY_CHECKLIST.md`, and the remaining board facts in
`docs/STATUS.md`. Do not finalise display work by guessing them.
