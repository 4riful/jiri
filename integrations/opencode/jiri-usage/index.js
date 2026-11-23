// JIRI usage observer for OpenCode 2.x (server plugin, plain ESM, no deps).
//
// What it does
//   OpenCode's built-in ChatGPT provider talks to chatgpt.com/backend-api/codex.
//   Every response carries the plan's rate-limit windows as headers
//   (x-codex-primary-used-percent, -window-minutes, -reset-at, and the same for
//   "secondary"), and the WebSocket transport sends the same numbers as a
//   {"type":"codex.rate_limits"} frame. OpenCode only keeps them when a request
//   fails with 429. This plugin watches those responses through OpenCode's
//   documented session hooks ("http.response", "experimental.ws.receive") and
//   writes the latest windows to a small JSON file that
//   scripts/jiri_usage_push.py reads and pushes to JIRI.
//
// What it never does
//   It never reads request headers, auth/credential data or response bodies,
//   never changes a request/response/frame, and makes no network calls. It
//   copies only the numeric x-codex-{primary,secondary}-* values and plan type.
//
// Output (atomic replace, only when the numbers change or every 5 minutes):
//   ${JIRI_OPENCODE_LIMITS:-${XDG_CACHE_HOME:-~/.cache}/jiri/opencode-limits.json}
//   {"version":1,"captured_at":<epoch s>,"source":"http"|"ws","plan_type":"plus",
//    "model":"gpt-...","primary":{"used_percent":12,"window_minutes":300,"reset_at":<epoch s>},
//    "secondary":{...}}
//
// Install (OpenCode auto-discovers and hot-reloads ~/.config/opencode/plugins/*/):
//   mkdir -p ~/.config/opencode/plugins
//   ln -s /path/to/jiri/integrations/opencode/jiri-usage ~/.config/opencode/plugins/jiri-usage
//   opencode plugin list        # should list "jiri-usage"
// Uninstall: rm ~/.config/opencode/plugins/jiri-usage

import { mkdir, rename, writeFile } from "node:fs/promises"
import { homedir } from "node:os"
import { dirname, join } from "node:path"

const REFRESH_MS = 5 * 60 * 1000
const WINDOWS = ["primary", "secondary"]

export function outputPath(env = process.env) {
  if (env.JIRI_OPENCODE_LIMITS) return env.JIRI_OPENCODE_LIMITS
  const cache = env.XDG_CACHE_HOME || join(homedir(), ".cache")
  return join(cache, "jiri", "opencode-limits.json")
}

function num(value) {
  if (value === null || value === undefined || value === "") return undefined
  const n = Number(value)
  return Number.isFinite(n) ? n : undefined
}

// Headers -> {plan_type, primary, secondary} or undefined. `get` is Headers#get-like.
export function limitsFromHeaders(get, nowSeconds = Date.now() / 1000) {
  const out = {}
  for (const name of WINDOWS) {
    const used = num(get(`x-codex-${name}-used-percent`))
    if (used === undefined) continue
    let reset = num(get(`x-codex-${name}-reset-at`))
    const after = num(get(`x-codex-${name}-reset-after-seconds`))
    if (reset === undefined && after !== undefined) reset = Math.round(nowSeconds + after)
    out[name] = { used_percent: used, window_minutes: num(get(`x-codex-${name}-window-minutes`)) ?? null, reset_at: reset ?? null }
  }
  if (!out.primary && !out.secondary) return undefined
  const plan = get("x-codex-plan-type")
  if (typeof plan === "string" && plan) out.plan_type = plan.slice(0, 20)
  return out
}

// A {"type":"codex.rate_limits"} WebSocket frame -> same shape, or undefined.
export function limitsFromFrame(frame) {
  if (typeof frame !== "string" || !frame.includes("codex.rate_limits")) return undefined
  let event
  try {
    event = JSON.parse(frame)
  } catch {
    return undefined
  }
  if (!event || event.type !== "codex.rate_limits") return undefined
  const limitName = event.metered_limit_name || event.limit_name
  if (limitName && limitName !== "codex") return undefined // another meter, not the plan windows
  const details = event.rate_limits || {}
  const out = {}
  for (const name of WINDOWS) {
    const w = details[name]
    const used = w ? num(w.used_percent) : undefined
    if (used === undefined) continue
    out[name] = { used_percent: used, window_minutes: num(w.window_minutes) ?? null, reset_at: num(w.reset_at) ?? null }
  }
  if (!out.primary && !out.secondary) return undefined
  if (typeof event.plan_type === "string" && event.plan_type) out.plan_type = event.plan_type.slice(0, 20)
  return out
}

function modelName(input) {
  const model = input && input.model
  if (!model) return undefined
  const id = typeof model === "string" ? model : model.id || model.modelID
  return typeof id === "string" ? id.slice(0, 40) : undefined
}

export function createRecorder(path = outputPath()) {
  let lastKey = ""
  let lastWrite = 0
  let pending = Promise.resolve()
  return function record(limits, source, model) {
    if (!limits) return pending
    const key = JSON.stringify([limits, model])
    const now = Date.now()
    if (key === lastKey && now - lastWrite < REFRESH_MS) return pending
    lastKey = key
    lastWrite = now
    const body = JSON.stringify({ version: 1, captured_at: Math.round(now / 1000), source, model: model ?? null, ...limits })
    pending = pending
      .then(async () => {
        await mkdir(dirname(path), { recursive: true })
        const tmp = `${path}.${process.pid}.tmp`
        await writeFile(tmp, body + "\n", "utf8")
        await rename(tmp, path)
      })
      .catch(() => {}) // a full disk must never break a chat turn
    return pending
  }
}

export default {
  id: "jiri-usage",
  setup: async (ctx) => {
    const record = createRecorder()
    const registrations = []
    const hook = ctx && ctx.session && ctx.session.hook
    if (typeof hook !== "function") return
    const scope = { providerID: "openai" }
    registrations.push(
      await hook(
        "http.response",
        (input) => {
          try {
            const headers = input.response && input.response.headers
            if (!headers || typeof headers.get !== "function") return
            record(limitsFromHeaders((name) => headers.get(name)), "http", modelName(input))
          } catch {}
        },
        scope,
      ),
    )
    try {
      registrations.push(
        await hook(
          "experimental.ws.receive",
          (input) => {
            try {
              record(limitsFromFrame(input.frame), "ws", modelName(input))
            } catch {}
          },
          scope,
        ),
      )
    } catch {} // experimental hook may disappear in a later OpenCode
    return async () => {
      for (const r of registrations) await r?.dispose?.().catch?.(() => {})
    }
  },
}
