from __future__ import annotations

from flask import Flask, jsonify

from jiri.config import load_config
from jiri.health import health_snapshot


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return "JIRI web dashboard starts in Stage 4. Core health API is available at /api/status."

    @app.get("/api/status")
    def api_status():
        cfg = load_config()
        return jsonify(health_snapshot(config=cfg))

    return app


if __name__ == "__main__":
    config = load_config()
    create_app().run(host=config.web.host, port=config.web.port)
