from __future__ import annotations

from dataclasses import asdict
from functools import wraps
import hmac
import logging
import os

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for

from jiri import __version__
from jiri import db
from jiri.config import AppConfig
from jiri.runtime import JiriRuntime
from jiri import telegram
from jiri import persona_settings
from jiri.ui.view_model import build_display_view_model


def create_app(config: AppConfig | None = None, db_path: str | None = None, surface: str | None = None) -> Flask:
    runtime = JiriRuntime.load(config=config, db_path=db_path)
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = os.environ.get("JIRI_WEB_SECRET_KEY", "jiri-dev-web-secret-change-me")
    web_surface = _surface(surface or os.environ.get("JIRI_WEB_SURFACE", "all"))
    app.jiri_runtime = runtime  # type: ignore[attr-defined]
    app.jiri_surface = web_surface  # type: ignore[attr-defined]

    @app.before_request
    def enforce_surface():
        if _surface_allows(web_surface, request.path):
            return None
        abort(404)

    def admin_required(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not _admin_authenticated():
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
        }

    @app.get("/")
    def index():
        if web_surface == "screen":
            return redirect(url_for("screen"))
        return redirect(url_for("admin"))

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "POST":
            password = request.form.get("password", "")
            expected = os.environ.get("JIRI_ADMIN_PASSWORD", "test")
            if hmac.compare_digest(password, expected):
                session["jiri_admin_authenticated"] = True
                next_url = request.args.get("next") or url_for("admin")
                if not next_url.startswith("/admin") or next_url.startswith("/admin/login"):
                    next_url = url_for("admin")
                return redirect(next_url)
            return render_template("login.html", error="Bad password", notice="")
        return render_template("login.html", error=request.args.get("error", ""), notice=request.args.get("notice", ""))

    @app.post("/admin/logout")
    def admin_logout():
        session.pop("jiri_admin_authenticated", None)
        return redirect(url_for("admin_login", notice="Logged out."))

    @app.get("/screen")
    def screen():
        panel = request.args.get("panel", "auto")
        snapshot = runtime.screen_snapshot(panel=panel)
        display = build_display_view_model(snapshot)
        return render_template(
            "screen.html",
            snapshot=snapshot,
            display=display,
            requested_panel=panel,
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
            refresh_url=url_for("screen", panel=panel),
        )

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
            rows = _table_data(runtime.db_path, table, limit)
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

    @app.get("/admin/llama")
    @admin_required
    def llama_view():
        status = runtime.llama_status()
        logs = runtime.llama_logs(tail=40)
        return render_template(
            "llama.html",
            snapshot=runtime.dashboard_snapshot(panel="system"),
            llama_status=status,
            llama_logs=logs,
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/admin/llama/start")
    @admin_required
    def llama_start():
        try:
            result = runtime.llama_start(
                model_path=request.form.get("model_path") or None,
                port=_int_form(request.form.get("port"), default=None),
                context=_int_form(request.form.get("context"), default=None),
                threads=_int_form(request.form.get("threads"), default=None),
            )
            return redirect(url_for("llama_view", notice=f"Started llama server (PID {result['pid']})."))
        except Exception as exc:
            return redirect(url_for("llama_view", error=str(exc)))

    @app.post("/admin/llama/stop")
    @admin_required
    def llama_stop():
        try:
            pid = _int_form(request.form.get("pid"), default=None)
            result = runtime.llama_stop(pid=pid)
            if result.get("stopped"):
                return redirect(url_for("llama_view", notice="Llama server stopped."))
            return redirect(url_for("llama_view", notice=result.get("reason", "Already stopped.")))
        except Exception as exc:
            return redirect(url_for("llama_view", error=str(exc)))

    @app.post("/admin/llama/test")
    @admin_required
    def llama_test():
        try:
            port = _int_form(request.form.get("port"), default=None) or runtime.config.llm.server_port
            result = runtime.llama_test(port=port)
            notice = f"Server responded {result['status_code']}" if result["ok"] else f"Test failed: {result['response']}"
            return redirect(url_for("llama_view", notice=notice))
        except Exception as exc:
            return redirect(url_for("llama_view", error=str(exc)))

    @app.post("/admin/llama/test_chat")
    @admin_required
    def llama_test_chat():
        try:
            prompt = request.form.get("prompt", "Hello")
            result = runtime.llama_test_chat(prompt=prompt)
            if result["ok"]:
                return redirect(url_for("llama_view", notice=f"Model reply: {result['response']}"))
            return redirect(url_for("llama_view", error=f"Chat test failed: {result['response']}"))
        except Exception as exc:
            return redirect(url_for("llama_view", error=str(exc)))

    @app.get("/api/llama/status")
    def api_llama_status():
        return jsonify(runtime.llama_status())

    @app.get("/api/telegram/status")
    @admin_required
    def api_telegram_status():
        return jsonify(runtime.telegram_status())

    @app.get("/api/telegram/status-light")
    @admin_required
    def api_telegram_status_light():
        return jsonify(telegram.binding_status(config=runtime.config, db_path=runtime.db_path))

    @app.get("/api/status")
    def api_status():
        return jsonify(runtime.health_snapshot())

    @app.get("/api/screen")
    def api_screen():
        panel = request.args.get("panel", "auto")
        return jsonify(asdict(runtime.screen_snapshot(panel=panel)))

    @app.get("/api/display")
    def api_display():
        panel = request.args.get("panel", "auto")
        return jsonify(asdict(build_display_view_model(runtime.screen_snapshot(panel=panel))))

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
    def api_weather():
        return jsonify(runtime.screen_snapshot(panel="weather").weather)

    @app.get("/api/water")
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
        return path in {"/", "/screen", "/api/status", "/api/screen", "/api/display", "/api/weather", "/api/focus"}
    if surface == "admin":
        return not (path == "/screen" or path.startswith("/api/screen") or path.startswith("/api/display"))
    return False


def _admin_authenticated() -> bool:
    return session.get("jiri_admin_authenticated") is True


def main() -> None:
    if os.environ.get("JIRI_WEB_QUIET", "").strip().lower() in {"1", "true", "yes", "on"}:
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = create_app()
    runtime = app.jiri_runtime  # type: ignore[attr-defined]
    app.run(host=runtime.config.web.host, port=runtime.config.web.port)


if __name__ == "__main__":
    main()
