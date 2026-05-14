from __future__ import annotations

import argparse
import sys

from . import weather
from .config import ConfigError
from .runtime import JiriRuntime


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        runtime = JiriRuntime.load()
        if args.command == "init-db":
            runtime.init_db()
            print(f"Initialized database: {runtime.db_path}")
            return 0
        if args.command == "todo":
            return _todo(args, runtime)
        if args.command == "note":
            return _note(args, runtime)
        if args.command == "location":
            return _location(args, runtime)
        if args.command == "weather":
            if args.weather_command == "test-providers":
                print(_format_provider_tests(runtime.weather_test_providers()))
                return 0
            snapshot = runtime.refresh_weather()
            print(_format_weather(snapshot))
            return 0
        if args.command == "status":
            print(runtime.health_text())
            return 0
        if args.command == "health":
            print(runtime.health_text())
            return 0
        parser.print_help()
        return 1
    except (ValueError, ConfigError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m jiri.cli", description="JIRI SSH-friendly CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init-db", help="Create or update the SQLite database")
    sub.add_parser("status", help="Print JIRI status")
    sub.add_parser("health", help="Print JIRI health check")

    todo = sub.add_parser("todo", help="Manage todos")
    todo_sub = todo.add_subparsers(dest="todo_command", required=True)
    todo_add = todo_sub.add_parser("add", help="Add a todo")
    todo_add.add_argument("title")
    todo_add.add_argument("--due", dest="due_at")
    todo_add.add_argument("--description")
    todo_add.add_argument("--priority", type=int, default=2)
    todo_list = todo_sub.add_parser("list", help="List todos")
    todo_list.add_argument("--all", action="store_true", help="Include done and cancelled todos")
    todo_done = todo_sub.add_parser("done", help="Mark todo done")
    todo_done.add_argument("id", type=int)
    todo_cancel = todo_sub.add_parser("cancel", help="Cancel a todo")
    todo_cancel.add_argument("id", type=int)
    todo_delete = todo_sub.add_parser("delete", help="Delete a todo")
    todo_delete.add_argument("id", type=int)

    note = sub.add_parser("note", help="Manage notes")
    note_sub = note.add_subparsers(dest="note_command", required=True)
    note_add = note_sub.add_parser("add", help="Add a note")
    note_add.add_argument("title")
    note_add.add_argument("--body", required=True)
    note_add.add_argument("--tags")
    note_sub.add_parser("list", help="List notes")
    note_delete = note_sub.add_parser("delete", help="Delete a note")
    note_delete.add_argument("id", type=int)

    location = sub.add_parser("location", help="Manage weather location")
    location_sub = location.add_subparsers(dest="location_command", required=True)
    location_sub.add_parser("current", help="Show active weather location")
    location_search = location_sub.add_parser("search", help="Search Open-Meteo locations")
    location_search.add_argument("query")
    location_search.add_argument("--country", help="Sort matching country code first, e.g. BD")
    location_set = location_sub.add_parser("set", help="Select a result from the last location search")
    location_set.add_argument("index", type=int)
    location_coords = location_sub.add_parser("set-coords", help="Set weather coordinates manually")
    location_coords.add_argument("--name", required=True)
    location_coords.add_argument("--lat", type=float, required=True)
    location_coords.add_argument("--lon", type=float, required=True)

    weather_parser = sub.add_parser("weather", help="Weather operations")
    weather_sub = weather_parser.add_subparsers(dest="weather_command", required=True)
    weather_sub.add_parser("refresh", help="Refresh weather using cache/fallback")
    weather_sub.add_parser("test-providers", help="Manually test Open-Meteo and wttr.in providers")

    return parser


def _todo(args: argparse.Namespace, runtime: JiriRuntime) -> int:
    if args.todo_command == "add":
        todo = runtime.add_todo(args.title, due_at=args.due_at, description=args.description, priority=args.priority)
        print(f"Added todo #{todo.id}: {todo.title}")
        return 0
    if args.todo_command == "list":
        rows = runtime.list_todos(include_done=args.all)
        if not rows:
            print("No todos.")
            return 0
        for todo in rows:
            due = f" due={todo.due_at}" if todo.due_at else ""
            print(f"#{todo.id} [{todo.status}] p{todo.priority}{due} {todo.title}")
        return 0
    if args.todo_command == "done":
        todo = runtime.mark_todo_done(args.id)
        print(f"Done todo #{todo.id}: {todo.title}")
        return 0
    if args.todo_command == "cancel":
        todo = runtime.cancel_todo(args.id)
        print(f"Cancelled todo #{todo.id}: {todo.title}")
        return 0
    if args.todo_command == "delete":
        todo = runtime.delete_todo(args.id)
        print(f"Deleted todo #{todo.id}: {todo.title}")
        return 0
    return 1


def _note(args: argparse.Namespace, runtime: JiriRuntime) -> int:
    if args.note_command == "add":
        note = runtime.add_note(args.title, args.body, tags=args.tags)
        print(f"Added note #{note.id}: {note.title}")
        return 0
    if args.note_command == "list":
        rows = runtime.list_notes()
        if not rows:
            print("No notes.")
            return 0
        for note in rows:
            tags = f" tags={note.tags}" if note.tags else ""
            print(f"#{note.id}{tags} {note.title}")
        return 0
    if args.note_command == "delete":
        note = runtime.delete_note(args.id)
        print(f"Deleted note #{note.id}: {note.title}")
        return 0
    return 1


def _location(args: argparse.Namespace, runtime: JiriRuntime) -> int:
    if args.location_command == "current":
        print(weather.format_active_location(runtime.active_location()))
        return 0
    if args.location_command == "search":
        results = runtime.search_locations(args.query, country=args.country)
        runtime.save_location_search(results)
        if not results:
            print("No locations found.")
            return 0
        for index, item in enumerate(results, start=1):
            print(weather.format_location_result(index, item))
        return 0
    if args.location_command == "set":
        selected = runtime.select_location(args.index)
        print("Selected weather location:")
        print(weather.format_active_location({**selected, "source": "settings"}))
        return 0
    if args.location_command == "set-coords":
        selected = runtime.set_coordinates(args.name, args.lat, args.lon)
        print("Selected weather coordinates:")
        print(weather.format_active_location({**selected, "source": "settings"}))
        return 0
    return 1


def _format_weather(snapshot: dict[str, object]) -> str:
    temp = snapshot.get("temperature_c")
    temp_text = "unknown" if temp is None else f"{temp}C"
    humidity = snapshot.get("humidity")
    humidity_text = "unknown" if humidity is None else f"{humidity}%"
    rain = snapshot.get("rain_chance")
    rain_text = "unknown" if rain is None else f"{rain}%"
    feels = snapshot.get("feels_like_c")
    feels_text = "unknown" if feels is None else f"{feels}C"
    wind = snapshot.get("wind_kmh")
    wind_text = "unknown" if wind is None else f"{wind} km/h"
    meta = snapshot.get("location_meta")
    lines = [
        f"weather source: {snapshot.get('source')}",
        f"location: {snapshot.get('location')}",
        f"temperature: {temp_text}",
        f"feels like: {feels_text}",
        f"condition: {snapshot.get('condition')}",
        f"humidity: {humidity_text}",
        f"rain chance: {rain_text}",
        f"wind: {wind_text}",
        f"fetched at: {snapshot.get('fetched_at') or 'never'}",
        f"message: {snapshot.get('message')}",
    ]
    if isinstance(meta, dict):
        lines.insert(2, f"coordinates: {meta.get('latitude')}, {meta.get('longitude')}")
        if meta.get("country") or meta.get("country_code"):
            lines.insert(3, f"country: {meta.get('country') or 'unknown'} ({meta.get('country_code') or 'unknown'})")
        if meta.get("admin1") or meta.get("admin2") or meta.get("admin3"):
            lines.insert(4, f"area: {meta.get('admin1') or 'unknown'} / {meta.get('admin2') or 'unknown'} / {meta.get('admin3') or 'unknown'}")
    return "\n".join(lines)


def _format_provider_tests(results: list[dict[str, object]]) -> str:
    lines = []
    for result in results:
        status = "OK" if result.get("ok") else "FAILED"
        line = f"{result.get('provider')}: {status} in {result.get('response_ms')}ms"
        if result.get("ok"):
            line += f" | temp={result.get('temperature_c')}C | condition={result.get('condition')}"
        else:
            line += f" | error={result.get('error')}"
        lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
