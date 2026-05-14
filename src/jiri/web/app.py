from __future__ import annotations

from dataclasses import asdict

from flask import Flask, jsonify, redirect, render_template, request, url_for

from jiri import __version__
from jiri.config import AppConfig
from jiri.runtime import JiriRuntime
from jiri.ui.view_model import build_display_view_model


def create_app(config: AppConfig | None = None, db_path: str | None = None) -> Flask:
    runtime = JiriRuntime.load(config=config, db_path=db_path)
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.jiri_runtime = runtime  # type: ignore[attr-defined]

    @app.context_processor
    def inject_globals():
        return {"app_name": runtime.config.assistant.name, "app_version": __version__}

    @app.get("/")
    def index():
        return redirect(url_for("screen"))

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
    def admin():
        snapshot = runtime.dashboard_snapshot(panel="system")
        return render_template(
            "admin.html",
            snapshot=snapshot,
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/focus/start")
    def focus_start():
        try:
            session = runtime.start_focus(
                minutes=_optional_int_form(request.form.get("minutes")),
                title=request.form.get("title", "Focus session"),
                todo_id=_optional_int_form(request.form.get("todo_id")),
            )
            return redirect(url_for("admin", notice=f"Started focus #{session.id}: {session.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("admin", error=str(exc)))

    @app.post("/focus/break")
    def focus_break():
        try:
            session = runtime.start_break(minutes=_optional_int_form(request.form.get("minutes")), title=request.form.get("title", "Break"))
            return redirect(url_for("admin", notice=f"Started break #{session.id}: {session.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("admin", error=str(exc)))

    @app.post("/focus/pause")
    def focus_pause():
        try:
            session = runtime.pause_focus()
            return redirect(url_for("admin", notice=f"Paused focus #{session.id}: {session.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("admin", error=str(exc)))

    @app.post("/focus/resume")
    def focus_resume():
        try:
            session = runtime.resume_focus()
            return redirect(url_for("admin", notice=f"Resumed focus #{session.id}: {session.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("admin", error=str(exc)))

    @app.post("/focus/complete")
    def focus_complete():
        try:
            session = runtime.complete_focus()
            return redirect(url_for("admin", notice=f"Completed focus #{session.id}: {session.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("admin", error=str(exc)))

    @app.post("/focus/cancel")
    def focus_cancel():
        try:
            session = runtime.cancel_focus()
            return redirect(url_for("admin", notice=f"Cancelled focus #{session.id}: {session.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("admin", error=str(exc)))

    @app.get("/todos")
    def todos_view():
        snapshot = runtime.dashboard_snapshot(panel="todos")
        return render_template(
            "todos.html",
            snapshot=snapshot,
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/todos")
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

    @app.post("/todos/<int:todo_id>/done")
    def todo_done(todo_id: int):
        try:
            todo = runtime.mark_todo_done(todo_id)
            return redirect(url_for("todos_view", notice=f"Done todo #{todo.id}: {todo.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("todos_view", error=str(exc)))

    @app.post("/todos/<int:todo_id>/cancel")
    def todo_cancel(todo_id: int):
        try:
            todo = runtime.cancel_todo(todo_id)
            return redirect(url_for("todos_view", notice=f"Cancelled todo #{todo.id}: {todo.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("todos_view", error=str(exc)))

    @app.post("/todos/<int:todo_id>/update")
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

    @app.post("/todos/<int:todo_id>/delete")
    def todo_delete(todo_id: int):
        try:
            todo = runtime.delete_todo(todo_id)
            return redirect(url_for("todos_view", notice=f"Deleted todo #{todo.id}: {todo.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("todos_view", error=str(exc)))

    @app.get("/notes")
    def notes_view():
        snapshot = runtime.dashboard_snapshot(panel="notes")
        return render_template(
            "notes.html",
            snapshot=snapshot,
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/notes")
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

    @app.post("/notes/<int:note_id>/delete")
    def note_delete(note_id: int):
        try:
            note = runtime.delete_note(note_id)
            return redirect(url_for("notes_view", notice=f"Deleted note #{note.id}: {note.title}"))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("notes_view", error=str(exc)))

    @app.post("/notes/<int:note_id>/update")
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

    @app.get("/weather")
    def weather_view():
        snapshot = runtime.dashboard_snapshot(panel="weather")
        return render_template(
            "weather.html",
            snapshot=snapshot,
            search_results=snapshot.search_results,
            provider_results=snapshot.provider_results,
            notice=request.args.get("notice", ""),
            error=request.args.get("error", ""),
        )

    @app.post("/weather/search")
    def weather_search():
        try:
            query = request.form.get("query", "")
            country = request.form.get("country") or None
            results = runtime.search_locations(query, country=country)
            runtime.save_location_search(results)
            return redirect(url_for("weather_view", notice=f"Found {len(results)} location(s)."))
        except Exception as exc:
            return redirect(url_for("weather_view", error=str(exc)))

    @app.post("/weather/select")
    def weather_select():
        try:
            selected = runtime.select_location(_int_form(request.form.get("index"), default=1))
            return redirect(url_for("weather_view", notice=f"Selected {selected.get('name')}."))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("weather_view", error=str(exc)))

    @app.post("/weather/set-coords")
    def weather_set_coords():
        try:
            selected = runtime.set_coordinates(
                request.form.get("name", ""),
                float(request.form.get("lat", "0")),
                float(request.form.get("lon", "0")),
            )
            return redirect(url_for("weather_view", notice=f"Selected coordinates for {selected.get('name')}."))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("weather_view", error=str(exc)))

    @app.post("/weather/refresh")
    def weather_refresh():
        try:
            runtime.refresh_weather()
            return redirect(url_for("weather_view", notice="Weather refreshed."))
        except (ValueError, RuntimeError) as exc:
            return redirect(url_for("weather_view", error=str(exc)))

    @app.post("/weather/providers")
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
    def api_todos_list():
        include_done = request.args.get("all", "false").lower() in {"1", "true", "yes", "on"}
        return jsonify([asdict(todo) for todo in runtime.list_todos(include_done=include_done)])

    @app.post("/api/todos")
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
    def api_todos_done(todo_id: int):
        try:
            return jsonify(asdict(runtime.mark_todo_done(todo_id)))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/todos/<int:todo_id>/cancel")
    def api_todos_cancel(todo_id: int):
        try:
            return jsonify(asdict(runtime.cancel_todo(todo_id)))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.delete("/api/todos/<int:todo_id>")
    def api_todos_delete(todo_id: int):
        try:
            return jsonify(asdict(runtime.delete_todo(todo_id)))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/notes")
    def api_notes_list():
        return jsonify([asdict(note) for note in runtime.list_notes()])

    @app.post("/api/notes")
    def api_notes_create():
        payload = _json_payload()
        try:
            note = runtime.add_note(str(payload.get("title") or ""), str(payload.get("body") or ""), tags=payload.get("tags") or None)
            return jsonify(asdict(note)), 201
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.put("/api/notes/<int:note_id>")
    def api_notes_update(note_id: int):
        payload = _json_payload()
        try:
            note = runtime.update_note(note_id, str(payload.get("title") or ""), str(payload.get("body") or ""), tags=payload.get("tags") or None)
            return jsonify(asdict(note))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.delete("/api/notes/<int:note_id>")
    def api_notes_delete(note_id: int):
        try:
            return jsonify(asdict(runtime.delete_note(note_id)))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/weather")
    def api_weather():
        return jsonify(runtime.screen_snapshot(panel="weather").weather)

    @app.post("/api/weather/refresh")
    def api_weather_refresh():
        try:
            return jsonify(runtime.refresh_weather())
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/focus")
    def api_focus():
        return jsonify(runtime.focus_snapshot())

    @app.post("/api/focus/start")
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
    def api_focus_break():
        payload = _json_payload()
        try:
            session = runtime.start_break(minutes=_optional_int_value(payload.get("minutes")), title=str(payload.get("title") or "Break"))
            return jsonify(asdict(session)), 201
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/focus/pause")
    def api_focus_pause():
        try:
            return jsonify(asdict(runtime.pause_focus()))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/focus/resume")
    def api_focus_resume():
        try:
            return jsonify(asdict(runtime.resume_focus()))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/focus/complete")
    def api_focus_complete():
        try:
            return jsonify(asdict(runtime.complete_focus()))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/focus/cancel")
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


if __name__ == "__main__":
    app = create_app()
    runtime = app.jiri_runtime  # type: ignore[attr-defined]
    app.run(host=runtime.config.web.host, port=runtime.config.web.port)
