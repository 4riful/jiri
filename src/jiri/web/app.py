from __future__ import annotations

from dataclasses import asdict

from flask import Flask, jsonify, redirect, render_template, request, url_for

from jiri import __version__
from jiri.config import AppConfig
from jiri.runtime import JiriRuntime


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
        return render_template(
            "screen.html",
            snapshot=snapshot,
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

    return app


def _int_form(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


if __name__ == "__main__":
    app = create_app()
    runtime = app.jiri_runtime  # type: ignore[attr-defined]
    app.run(host=runtime.config.web.host, port=runtime.config.web.port)
