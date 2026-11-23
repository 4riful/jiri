from __future__ import annotations

from dataclasses import asdict
from functools import wraps
import hmac
import logging
import os
from pathlib import Path
import secrets
import time

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for

from jiri import __version__
from jiri import db
from jiri.config import AppConfig
from jiri.runtime import JiriRuntime
from jiri import telegram
from jiri import persona_settings
from jiri import update_checker
from jiri import usage
from jiri import usage_accounts


def create_app(config: AppConfig | None = None, db_path: str | None = None, surface: str | None = None) -> Flask:
    runtime = JiriRuntime.load(config=config, db_path=db_path)
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = _load_secret_key(runtime.db_path)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Template hot reload is a dev-loop convenience (scripts/run_all.sh sets
    # JIRI_DEV=1); production on the Pi keeps compiled templates cached.
    app.config["TEMPLATES_AUTO_RELOAD"] = os.environ.get("JIRI_DEV", "").strip() == "1"
    web_surface = _surface(surface or os.environ.get("JIRI_WEB_SURFACE", "all"))
    app.jiri_runtime = runtime  # type: ignore[attr-defined]
    app.jiri_surface = web_surface  # type: ignore[attr-defined]
    login_failures: dict[str, list[float]] = {}

    @app.before_request
    def enforce_surface():
        if _surface_allows(web_surface, request.path):
            return None
        abort(404)

    @app.before_request
    def csrf_protect():
        if request.method not in _CSRF_METHODS or request.path in _CSRF_EXEMPT_PATHS:
            return None
        # The screen surface is loopback-only and has no session to hold a
        # token. Taps must be JSON, so a cross-site page cannot send one
        # without a CORS preflight (which this app never answers).
        if web_surface == "screen" and request.path == "/screen/tap":
            return None
        expected = session.get(_CSRF_SESSION_KEY)
        supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        if isinstance(expected, str) and expected and hmac.compare_digest(supplied.encode(), expected.encode()):
            return None
        if request.path.startswith("/api/"):
            return jsonify({"error": "missing or invalid CSRF token"}), 400
        return "Missing or invalid CSRF token. Reload the page and try again.", 400

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    def admin_required(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not _admin_authenticated():
                return redirect(url_for("admin_login", next=request.path))
            return func(*args, **kwargs)

        return wrapper

    def private_data(func):
        """Personal data (todos, notes, focus, water...) needs a login on the
        LAN-facing admin/all surfaces. The screen-only surface is bound to
        127.0.0.1 by the run scripts and has no login page, so it stays open."""

        @wraps(func)
        def wrapper(*args, **kwargs):
            if web_surface != "screen" and not _admin_authenticated():
                return redirect(url_for("admin_login", next=request.path))
            return func(*args, **kwargs)

        return wrapper

    @app.context_processor
    def inject_globals():
        return {
            "app_name": runtime.config.assistant.name,
            "app_version": __version__,
            "admin_authenticated": _admin_authenticated(),
            "web_surface": web_surface,
            "ui_theme": persona_settings.get_ui_theme(db_path=runtime.db_path),
            "csrf_token": _csrf_token,
        }

    @app.get("/")
    def index():
        if web_surface == "screen":
            return redirect(url_for("screen"))
        return redirect(url_for("admin"))

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        expected = _configured_admin_password()
        if expected is None:
            status = 503 if request.method == "POST" else 200
            return render_template("login.html", error="", notice="", password_configured=False), status
        if request.method == "POST":
            client = request.remote_addr or "unknown"
            now = time.monotonic()
            recent = [t for t in login_failures.get(client, []) if now - t < _LOGIN_WINDOW_SECONDS]
            if len(recent) >= _LOGIN_MAX_FAILURES:
                login_failures[client] = recent
                return (
                    render_template(
                        "login.html",
                        error="Too many failed logins. Wait a few minutes and try again.",
                        notice="",
                        password_configured=True,
                    ),
                    429,
                )
            password = request.form.get("password", "")
            if hmac.compare_digest(password.encode(), expected.encode()):
                login_failures.pop(client, None)
                # Fresh session on login: no fixation, new CSRF token.
                session.clear()
                session["jiri_admin_authenticated"] = True
                next_url = request.args.get("next") or url_for("admin")
                if not _safe_next(next_url):
                    next_url = url_for("admin")
                return redirect(next_url)
            recent.append(now)
            login_failures[client] = recent
            return render_template("login.html", error="Bad password", notice="", password_configured=True)
        return render_template(
            "login.html",
            error=request.args.get("error", ""),
            notice=request.args.get("notice", ""),
            password_configured=True,
        )

    @app.post("/admin/logout")
    def admin_logout():
        session.pop("jiri_admin_authenticated", None)
        return redirect(url_for("admin_login", notice="Logged out."))

    @app.get("/screen")
    @private_data
    def screen():
        panel = request.args.get("panel", "auto")
        snapshot = runtime.screen_snapshot(panel=panel)
        return render_template(
            "screen.html",
            snapshot=snapshot,
            png_url=url_for("screen_png", panel=panel),
        )

    @app.get("/screen.png")
    @private_data
    def screen_png():
        from jiri.ui.renderer import render_snapshot_png

        from jiri.ui.pygame_app import _read_state

        page = request.args.get("panel", "face")
        snapshot, reports = _read_state(runtime)
        if page not in {"face", "tasks", "notes", "weather", "water", "focus", "usage"}:
            page = "face"
        paused = request.args.get("paused") == "1"
        from jiri import ai

        def voice(category, mood, seed):
            return ai.pick(category, mood, seed, db_path=runtime.db_path)

        from jiri.ui import live

        live.shared_lock()  # one pygame lock for this route and the live stream
        png = render_snapshot_png(snapshot, usage=reports, page=page, paused=paused, voice=voice)
        response = app.response_class(png, mimetype="image/png")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/screen/live")
    @private_data
    def screen_live():
        """MJPEG stream of the real Stage running at ~10 FPS (blinks, gaze,
        springs, typing). The render thread only runs while someone watches."""
        from jiri.ui import live

        preview = live.get(runtime)
        preview.acquire()

        def frames():
            last, sent_at = 0, 0.0
            try:
                while True:
                    counter, data, mimetype = preview.wait_frame(last, timeout=2.0)
                    if counter == last:
                        # No new frame: restart a thread that died, and resend
                        # the last frame as a heartbeat so a gone client is
                        # noticed (the write fails and the generator closes).
                        preview.ensure_running()
                    last = counter
                    if data:
                        yield (
                            b"--frame\r\nContent-Type: " + mimetype.encode() + b"\r\n"
                            + b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n"
                        )
                    # Cap the stream at 12 fps whatever the render rate.
                    wait = _LIVE_MIN_INTERVAL - (time.monotonic() - sent_at)
                    if wait > 0:
                        time.sleep(wait)
                    sent_at = time.monotonic()
            finally:
                preview.release()

        response = app.response_class(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    @app.post("/screen/tap")
    @private_data
    def screen_tap():
        """A touch on the live preview, in 480x320 device coordinates."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "expected JSON {x, y}"}), 400
        try:
            x, y = float(payload.get("x")), float(payload.get("y"))
        except (TypeError, ValueError):
            return jsonify({"error": "x and y must be numbers"}), 400
        if x != x or y != y:  # NaN
            return jsonify({"error": "x and y must be numbers"}), 400
        from jiri.ui import live

        live.get(runtime).tap(x, y)
        return "", 204

    @app.get("/admin")
    @admin_required
    def admin():
        snapshot = runtime.dashboard_snapshot(panel="system")
        return render_template(
            "admin.html",
            snapshot=snapshot,
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/admin/update-check")
    @admin_required
    def update_check():
        status = update_checker.check_updates(repo_path=str(Path(__file__).resolve().parents[3]))
        message = str(status.get("message") or "Update check finished.")
        if status.get("status") == "update_available":
            message = f"{message} Local {status.get('local_sha')} / remote {status.get('remote_sha')}."
        if status.get("status") == "unavailable":
            return redirect(url_for("admin", error=message))
        return redirect(url_for("admin", notice=message))

    @app.get("/admin/focus")
    @admin_required
    def focus_view():
        snapshot = runtime.dashboard_snapshot(panel="focus")
        return render_template(
            "focus.html",
            snapshot=snapshot,
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/admin/focus/start")
    @admin_required
    def focus_start():
        try:
            session = runtime.start_focus(
                minutes=_optional_int_form(request.form.get("minutes")),
                title=request.form.get("title", "Focus session"),
                todo_id=_optional_int_form(request.form.get("todo_id")),
            )
            return redirect(url_for("focus_view", notice=f"Started focus #{session.id}: {session.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("focus_view", error=str(exc)))

    @app.post("/admin/focus/break")
    @admin_required
    def focus_break():
        try:
            session = runtime.start_break(minutes=_optional_int_form(request.form.get("minutes")), title=request.form.get("title", "Break"))
            return redirect(url_for("focus_view", notice=f"Started break #{session.id}: {session.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("focus_view", error=str(exc)))

    @app.post("/admin/focus/pause")
    @admin_required
    def focus_pause():
        try:
            session = runtime.pause_focus()
            return redirect(url_for("focus_view", notice=f"Paused focus #{session.id}: {session.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("focus_view", error=str(exc)))

    @app.post("/admin/focus/resume")
    @admin_required
    def focus_resume():
        try:
            session = runtime.resume_focus()
            return redirect(url_for("focus_view", notice=f"Resumed focus #{session.id}: {session.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("focus_view", error=str(exc)))

    @app.post("/admin/focus/complete")
    @admin_required
    def focus_complete():
        try:
            session = runtime.complete_focus()
            return redirect(url_for("focus_view", notice=f"Completed focus #{session.id}: {session.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("focus_view", error=str(exc)))

    @app.post("/admin/focus/cancel")
    @admin_required
    def focus_cancel():
        try:
            session = runtime.cancel_focus()
            return redirect(url_for("focus_view", notice=f"Cancelled focus #{session.id}: {session.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("focus_view", error=str(exc)))

    @app.get("/admin/todos")
    @admin_required
    def todos_view():
        snapshot = runtime.dashboard_snapshot(panel="todos")
        return render_template(
            "todos.html",
            snapshot=snapshot,
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/admin/todos")
    @admin_required
    def todos_add():
        try:
            todo = runtime.add_todo(
                request.form.get("title", ""),
                due_at=request.form.get("due_at") or None,
                description=request.form.get("description") or None,
                priority=_int_form(request.form.get("priority"), default=2),
            )
            return redirect(url_for("todos_view", notice=f"Added todo #{todo.id}: {todo.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("todos_view", error=str(exc)))

    @app.post("/admin/todos/<int:todo_id>/done")
    @admin_required
    def todo_done(todo_id: int):
        try:
            todo = runtime.mark_todo_done(todo_id)
            return redirect(url_for("todos_view", notice=f"Done todo #{todo.id}: {todo.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("todos_view", error=str(exc)))

    @app.post("/admin/todos/<int:todo_id>/cancel")
    @admin_required
    def todo_cancel(todo_id: int):
        try:
            todo = runtime.cancel_todo(todo_id)
            return redirect(url_for("todos_view", notice=f"Cancelled todo #{todo.id}: {todo.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("todos_view", error=str(exc)))

    @app.post("/admin/todos/<int:todo_id>/update")
    @admin_required
    def todo_update(todo_id: int):
        try:
            todo = runtime.update_todo(
                todo_id,
                request.form.get("title", ""),
                due_at=request.form.get("due_at") or None,
                description=request.form.get("description") or None,
                priority=_int_form(request.form.get("priority"), default=2),
            )
            return redirect(url_for("todos_view", notice=f"Updated todo #{todo.id}: {todo.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("todos_view", error=str(exc)))

    @app.post("/admin/todos/<int:todo_id>/delete")
    @admin_required
    def todo_delete(todo_id: int):
        try:
            todo = runtime.delete_todo(todo_id)
            return redirect(url_for("todos_view", notice=f"Deleted todo #{todo.id}: {todo.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("todos_view", error=str(exc)))

    @app.get("/admin/notes")
    @admin_required
    def notes_view():
        snapshot = runtime.dashboard_snapshot(panel="notes")
        return render_template(
            "notes.html",
            snapshot=snapshot,
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/admin/notes")
    @admin_required
    def notes_add():
        try:
            note = runtime.add_note(
                request.form.get("title", ""),
                request.form.get("body", ""),
                tags=request.form.get("tags") or None,
            )
            return redirect(url_for("notes_view", notice=f"Added note #{note.id}: {note.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("notes_view", error=str(exc)))

    @app.post("/admin/notes/<int:note_id>/delete")
    @admin_required
    def note_delete(note_id: int):
        try:
            note = runtime.delete_note(note_id)
            return redirect(url_for("notes_view", notice=f"Deleted note #{note.id}: {note.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("notes_view", error=str(exc)))

    @app.post("/admin/notes/<int:note_id>/update")
    @admin_required
    def note_update(note_id: int):
        try:
            note = runtime.update_note(
                note_id,
                request.form.get("title", ""),
                request.form.get("body", ""),
                tags=request.form.get("tags") or None,
            )
            return redirect(url_for("notes_view", notice=f"Updated note #{note.id}: {note.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("notes_view", error=str(exc)))

    @app.get("/admin/weather")
    @admin_required
    def weather_view():
        snapshot = runtime.dashboard_snapshot(panel="weather")
        return render_template(
            "weather.html",
            snapshot=snapshot,
            search_results=(),
            provider_results=snapshot.provider_results,
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.get("/admin/water")
    @admin_required
    def water_view():
        snapshot = runtime.dashboard_snapshot(panel="system")
        return render_template(
            "water.html",
            snapshot=snapshot,
            water_week=runtime.water_weekly_history(),
            water_month=runtime.water_monthly_history(),
            water_year=runtime.water_yearly_history(),
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/admin/water/add")
    @admin_required
    def water_add():
        try:
            snapshot = runtime.add_water(_int_form(request.form.get("amount_ml"), default=250))
            return redirect(url_for("water_view", notice=f"Added water. {snapshot['progress_ml']}ml / {snapshot['goal_ml']}ml."))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("water_view", error=str(exc)))

    @app.post("/admin/water/goal")
    @admin_required
    def water_goal():
        try:
            snapshot = runtime.set_water_goal(_int_form(request.form.get("goal_ml"), default=2150))
            return redirect(url_for("water_view", notice=f"Water goal set to {snapshot['goal_ml']}ml."))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("water_view", error=str(exc)))

    @app.post("/admin/water/age")
    @admin_required
    def water_age():
        try:
            snapshot = runtime.set_water_goal_by_profile(
                _int_form(request.form.get("age"), default=18),
                request.form.get("sex", "female"),
            )
            return redirect(url_for("water_view", notice=f"Profile water goal set to {snapshot['goal_ml']}ml."))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("water_view", error=str(exc)))

    @app.post("/admin/water/reset")
    @admin_required
    def water_reset():
        runtime.reset_water()
        return redirect(url_for("water_view", notice="Water progress reset."))

    @app.get("/admin/telegram")
    @admin_required
    def telegram_view():
        return render_template(
            "telegram.html",
            snapshot=runtime.dashboard_snapshot(panel="system"),
            telegram_status=telegram.binding_status(config=runtime.config, db_path=runtime.db_path),
            discovered_chats=(),
            chat_id_to_edit="",
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/admin/telegram/save")
    @admin_required
    def telegram_save():
        try:
            telegram.save_settings(
                enabled=request.form.get("enabled") == "1",
                bot_token=request.form.get("bot_token", ""),
                allowed_chat_ids=request.form.get("allowed_chat_ids", ""),
                command_chat_id=request.form.get("command_chat_id", ""),
                polling_timeout_seconds=_int_form(request.form.get("polling_timeout_seconds"), default=25),
                db_path=runtime.db_path,
                config=runtime.config,
            )
            if request.form.get("clear_token") == "1":
                telegram.clear_token(db_path=runtime.db_path, config=runtime.config)
            return redirect(url_for("telegram_view", notice="Telegram settings saved."))
        except Exception as exc:
            return redirect(url_for("telegram_view", error=str(exc)))

    @app.post("/admin/telegram/enable")
    @admin_required
    def telegram_enable():
        try:
            telegram.toggle_enabled(True, db_path=runtime.db_path, config=runtime.config)
            return redirect(url_for("telegram_view", notice="Telegram enabled."))
        except Exception as exc:
            return redirect(url_for("telegram_view", error=str(exc)))

    @app.post("/admin/telegram/disable")
    @admin_required
    def telegram_disable():
        try:
            telegram.toggle_enabled(False, db_path=runtime.db_path, config=runtime.config)
            return redirect(url_for("telegram_view", notice="Telegram disabled."))
        except Exception as exc:
            return redirect(url_for("telegram_view", error=str(exc)))

    @app.post("/admin/telegram/allowed/add")
    @admin_required
    def telegram_allowed_add():
        try:
            telegram.add_allowed_chat(request.form.get("chat_id", ""), db_path=runtime.db_path, config=runtime.config)
            return redirect(url_for("telegram_view", notice="Allowed chat added."))
        except Exception as exc:
            return redirect(url_for("telegram_view", error=str(exc)))

    @app.post("/admin/telegram/allowed/remove")
    @admin_required
    def telegram_allowed_remove():
        try:
            telegram.remove_allowed_chat(request.form.get("chat_id", ""), db_path=runtime.db_path, config=runtime.config)
            return redirect(url_for("telegram_view", notice="Allowed chat removed."))
        except Exception as exc:
            return redirect(url_for("telegram_view", error=str(exc)))

    @app.post("/admin/telegram/clear-token")
    @admin_required
    def telegram_clear_token():
        try:
            telegram.clear_token(db_path=runtime.db_path, config=runtime.config)
            return redirect(url_for("telegram_view", notice="Telegram token cleared."))
        except Exception as exc:
            return redirect(url_for("telegram_view", error=str(exc)))

    @app.post("/admin/telegram/reset-state")
    @admin_required
    def telegram_reset_state():
        telegram.reset_runtime_state(db_path=runtime.db_path)
        return redirect(url_for("telegram_view", notice="Telegram runtime state cleared."))

    @app.post("/admin/telegram/check")
    @admin_required
    def telegram_check():
        try:
            bot = telegram.check_bot_for_db(db_path=runtime.db_path, config=runtime.config)
            username = bot.get("username") or bot.get("first_name") or "unknown"
            return redirect(url_for("telegram_view", notice=f"Telegram bot reachable: @{username}."))
        except Exception as exc:
            return redirect(url_for("telegram_view", error=str(exc)))

    @app.post("/admin/telegram/discover")
    @admin_required
    def telegram_discover():
        try:
            chats = runtime.telegram_discover_chats()
            notice = f"Found {len(chats)} recent Telegram chat(s)." if chats else "No recent chats found. Send /start to the bot, then retry."
            return render_template(
                "telegram.html",
                snapshot=runtime.dashboard_snapshot(panel="system"),
                telegram_status=telegram.binding_status(config=runtime.config, db_path=runtime.db_path),
                discovered_chats=chats,
                chat_id_to_edit="",
                notice=notice,
                error="",
            )
        except Exception as exc:
            return redirect(url_for("telegram_view", error=str(exc)))

    @app.get("/admin/persona")
    @admin_required
    def persona_view():
        return render_template(
            "persona.html",
            settings=persona_settings.load_all(db_path=runtime.db_path),
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/admin/persona/save")
    @admin_required
    def persona_save():
        try:
            toggle_raw = request.form.get("toggle_theme", "").strip()
            if toggle_raw == "1":
                current = persona_settings.get_ui_theme(db_path=runtime.db_path)
                new_theme = "nothing" if current == "catppuccin" else "catppuccin"
                persona_settings.set_ui_theme(new_theme, db_path=runtime.db_path)
                return redirect(request.referrer or url_for("admin"))
            theme_raw = request.form.get("ui_theme", "").strip()
            if theme_raw:
                persona_settings.set_ui_theme(theme_raw, db_path=runtime.db_path)
            quiet_start = request.form.get("quiet_start", "").strip()
            quiet_end = request.form.get("quiet_end", "").strip()
            if quiet_start and quiet_end:
                persona_settings.set_quiet_hours(quiet_start, quiet_end, db_path=runtime.db_path)
            for cat in persona_settings.CATEGORIES:
                interval_raw = request.form.get(f"interval_{cat}", "").strip()
                if interval_raw:
                    persona_settings.set_interval(cat, int(interval_raw), db_path=runtime.db_path)
                enabled_raw = request.form.get(f"enabled_{cat}", "")
                persona_settings.set_enabled(cat, enabled_raw == "1", db_path=runtime.db_path)
            return redirect(url_for("persona_view", notice="Persona settings saved."))
        except (ValueError, TypeError) as exc:
            return redirect(url_for("persona_view", error=str(exc)))

    @app.get("/admin/db-browser")
    @admin_required
    def db_browser():
        table = request.args.get("table", "")
        try:
            limit = int(request.args.get("limit", "100"))
        except ValueError:
            limit = 100
        limit = max(1, min(limit, 1000))
        tables = _list_tables(runtime.db_path)
        if table and table in tables:
            rows = _mask_secrets(_table_data(runtime.db_path, table, limit))
            return render_template(
                "db_browser.html",
                tables=tables,
                table=table,
                rows=rows,
                limit=limit,
            )
        return render_template(
            "db_browser.html",
            tables=tables,
            table="",
            rows=(),
            limit=limit,
        )

    def _list_tables(db_path):
        with db.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        return [str(r["name"]) for r in rows]

    def _table_data(db_path, table, limit):
        with db.connect(db_path) as conn:
            cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
            column_names = [str(c["name"]) for c in cols]
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        return {"columns": column_names, "rows": [dict(r) for r in rows]}

    @app.post("/admin/weather/search")
    @admin_required
    def weather_search():
        try:
            query = request.form.get("query", "")
            country = request.form.get("country") or None
            results = runtime.search_locations(query, country=country)
            runtime.save_location_search(results)
            snapshot = runtime.dashboard_snapshot(panel="weather", search_results=results)
            return render_template(
                "weather.html",
                snapshot=snapshot,
                search_results=results,
                provider_results=snapshot.provider_results,
                notice=f"Found {len(results)} location(s).",
                error="",
            )
        except Exception as exc:
            return redirect(url_for("weather_view", error=str(exc)))

    @app.post("/admin/weather/select")
    @admin_required
    def weather_select():
        try:
            selected = runtime.select_location(_int_form(request.form.get("index"), default=1))
            runtime.refresh_weather_for_location(selected)
            return redirect(url_for("weather_view", notice=f"Selected {selected.get('name')} and refreshed weather."))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("weather_view", error=str(exc)))
        except Exception as exc:
            return redirect(url_for("weather_view", error=f"Location selected, but weather refresh failed: {exc}"))

    @app.post("/admin/weather/recent")
    @admin_required
    def weather_select_recent():
        try:
            selected = runtime.select_recent_location(_int_form(request.form.get("index"), default=1))
            runtime.refresh_weather_for_location(selected)
            return redirect(url_for("weather_view", notice=f"Selected {selected.get('name')} and refreshed weather."))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("weather_view", error=str(exc)))
        except Exception as exc:
            return redirect(url_for("weather_view", error=f"Location selected, but weather refresh failed: {exc}"))

    @app.post("/admin/weather/set-coords")
    @admin_required
    def weather_set_coords():
        try:
            selected = runtime.set_coordinates(
                request.form.get("name", ""),
                float(request.form.get("lat", "0")),
                float(request.form.get("lon", "0")),
            )
            runtime.refresh_weather_for_location(selected)
            return redirect(url_for("weather_view", notice=f"Selected coordinates for {selected.get('name')} and refreshed weather."))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("weather_view", error=str(exc)))
        except Exception as exc:
            return redirect(url_for("weather_view", error=f"Coordinates saved, but weather refresh failed: {exc}"))

    @app.post("/admin/weather/refresh")
    @admin_required
    def weather_refresh():
        try:
            runtime.refresh_weather()
            return redirect(url_for("weather_view", notice="Weather refreshed."))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("weather_view", error=str(exc)))

    @app.post("/admin/weather/providers")
    @admin_required
    def weather_providers():
        try:
            results = runtime.weather_test_providers()
            snapshot = runtime.dashboard_snapshot(panel="weather", provider_results=results)
            return render_template(
                "weather.html",
                snapshot=snapshot,
                search_results=snapshot.search_results,
                provider_results=results,
                notice=f"Tested {len(results)} provider(s).",
                error="",
            )
        except Exception as exc:
            snapshot = runtime.dashboard_snapshot(panel="weather")
            return render_template(
                "weather.html",
                snapshot=snapshot,
                search_results=snapshot.search_results,
                provider_results=snapshot.provider_results,
                notice="",
                error=str(exc),
            )

    @app.get("/admin/ai")
    @admin_required
    def ai_view():
        return render_template(
            "ai.html",
            snapshot=runtime.dashboard_snapshot(panel="ai"),
            ai_status=runtime.ai_status(),
            activity=runtime.ai_activity(),
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/admin/ai/refill")
    @admin_required
    def ai_refill():
        try:
            result = runtime.ai_refill()
            if result.get("skipped"):
                return redirect(url_for("ai_view", notice=f"Skipped: {result['skipped']}."))
            return redirect(url_for("ai_view", notice=(
                f"Refill made {result['calls']} call(s), stored {result['stored']} new line(s)."
            )))
        except Exception as exc:
            return redirect(url_for("ai_view", error=str(exc)))

    @app.post("/admin/ai/clear")
    @admin_required
    def ai_clear():
        try:
            removed = runtime.ai_clear_cache()
            return redirect(url_for("ai_view", notice=f"Cleared {removed} cached line(s)."))
        except Exception as exc:
            return redirect(url_for("ai_view", error=str(exc)))

    @app.post("/admin/ai/generate")
    @admin_required
    def ai_generate():
        category = (request.form.get("category") or "").strip()
        mood = (request.form.get("mood") or "").strip()
        try:
            result = runtime.ai_generate_bucket(category, mood)
        except ValueError as exc:
            return redirect(url_for("ai_view", error=str(exc)))
        except Exception as exc:
            return redirect(url_for("ai_view", error=f"Generate failed: {exc.__class__.__name__}"))
        if result.get("skipped"):
            return redirect(url_for("ai_view", notice=f"Skipped: {result['skipped']}."))
        if not result.get("ok"):
            return redirect(url_for("ai_view", error=f"No provider answered for {category}/{mood}. See Recent AI calls."))
        return redirect(url_for("ai_view", notice=(
            f"{category}/{mood}: {result.get('provider')} returned {result.get('returned', 0)}, "
            f"accepted {result.get('accepted', 0)}, stored {result.get('stored', 0)} new line(s)."
        )))

    @app.get("/api/ai/activity")
    def api_ai_activity():
        # Admin only, on every surface. JSON clients get a 401, not a login redirect.
        if not _admin_authenticated():
            return jsonify({"error": "admin login required"}), 401
        return jsonify(runtime.ai_activity())

    @app.get("/api/ai/status")
    @private_data
    def api_ai_status():
        return jsonify(runtime.ai_status())

    @app.get("/api/telegram/status")
    @admin_required
    def api_telegram_status():
        return jsonify(runtime.telegram_status())

    @app.get("/api/telegram/status-light")
    @admin_required
    def api_telegram_status_light():
        return jsonify(telegram.binding_status(config=runtime.config, db_path=runtime.db_path))

    @app.post("/api/usage")
    def api_usage_push():
        # Pushed from the owner's laptop (scripts/jiri_usage_push.py). Bearer
        # token, not the admin session: the collector has no browser login.
        # Accepts the admin-generated DB token and, for older setups, the
        # JIRI_USAGE_TOKEN env var (both compared in constant time).
        if not usage.push_enabled(runtime.db_path):
            return jsonify({"error": "usage push disabled"}), 503
        header = request.headers.get("Authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer" or not usage.check_push_token(supplied, db_path=runtime.db_path):
            return jsonify({"error": "unauthorized"}), 401
        try:
            report, stored = usage.record_if_changed(_json_payload(), db_path=runtime.db_path)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"stored": stored, "report": asdict(report)})

    @app.get("/api/usage")
    @admin_required
    def api_usage():
        return jsonify({provider: asdict(report) for provider, report in usage.latest(runtime.db_path).items()})

    @app.get("/api/usage/sources")
    @admin_required
    def api_usage_sources():
        return jsonify(
            {
                "sources": usage.sources_status(runtime.db_path),
                "shown": usage.shown_providers(runtime.db_path),
                "push": usage.token_status(runtime.db_path),  # masked only
                "accounts": usage_accounts.statuses(runtime.db_path),  # never tokens
                "fresh_seconds": usage.FRESH_SECONDS,
            }
        )

    # ------------------------------------------------------------ /admin/usage

    pending_logins: dict[str, dict[str, object]] = {}  # in-memory PKCE state, never in the cookie

    def _pending_for(provider: str) -> dict[str, object] | None:
        nonce = session.get(_USAGE_LOGIN_SESSION_KEY)
        entry = pending_logins.get(nonce) if isinstance(nonce, str) else None
        if not entry or entry.get("provider") != provider:
            return None
        if time.time() - float(entry.get("started", 0)) > _USAGE_LOGIN_TTL_SECONDS:
            pending_logins.pop(str(nonce), None)
            return None
        return entry

    def _render_usage(status_code: int = 200, **extra):
        nonce = session.get(_USAGE_LOGIN_SESSION_KEY)
        pending = pending_logins.get(nonce) if isinstance(nonce, str) else None
        if pending and time.time() - float(pending.get("started", 0)) > _USAGE_LOGIN_TTL_SECONDS:
            pending = None
        base_url = request.host_url.rstrip("/")
        repo = db.get_setting(_USAGE_REPO_SETTING, db_path=runtime.db_path) or _default_repo_path()
        context = {
            "title": "AI Usage",
            "sources": usage.sources_status(runtime.db_path),
            "shown": usage.shown_providers(runtime.db_path),
            "push": usage.token_status(runtime.db_path),
            "accounts": usage_accounts.statuses(runtime.db_path),
            "pending_login": pending,
            "revealed_token": None,
            "base_url": base_url,
            "repo_path": repo,
            "fresh_minutes": int(usage.FRESH_SECONDS // 60),
        }
        context.update(extra)
        context["snippets"] = _usage_snippets(base_url, repo, context["revealed_token"])
        return render_template("usage.html", **context), status_code

    @app.get("/admin/usage")
    @admin_required
    def usage_view():
        return _render_usage(notice=request.args.get("notice", "")[:200])

    @app.post("/admin/usage/token")
    @admin_required
    def usage_token():
        # The full value is shown exactly once, on this response. Afterwards
        # the page only ever shows the masked last four characters.
        token = usage.generate_push_token(runtime.db_path)
        return _render_usage(revealed_token=token, notice="New push token generated. The old one no longer works.")

    @app.post("/admin/usage/visibility")
    @admin_required
    def usage_visibility():
        for provider in sorted(usage.PROVIDERS):
            usage.set_shown(provider, request.form.get(f"show_{provider}") == "1", db_path=runtime.db_path)
        return redirect(url_for("usage_view", notice="Display providers saved."))

    @app.post("/admin/usage/clear")
    @admin_required
    def usage_clear():
        provider = request.form.get("provider", "")
        if provider not in usage.PROVIDERS:
            return _render_usage(400, error="Unknown provider.")
        usage.clear(provider, db_path=runtime.db_path)
        return redirect(url_for("usage_view", notice=f"Cleared stored {provider} usage."))

    @app.post("/admin/usage/repo")
    @admin_required
    def usage_repo():
        value = " ".join(request.form.get("repo_path", "").split())[:200]
        if value:
            db.set_setting(_USAGE_REPO_SETTING, value, db_path=runtime.db_path)
        else:
            db.delete_setting(_USAGE_REPO_SETTING, db_path=runtime.db_path)
        return redirect(url_for("usage_view", notice="Laptop repo path saved.") + "#connect")

    @app.post("/admin/usage/account/<provider>/connect")
    @admin_required
    def usage_account_connect(provider: str):
        if provider not in usage_accounts.PROVIDERS:
            abort(404)
        login = usage_accounts.start_login(provider)
        now = time.time()
        for key in [k for k, v in pending_logins.items() if now - float(v.get("started", 0)) > _USAGE_LOGIN_TTL_SECONDS]:
            pending_logins.pop(key, None)
        old = session.get(_USAGE_LOGIN_SESSION_KEY)
        if isinstance(old, str):
            pending_logins.pop(old, None)
        nonce = secrets.token_urlsafe(16)
        session[_USAGE_LOGIN_SESSION_KEY] = nonce
        pending_logins[nonce] = {**login, "started": now}
        return redirect(url_for("usage_view") + f"#account-{provider}")

    @app.post("/admin/usage/account/<provider>/complete")
    @admin_required
    def usage_account_complete(provider: str):
        if provider not in usage_accounts.PROVIDERS:
            abort(404)
        pending = _pending_for(provider)
        if pending is None:
            return _render_usage(400, error="That sign-in attempt expired. Click Connect again.")
        try:
            usage_accounts.complete_login(
                provider,
                request.form.get("pasted", ""),
                expected_state=str(pending["state"]),
                verifier=str(pending["verifier"]),
                db_path=runtime.db_path,
            )
        except ValueError as exc:
            return _render_usage(400, error=str(exc))
        pending_logins.pop(str(session.pop(_USAGE_LOGIN_SESSION_KEY, "")), None)
        result = usage_accounts.check_now(provider, db_path=runtime.db_path)
        notice = f"{provider_title(provider)} connected."
        if result.get("last_error"):
            notice += f" First usage check: {result['last_error']}"
        return redirect(url_for("usage_view", notice=notice) + f"#account-{provider}")

    @app.post("/admin/usage/account/<provider>/cancel")
    @admin_required
    def usage_account_cancel(provider: str):
        pending_logins.pop(str(session.pop(_USAGE_LOGIN_SESSION_KEY, "")), None)
        return redirect(url_for("usage_view") + f"#account-{provider}")

    @app.post("/admin/usage/account/<provider>/disconnect")
    @admin_required
    def usage_account_disconnect(provider: str):
        if provider not in usage_accounts.PROVIDERS:
            abort(404)
        usage_accounts.disconnect(provider, db_path=runtime.db_path)
        return redirect(url_for("usage_view", notice=f"{provider_title(provider)} disconnected.") + f"#account-{provider}")

    @app.post("/admin/usage/account/<provider>/check")
    @admin_required
    def usage_account_check(provider: str):
        if provider not in usage_accounts.PROVIDERS:
            abort(404)
        result = usage_accounts.check_now(provider, db_path=runtime.db_path)
        notice = f"{provider_title(provider)}: " + (str(result["last_error"]) if result.get("last_error") else "usage updated.")
        return redirect(url_for("usage_view", notice=notice) + f"#account-{provider}")

    def provider_title(provider: str) -> str:
        return str(usage_accounts.PROVIDERS[provider]["title"])

    app.add_template_filter(_ago, "ago")
    app.add_template_filter(_countdown, "countdown")
    app.add_template_filter(_pct, "pct")

    @app.get("/api/status")
    def api_status():
        snapshot = runtime.health_snapshot()
        if web_surface == "screen" or _admin_authenticated():
            return jsonify(snapshot)
        # Public health probe: nothing personal (no counts, paths or AI state).
        return jsonify(
            {
                "ok": True,
                "app_version": snapshot.get("app_version"),
                "database_writable": snapshot.get("database_writable"),
            }
        )

    @app.get("/api/screen")
    @private_data
    def api_screen():
        panel = request.args.get("panel", "auto")
        return jsonify(asdict(runtime.screen_snapshot(panel=panel)))

    @app.get("/api/todos")
    @admin_required
    def api_todos_list():
        include_done = request.args.get("all", "false").lower() in {"1", "true", "yes", "on"}
        return jsonify([asdict(todo) for todo in runtime.list_todos(include_done=include_done)])

    @app.post("/api/todos")
    @admin_required
    def api_todos_create():
        payload = _json_payload()
        try:
            todo = runtime.add_todo(
                str(payload.get("title") or ""),
                due_at=payload.get("due_at") or None,
                description=payload.get("description") or None,
                priority=_int_value(payload.get("priority"), default=2),
            )
            return jsonify(asdict(todo)), 201
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.put("/api/todos/<int:todo_id>")
    @admin_required
    def api_todos_update(todo_id: int):
        payload = _json_payload()
        try:
            todo = runtime.update_todo(
                todo_id,
                str(payload.get("title") or ""),
                due_at=payload.get("due_at") or None,
                description=payload.get("description") or None,
                priority=_int_value(payload.get("priority"), default=2),
            )
            return jsonify(asdict(todo))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/todos/<int:todo_id>/done")
    @admin_required
    def api_todos_done(todo_id: int):
        try:
            return jsonify(asdict(runtime.mark_todo_done(todo_id)))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/todos/<int:todo_id>/cancel")
    @admin_required
    def api_todos_cancel(todo_id: int):
        try:
            return jsonify(asdict(runtime.cancel_todo(todo_id)))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.delete("/api/todos/<int:todo_id>")
    @admin_required
    def api_todos_delete(todo_id: int):
        try:
            return jsonify(asdict(runtime.delete_todo(todo_id)))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/notes")
    @admin_required
    def api_notes_list():
        return jsonify([asdict(note) for note in runtime.list_notes()])

    @app.post("/api/notes")
    @admin_required
    def api_notes_create():
        payload = _json_payload()
        try:
            note = runtime.add_note(str(payload.get("title") or ""), str(payload.get("body") or ""), tags=payload.get("tags") or None)
            return jsonify(asdict(note)), 201
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.put("/api/notes/<int:note_id>")
    @admin_required
    def api_notes_update(note_id: int):
        payload = _json_payload()
        try:
            note = runtime.update_note(note_id, str(payload.get("title") or ""), str(payload.get("body") or ""), tags=payload.get("tags") or None)
            return jsonify(asdict(note))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.delete("/api/notes/<int:note_id>")
    @admin_required
    def api_notes_delete(note_id: int):
        try:
            return jsonify(asdict(runtime.delete_note(note_id)))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/weather")
    @private_data
    def api_weather():
        return jsonify(runtime.screen_snapshot(panel="weather").weather)

    @app.get("/api/water")
    @private_data
    def api_water():
        snapshot = runtime.water_snapshot()
        return jsonify(snapshot)

    @app.post("/api/weather/refresh")
    @admin_required
    def api_weather_refresh():
        try:
            return jsonify(runtime.refresh_weather())
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/focus")
    @private_data
    def api_focus():
        return jsonify(runtime.focus_snapshot())

    @app.post("/api/focus/start")
    @admin_required
    def api_focus_start():
        payload = _json_payload()
        try:
            session = runtime.start_focus(
                minutes=_optional_int_value(payload.get("minutes")),
                title=str(payload.get("title") or "Focus session"),
                todo_id=_optional_int_value(payload.get("todo_id")),
            )
            return jsonify(asdict(session)), 201
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/focus/break")
    @admin_required
    def api_focus_break():
        payload = _json_payload()
        try:
            session = runtime.start_break(minutes=_optional_int_value(payload.get("minutes")), title=str(payload.get("title") or "Break"))
            return jsonify(asdict(session)), 201
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/focus/pause")
    @admin_required
    def api_focus_pause():
        try:
            return jsonify(asdict(runtime.pause_focus()))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/focus/resume")
    @admin_required
    def api_focus_resume():
        try:
            return jsonify(asdict(runtime.resume_focus()))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/focus/complete")
    @admin_required
    def api_focus_complete():
        try:
            return jsonify(asdict(runtime.complete_focus()))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/focus/cancel")
    @admin_required
    def api_focus_cancel():
        try:
            return jsonify(asdict(runtime.cancel_focus()))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    return app


def _int_form(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


def _int_value(value: object, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _optional_int_form(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    return int(value)


def _optional_int_value(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _json_payload() -> dict[str, object]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


def _surface(value: str) -> str:
    clean = value.strip().lower()
    if clean in {"admin", "screen", "all"}:
        return clean
    raise ValueError("JIRI_WEB_SURFACE must be admin, screen, or all")


def _surface_allows(surface: str, path: str) -> bool:
    if path.startswith("/static/"):
        return True
    if surface == "all":
        return True
    if surface == "screen":
        return path in {
            "/", "/screen", "/screen.png", "/screen/live", "/screen/tap",
            "/api/status", "/api/screen", "/api/weather", "/api/focus",
        }
    if surface == "admin":
        return not (path in {"/screen", "/screen.png", "/screen/live", "/screen/tap"} or path.startswith("/api/screen"))
    return False


def _admin_authenticated() -> bool:
    return session.get("jiri_admin_authenticated") is True


_CSRF_SESSION_KEY = "jiri_csrf_token"
_CSRF_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# /api/usage is pushed by the laptop collector with a bearer token, no session.
_CSRF_EXEMPT_PATHS = frozenset({"/api/usage"})
_LIVE_MIN_INTERVAL = 1.0 / 12  # /screen/live never streams faster than 12 fps
_SECRET_KEY_SETTING = "web.secret_key"
_WEAK_ADMIN_PASSWORDS = frozenset({"test"})
_LOGIN_MAX_FAILURES = 5
_LOGIN_WINDOW_SECONDS = 300.0
_SECRET_MARKERS = ("token", "secret", "password", "api_key")


_USAGE_LOGIN_SESSION_KEY = "jiri_usage_login"
_USAGE_LOGIN_TTL_SECONDS = 15 * 60.0
_USAGE_REPO_SETTING = "usage.laptop_repo"


def _default_repo_path() -> str:
    return str(Path(__file__).resolve().parents[3])


def _usage_snippets(base_url: str, repo: str, token: str | None) -> dict[str, str]:
    """Copy-ready laptop setup text. Embeds the token only when it was just
    generated (the one-time reveal); otherwise a placeholder."""
    import json

    token_line = token or "<paste the token shown once after Generate/Rotate>"
    push = f"python3 {repo}/scripts/jiri_usage_push.py"
    usage_env = f"JIRI_URL={base_url}\nJIRI_USAGE_TOKEN={token_line}\n"
    statusline = json.dumps(
        {"statusLine": {"type": "command", "command": f"{push} claude-statusline --then '<your existing statusline command>'"}},
        indent=2,
    )
    return {
        "usage_env": usage_env,
        "usage_env_cmd": (
            "mkdir -p ~/.config/jiri && cat > ~/.config/jiri/usage.env <<'EOF'\n"
            + usage_env
            + "EOF\nchmod 600 ~/.config/jiri/usage.env"
        ),
        "statusline": statusline,
        "opencode": f"mkdir -p ~/.config/opencode/plugins && cp -r {repo}/integrations/opencode/jiri-usage ~/.config/opencode/plugins/",
        "cron": f"*/5 * * * * {push} opencode --quiet",
        "dry_run": f"{push} opencode --dry-run",
    }


def _ago(epoch: object, now: float | None = None) -> str:
    if epoch in (None, ""):
        return "never"
    seconds = max(0, int((time.time() if now is None else now) - float(epoch)))  # type: ignore[arg-type]
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m ago"
    return f"{seconds // 86400}d ago"


def _countdown(seconds: object) -> str:
    if seconds in (None, ""):
        return ""
    total = max(0, int(float(seconds)))  # type: ignore[arg-type]
    if total == 0:
        return "resetting"
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"resets in {days}d {hours}h"
    if hours:
        return f"resets in {hours}h {minutes}m"
    return f"resets in {minutes}m"


def _pct(value: object) -> str:
    if value in (None, ""):
        return "--"
    return f"{float(value):.0f}%"  # type: ignore[arg-type]


def _csrf_token() -> str:
    token = session.get(_CSRF_SESSION_KEY)
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session[_CSRF_SESSION_KEY] = token
    return token


def _configured_admin_password() -> str | None:
    """The admin password from the environment, or None when unset/default.

    There is deliberately no fallback: an unconfigured box refuses all logins.
    """
    value = os.environ.get("JIRI_ADMIN_PASSWORD", "")
    if not value.strip() or value.strip() in _WEAK_ADMIN_PASSWORDS:
        return None
    return value


def _load_secret_key(db_path: str) -> str:
    """JIRI_WEB_SECRET_KEY, else a random key generated once and kept in SQLite
    so sessions survive restarts (and the admin/screen processes agree)."""
    from_env = os.environ.get("JIRI_WEB_SECRET_KEY", "").strip()
    if from_env:
        return from_env
    existing = db.get_setting(_SECRET_KEY_SETTING, db_path=db_path)
    if existing:
        return existing
    with db.connect(db_path) as conn:
        # INSERT OR IGNORE: if another process won the race, keep its key.
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
            (_SECRET_KEY_SETTING, secrets.token_hex(32)),
        )
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (_SECRET_KEY_SETTING,)).fetchone()
    return str(row["value"])


def _safe_next(url: str) -> bool:
    if not url.startswith("/") or url.startswith("//") or url.startswith("/admin/login"):
        return False
    return url.startswith("/admin") or url == "/screen" or url.startswith("/screen?")


def _is_secret_name(name: object) -> bool:
    lowered = str(name).lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def _mask_value(value: object) -> object:
    if value is None:
        return None
    text = str(value)
    if not text:
        return text
    return "\u2022\u2022\u2022\u2022" + (text[-4:] if len(text) > 8 else "")


def _mask_secrets(data: dict[str, object]) -> dict[str, object]:
    """Hide credential values in the raw DB browser (settings rows whose key
    names a token/secret/password/api key, and any such column)."""
    columns = list(data.get("columns", []))  # type: ignore[arg-type]
    masked_rows = []
    for row in data.get("rows", []):  # type: ignore[union-attr]
        clean = dict(row)
        for col in columns:
            if _is_secret_name(col):
                clean[col] = _mask_value(clean.get(col))
        if "key" in clean and "value" in clean and _is_secret_name(clean["key"]):
            clean["value"] = _mask_value(clean["value"])
        masked_rows.append(clean)
    return {"columns": columns, "rows": masked_rows}


def main() -> None:
    if os.environ.get("JIRI_WEB_QUIET", "").strip().lower() in {"1", "true", "yes", "on"}:
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = create_app()
    runtime = app.jiri_runtime  # type: ignore[attr-defined]
    # Background work (minute tick + AI refill) lives here, in the long-running admin process, and
    # nowhere near the pygame UI thread. Started from main() rather than
    # create_app() so tests and the screen-only surface never spawn it.
    if app.jiri_surface != "screen" and not app.testing:  # type: ignore[attr-defined]
        from jiri import ai_worker

        ai_worker.start_background(runtime)
    app.run(host=runtime.config.web.host, port=runtime.config.web.port)


if __name__ == "__main__":
    main()
