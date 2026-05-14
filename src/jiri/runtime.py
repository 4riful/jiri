from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import db, health, notes, todos, weather
from .config import AppConfig, load_config
from .views import DashboardSnapshot, ScreenSnapshot, build_dashboard_snapshot, build_screen_snapshot


@dataclass(frozen=True)
class JiriRuntime:
    config: AppConfig
    db_path: str

    @classmethod
    def load(cls, config: AppConfig | None = None, db_path: str | None = None) -> "JiriRuntime":
        cfg = config or load_config()
        path = db_path or cfg.database.path
        db.init_db(path)
        return cls(config=cfg, db_path=path)

    def init_db(self) -> None:
        db.init_db(self.db_path)

    def add_todo(
        self,
        title: str,
        due_at: str | datetime | None = None,
        description: str | None = None,
        priority: int = 2,
    ):
        return todos.add_todo(title, due_at=due_at, description=description, priority=priority, db_path=self.db_path)

    def list_todos(self, include_done: bool = False):
        return todos.list_todos(include_done=include_done, db_path=self.db_path)

    def mark_todo_done(self, todo_id: int):
        return todos.mark_done(todo_id, db_path=self.db_path)

    def cancel_todo(self, todo_id: int):
        return todos.cancel_todo(todo_id, db_path=self.db_path)

    def delete_todo(self, todo_id: int):
        return todos.delete_todo(todo_id, db_path=self.db_path)

    def update_todo(
        self,
        todo_id: int,
        title: str,
        due_at: str | datetime | None = None,
        description: str | None = None,
        priority: int = 2,
    ):
        return todos.update_todo(todo_id, title, due_at=due_at, description=description, priority=priority, db_path=self.db_path)

    def add_note(self, title: str, body: str, tags: str | None = None):
        return notes.add_note(title, body, tags=tags, db_path=self.db_path)

    def list_notes(self):
        return notes.list_notes(db_path=self.db_path)

    def delete_note(self, note_id: int):
        return notes.delete_note(note_id, db_path=self.db_path)

    def update_note(self, note_id: int, title: str, body: str, tags: str | None = None):
        return notes.update_note(note_id, title, body, tags=tags, db_path=self.db_path)

    def search_locations(self, query: str, country: str | None = None):
        return weather.search_locations(query, country=country, timeout_seconds=self.config.weather.timeout_seconds)

    def save_location_search(self, results: list[dict[str, object]]) -> None:
        weather.save_last_location_search(results, db_path=self.db_path)

    def get_last_location_search(self) -> list[dict[str, object]]:
        return weather.get_last_location_search(db_path=self.db_path)

    def select_location(self, index: int):
        return weather.select_location(index, db_path=self.db_path)

    def set_coordinates(self, name: str, latitude: float, longitude: float):
        return weather.set_coordinates(name, latitude, longitude, db_path=self.db_path)

    def active_location(self):
        return weather.get_active_location(db_path=self.db_path, config=self.config)

    def refresh_weather(self):
        return weather.refresh_weather(db_path=self.db_path)

    def refresh_weather_for_location(self, location: dict[str, object]):
        return weather.refresh_weather_for_location(location, timeout_seconds=self.config.weather.timeout_seconds, db_path=self.db_path)

    def weather_test_providers(self):
        return weather.test_providers(db_path=self.db_path)

    def health_snapshot(self):
        return health.health_snapshot(db_path=self.db_path, config=self.config)

    def health_text(self) -> str:
        return health.format_health(self.health_snapshot())

    def screen_snapshot(self, panel: str | None = None, now: datetime | None = None) -> ScreenSnapshot:
        return build_screen_snapshot(db_path=self.db_path, config=self.config, panel=panel, now=now)

    def dashboard_snapshot(
        self,
        panel: str | None = None,
        now: datetime | None = None,
        search_results: list[dict[str, object]] | None = None,
        provider_results: list[dict[str, object]] | None = None,
        notice: str = "",
        error: str = "",
    ) -> DashboardSnapshot:
        return build_dashboard_snapshot(
            db_path=self.db_path,
            config=self.config,
            panel=panel,
            now=now,
            search_results=search_results,
            provider_results=provider_results,
            notice=notice,
            error=error,
        )
