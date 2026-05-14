from __future__ import annotations

import argparse
import sys

from . import db, health, notes, todos, weather
from .config import ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        cfg = load_config()
        db_path = cfg.database.path
        if args.command == "init-db":
            db.init_db(db_path)
            print(f"Initialized database: {db_path}")
            return 0
        if args.command == "todo":
            return _todo(args, db_path)
        if args.command == "note":
            return _note(args, db_path)
        if args.command == "weather":
            snapshot = weather.refresh_weather(db_path=db_path)
            print(f"{snapshot.location}: {snapshot.condition}")
            return 0
        if args.command == "status":
            print(health.format_health(health.health_snapshot(db_path=db_path, config=cfg)))
            return 0
        if args.command == "health":
            print(health.format_health(health.health_snapshot(db_path=db_path, config=cfg)))
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

    note = sub.add_parser("note", help="Manage notes")
    note_sub = note.add_subparsers(dest="note_command", required=True)
    note_add = note_sub.add_parser("add", help="Add a note")
    note_add.add_argument("title")
    note_add.add_argument("--body", required=True)
    note_add.add_argument("--tags")
    note_sub.add_parser("list", help="List notes")

    weather_parser = sub.add_parser("weather", help="Weather operations")
    weather_sub = weather_parser.add_subparsers(dest="weather_command", required=True)
    weather_sub.add_parser("refresh", help="Refresh weather cache when Stage 2 is implemented")

    return parser


def _todo(args: argparse.Namespace, db_path: str) -> int:
    if args.todo_command == "add":
        todo = todos.add_todo(args.title, due_at=args.due_at, description=args.description, priority=args.priority, db_path=db_path)
        print(f"Added todo #{todo.id}: {todo.title}")
        return 0
    if args.todo_command == "list":
        rows = todos.list_todos(include_done=args.all, db_path=db_path)
        if not rows:
            print("No todos.")
            return 0
        for todo in rows:
            due = f" due={todo.due_at}" if todo.due_at else ""
            print(f"#{todo.id} [{todo.status}] p{todo.priority}{due} {todo.title}")
        return 0
    if args.todo_command == "done":
        todo = todos.mark_done(args.id, db_path=db_path)
        print(f"Done todo #{todo.id}: {todo.title}")
        return 0
    if args.todo_command == "cancel":
        todo = todos.cancel_todo(args.id, db_path=db_path)
        print(f"Cancelled todo #{todo.id}: {todo.title}")
        return 0
    return 1


def _note(args: argparse.Namespace, db_path: str) -> int:
    if args.note_command == "add":
        note = notes.add_note(args.title, args.body, tags=args.tags, db_path=db_path)
        print(f"Added note #{note.id}: {note.title}")
        return 0
    if args.note_command == "list":
        rows = notes.list_notes(db_path=db_path)
        if not rows:
            print("No notes.")
            return 0
        for note in rows:
            tags = f" tags={note.tags}" if note.tags else ""
            print(f"#{note.id}{tags} {note.title}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
