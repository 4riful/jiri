# Performance Budgets

- Idle RAM for UI process: target under 180MB, hard limit 250MB.
- Idle RAM for web process: target under 100MB, hard limit 150MB.
- Total JIRI memory without LLM: target under 350MB.
- CPU idle average: target under 15%, hard limit 30%.
- UI target FPS: 10 to 15 FPS.
- UI must never block for network requests.
- UI frame loop must not perform HTTP requests.
- UI frame loop must not perform slow database scans.
- Weather fetch timeout: max 3 seconds.
- Worker Pi HTTP timeout: max 1 second.
- Web API response target: under 500ms locally.
- Telegram command response target: under 2 seconds.
- Startup target: under 30 seconds after login.
- Full boot-to-ready target with systemd: under 90 seconds.
- Database file target for v1: under 50MB.
- Logs must be rotated or limited.
- AI requests must be background only and must not block display refresh.
