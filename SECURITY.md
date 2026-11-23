# Security Policy

## Supported versions

JIRI is pre-1.0 and ships from a single branch. Fixes land on `main` and nowhere else.

| Version | Supported |
| --- | --- |
| `main` (latest commit) | Yes |
| Any older tag or commit | No, update to `main` |

If you are running an older checkout, `docs/SAFE_UPDATE_METHODOLOGY.md` describes how to update
without losing your database. Back up first with `scripts/backup_db.sh`.

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Use GitHub's private vulnerability reporting:

1. Go to <https://github.com/4riful/jiri/security/advisories>.
2. Click **Report a vulnerability**.
3. Describe the issue, the version or commit you tested, and how to reproduce it.

> **TODO: add a real email address here as a fallback reporting channel.**
> Anyone without a GitHub account currently has no way to report privately.

What to expect: an acknowledgement within a week, and a fix or an explanation of why it is not
being fixed. This is a hobby project maintained by volunteers, so please be patient. If you plan
to disclose publicly, let us know your timeline and we will work to it.

Things that are useful in a report: the exact request or input, what you expected, what happened,
and whether it needs local network access or admin credentials.

## Secrets and API keys

**Never put a secret in a file that gets committed.**

`config.toml` is in `.gitignore` and is meant for local settings. `config.example.toml` is
committed and must stay free of real values. If you send a pull request that adds a key,
a token, or a password to any committed file, it will be rejected.

Keys belong in one of these places:

- **Environment variables** during development: `GEMINI_API_KEY`, `GROQ_API_KEY`,
  `JIRI_ADMIN_PASSWORD`, `JIRI_TELEGRAM_BOT_TOKEN`. JIRI also accepts `JIRI_`-prefixed variants
  of the provider keys so all app secrets can share one prefix.
- **systemd credentials** in production. Use `LoadCredential=` in the unit file, or an
  `EnvironmentFile=` owned by the service user with mode `0600`. Do not write keys into the
  `.service` files themselves, since those are world-readable by default.

The Telegram bot token is stored in SQLite once the database is initialised, and the database is
the source of truth from then on. `data/*.db`, `data/*.db-*`, `backups/*.db`, and `.env` are all
gitignored. Keep them that way, and remember that a SQLite backup contains the token.

If you have already committed a secret: rotate it first, then clean the history. Rotating is the
part that actually protects you.

## Threat posture

JIRI is a personal device on a personal network. Being clear about that is more useful than
claiming a security model the project does not have.

**What JIRI assumes:**

- It runs on a Raspberry Pi on a home LAN, used by one person.
- The admin dashboard is not exposed to the internet. There is no webhook, no port forward, and
  no public IP anywhere in the design. Telegram uses outbound `getUpdates` polling for exactly
  this reason.
- Anyone with physical access to the Pi or its SD card has the database. SQLite is not encrypted.

**What JIRI does defend:**

- The admin dashboard requires a password. The development default is `test`, which is fine on
  a laptop and is not fine on a device with a real database. Set `JIRI_ADMIN_PASSWORD`.
- Telegram enforces an allowlist of chat IDs. Commands from anyone else are ignored.
- The DB browser at `/admin/db-browser` is read-only. It cannot write, update, or delete rows.
- The update checker uses `git ls-remote` to compare against the configured upstream. It never
  runs `git pull`, never runs `git reset`, and never mutates the working tree.
- Every outbound request has a timeout, and every network feature has an offline fallback.

**If you expose JIRI beyond your LAN, that is on you.** `[web].host` defaults to `0.0.0.0`, so
the dashboard is reachable from your whole network as shipped. Put it behind a reverse proxy with
TLS and a real password, or leave it on the LAN.

### The AI layer

The required AI wording layer transmits **no user data**. This is structural, not a promise.

JIRI asks a provider for line *templates* containing `{task}` and `{minutes}` placeholders, and
fills those slots locally on the device. The outbound request body contains a category name, a
mood name, and a fixed style brief. There is no code path that puts a todo title, a note, a
location, a water log, or any other personal value into a request.

That is what makes a free API tier acceptable here even where the provider's terms allow training
on free-tier prompts: there is nothing personal in the prompt.

The layer requires a configured provider for production readiness, runs in a background worker
only, and is unreachable from the render path. See `docs/AI_SPEC.md` §1 and §3 for the invariants
and the tests that enforce them.

**A finding that shows user data reaching a provider is a security bug.** Report it through the
private channel above, not as a public issue.
