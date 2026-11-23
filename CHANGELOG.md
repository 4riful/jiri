# Changelog

All notable changes to JIRI are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.0.0] — 2026-11-24

The first version of JIRI as a desk pet. Everything below is new; earlier
prototypes were a different design and are not carried forward.

### Display
- A pink-eyed face with pupils and glints, driven by spring physics: blinks,
  gaze, squash and stretch, heavy lids, blush. The eyes show the clock only
  during short time checks.
- An emotion engine (valence and arousal) that appraises your tasks, water,
  focus, weather, AI usage and the time of day, settles on one feeling, and
  says why on screen.
- A pet brain: pokes, tickles, grumpiness, yawns, sleeping and waking, and
  noticing when your data changes.
- Thoughts on the Home screen: a real fact plus a short LLM-written quip,
  revealed with a scramble effect.
- Screens: Home, Tasks, Notes, Weather, Water, Focus and AI usage, with splash
  wipes, automatic rotation, fading prev/next arrows and tap / double-tap
  controls.
- Runs on a Raspberry Pi 3B/3B+ with a 3.5" GPIO SPI panel (fbtft ILI9486),
  writing only changed rows to the framebuffer. A live preview of the display
  runs in the browser and accepts taps.

### AI
- Background-only wording from an OpenAI-compatible provider (FreeLLMAPI
  first), cached locally; the display never waits on the network. Offline
  fallback lines for every situation.
- An AI activity page in the admin: every call, model, latency, tokens and
  what was generated.

### AI usage
- Claude and ChatGPT 5-hour and weekly limits on the display, pushed from a
  laptop (Claude Code statusline, OpenCode plugin) or fetched by the Pi after
  signing in from the admin.

### Admin and security
- A LAN web dashboard for tasks, notes, water, focus, weather, AI and usage.
- Required admin password, CSRF protection, login rate limiting, private data
  behind login, secrets masked everywhere.
